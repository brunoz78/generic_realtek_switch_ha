"""
Direct CGI scraper for the original Realtek-based web interface (HORACO, keepLink and other OEM switches).

Ported from https://github.com/byte4geek/switch-dashboard (scraper.py)
into async aiohttp for native Home Assistant use — no intermediate service.

Auth flow:
  1. MD5(username + password)  →  POST /login.cgi
  2. Cookie jar carries the session
  3. /info.cgi       → device info + port link/speed table
  4. /port.cgi       → admin enabled/disabled state per port
  5. /port.cgi?page=stats → TX/RX packet, error (and, if reported, byte) counters
  6. POST /reboot.cgi {"cmd":"reboot"} → remote reboot
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from .const import (
    CGI_INFO,
    CGI_LOGIN,
    CGI_PORT_CFG,
    CGI_PORT_STATS,
    CGI_REBOOT,
    PORT_STATUS_DISABLED,
    PORT_STATUS_DOWN,
    PORT_STATUS_UP,
)

_LOGGER = logging.getLogger(__name__)

# Small inter-request delay to avoid session thrashing the uIP micro-controller
# (same rationale as the original switch-dashboard scraper.py)
_REQUEST_DELAY = 0.4

# Some firmware (e.g. V1.9) occasionally closes a connection without a reply
_MAX_ATTEMPTS = 3
_RETRY_DELAY = 1.0


@dataclass
class PortData:
    """All data for a single physical switch port."""
    port: str                 # "1", "2", … "9"
    status: str               # "up" | "down" | "disable"
    link: str                 # "Link Up" | "Link Down" | "Disabled"
    speed: str                # "100M" | "1000M" | "10G" | "Disabled" | ""
    duplex: str | None        # "Full" | "Half" | "" — None: firmware doesn't report it
    flow_control: str | None  # "Enabled" | "Disabled" | "" — None: not reported
    tx_bytes: int | None = None   # None = switch reports no byte counters
    rx_bytes: int | None = None
    # Counters stay None until /port.cgi?page=stats was read successfully.
    # Reporting 0 after a failed fetch would look like a counter reset to
    # Home Assistant and inflate the long-term statistics on the next poll.
    tx_packets: int | None = None
    rx_packets: int | None = None
    tx_errors: int | None = None  # TxBadPkt
    rx_errors: int | None = None  # RxBadPkt
    name: str = ""                # port name set on the switch (RTLPlayground)
    sfp_module: str = ""          # vendor and model of a plugged-in SFP module


@dataclass
class SwitchData:
    """Full snapshot of one managed switch."""
    ip: str
    model: str
    mac: str
    uptime: str
    firmware: str
    ports: list[PortData] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    available: bool = True
    temperature: float | None = None  # chip temperature in °C, if reported
    hostname: str = ""
    uptime_seconds: int | None = None  # seconds since boot, if reported as a number
    boot_time: datetime | None = None  # derived from uptime_seconds


class CgiScraper:
    """Async scraper that speaks directly to the switch CGI interface."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        ip: str,
        username: str,
        password: str,
        http_port: int = 80,
    ) -> None:
        self._session = session
        self.ip = ip
        self._username = username
        self._password = password
        self._base_url = (
            f"http://{ip}:{http_port}" if http_port != 80 else f"http://{ip}"
        )
        self._cookies: dict[str, str] = {}
        self._logged_in = False

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        """POST /login.cgi with MD5(user+pass) — mirrors the original scraper."""
        md5hash = hashlib.md5(
            (self._username + self._password).encode()
        ).hexdigest()

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            # A FormData object can only be sent once, so build it per attempt
            form = aiohttp.FormData()
            form.add_field("username", self._username)
            form.add_field("password", self._password)
            form.add_field("Response", md5hash)
            form.add_field("language", "EN")
            try:
                async with self._session.post(
                    f"{self._base_url}{CGI_LOGIN}",
                    data=form,
                    headers={"Referer": f"{self._base_url}/login.html"},
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=True,
                ) as resp:
                    resp.raise_for_status()
                    self._cookies["admin"] = md5hash
                    self._logged_in = True
                    _LOGGER.debug("[%s] Login OK", self.ip)
                    return
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
                if attempt < _MAX_ATTEMPTS:
                    _LOGGER.debug("[%s] Login attempt %d failed (%s), retrying", self.ip, attempt, exc)
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                self._logged_in = False
                raise RuntimeError(f"Login failed for {self.ip}: {exc}") from exc
            except Exception as exc:
                self._logged_in = False
                raise RuntimeError(f"Login failed for {self.ip}: {exc}") from exc

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch(self, path: str, _relogin: bool = True) -> str | None:
        if not self._logged_in:
            await self._login()
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            await asyncio.sleep(_REQUEST_DELAY)
            try:
                async with self._session.get(
                    f"{self._base_url}{path}",
                    # Required: newer firmware (e.g. V100.9.9.x on HW V3.x) returns an
                    # empty page without a Referer; older firmware (V1.9) ignores it.
                    headers={"Referer": f"{self._base_url}/"},
                    cookies=self._cookies,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=True,
                ) as resp:
                    if resp.status in (401, 403) and _relogin:
                        _LOGGER.warning("[%s] Session expired, re-logging in", self.ip)
                        self._logged_in = False
                        await self._login()
                        return await self._fetch(path, _relogin=False)
                    resp.raise_for_status()
                    return await resp.text(encoding="utf-8", errors="replace")
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
                if attempt < _MAX_ATTEMPTS:
                    _LOGGER.debug("[%s] Fetch %s attempt %d failed (%s), retrying", self.ip, path, attempt, exc)
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                _LOGGER.error("[%s] Fetch %s failed after %d attempts: %s", self.ip, path, attempt, exc)
            except Exception as exc:
                _LOGGER.error("[%s] Fetch %s failed: %s", self.ip, path, exc)
                return None
        return None

    async def _post(self, path: str, data: dict[str, str]) -> str | None:
        if not self._logged_in:
            await self._login()
        await asyncio.sleep(_REQUEST_DELAY)
        try:
            async with self._session.post(
                f"{self._base_url}{path}",
                data=data,
                headers={
                    "Referer": f"{self._base_url}{path}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                cookies=self._cookies,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                resp.raise_for_status()
                return await resp.text(encoding="utf-8", errors="replace")
        except Exception as exc:
            _LOGGER.error("[%s] POST %s failed: %s", self.ip, path, exc)
            return None

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_counter(val: str) -> int:
        """Parse hex (0x…), split-64 (hi-lo), or decimal counter values."""
        val = val.strip()
        if val.lower().startswith("0x"):
            try:
                return int(val, 16)
            except ValueError:
                return 0
        parts = val.split("-")
        if len(parts) == 2:
            try:
                return int(parts[0]) * 4_294_967_296 + int(parts[1])
            except ValueError:
                return 0
        try:
            return int(val)
        except ValueError:
            return 0

    @staticmethod
    def _fmt_uptime(raw: str) -> str:
        m = re.match(
            r"(?:(\d+)Day)?(?:(\d+)Hour)?(?:(\d+)Minute)?(?:(\d+)Second)?", raw
        )
        if m:
            labels = ["d", "h", "m", "s"]
            parts = [f"{v}{s}" for v, s in zip(m.groups(), labels) if v]
            return " ".join(parts) if parts else raw
        return raw

    @staticmethod
    def _parse_speed_duplex(raw: str) -> tuple[str, str]:
        """Split "1000Full" / "2500Full" / "10GFull" / "100M/Half" into ("1000M", "Full")."""
        m = re.match(r"(\d+)\s*([MG])?\s*/?\s*(Full|Half)", raw, re.IGNORECASE)
        if not m:
            return "", ""
        mbit = int(m.group(1)) * (1000 if (m.group(2) or "").upper() == "G" else 1)
        speed = f"{mbit // 1000}G" if mbit >= 10000 and mbit % 1000 == 0 else f"{mbit}M"
        return speed, m.group(3).capitalize()

    @staticmethod
    def _find_port_status_table(soup: BeautifulSoup) -> Any:
        """Return the read-only per-port table of /port.cgi (not the <select> forms)."""
        port_list_h3 = soup.find(
            lambda tag: tag.name == "h3" and "Port List" in tag.text
        )
        if port_list_h3:
            return port_list_h3.find_next("table")
        for t in soup.find_all("table"):
            hdrs = [th.get_text(strip=True).lower() for th in t.find_all("th")]
            if "port" in hdrs and "state" in hdrs:
                first_row = t.find("tr")
                nxt = first_row.find_next_sibling("tr") if first_row else None
                if nxt and not nxt.find("select"):
                    return t
        return None

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> SwitchData:
        """Full telemetry scrape — mirrors _scrape_builtin() in the original."""
        try:
            await self._login()
        except Exception as exc:
            _LOGGER.error("[%s] Login error: %s", self.ip, exc)
            return SwitchData(ip=self.ip, model="Unknown", mac="", uptime="", firmware="", available=False)

        info_html      = await self._fetch(CGI_INFO)
        stats_html     = await self._fetch(CGI_PORT_STATS)
        port_cfg_html  = await self._fetch(CGI_PORT_CFG)

        return self.parse(info_html, port_cfg_html, stats_html)

    def parse(
        self,
        info_html: str | None,
        port_cfg_html: str | None,
        stats_html: str | None,
    ) -> SwitchData:
        """Turn the raw CGI pages into a SwitchData snapshot.

        Two page layouts are supported:
          • HORACO: port link/speed table on /info.cgi (second table)
          • keepLink KP-9000 & co.: /info.cgi has device info only; link/speed
            come from the "Actual" columns of the status table on /port.cgi
        """
        device_info: dict[str, str] = {}
        port_admin_states: dict[str, str] = {}  # port_num → "enable"/"disable"
        port_status_rows: list[list[str]] = []   # /port.cgi status rows (KP-9000 layout)
        ports: list[PortData] = []

        # ── 1. Admin state per port from /port.cgi ─────────────────────
        if port_cfg_html:
            try:
                soup = BeautifulSoup(port_cfg_html, "html.parser")
                port_table = self._find_port_status_table(soup)
                if port_table:
                    for row in port_table.find_all("tr"):
                        cells = [c.get_text(strip=True) for c in row.find_all("td")]
                        if len(cells) >= 2:
                            m = re.search(r"\d+", cells[0])
                            if m:
                                port_admin_states[m.group(0)] = cells[1].lower()
                                # Port | State | Speed Config | Speed Actual | Flow Config | Flow Actual
                                if len(cells) >= 6:
                                    port_status_rows.append([m.group(0), *cells[1:]])
            except Exception as exc:
                _LOGGER.warning("[%s] Could not parse port admin states: %s", self.ip, exc)

        # ── 2. Device info + port link/speed from /info.cgi ────────────
        if info_html:
            soup = BeautifulSoup(info_html, "html.parser")
            tables = soup.find_all("table")

            if tables:
                for row in tables[0].find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    for i in range(0, len(cells) - 1, 2):
                        label = cells[i].get_text(strip=True).rstrip(":")
                        value = cells[i + 1].get_text(strip=True)
                        if "Sys Uptime"        in label: device_info["uptime"]   = self._fmt_uptime(value)
                        elif "MAC Address"     in label: device_info["mac"]      = value
                        elif "Firmware Version" in label: device_info["firmware"] = value
                        elif "Device Model"    in label or "Device Name" in label:
                            device_info["model"] = value

            if len(tables) >= 2:
                for row in tables[1].find_all("tr")[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 4:
                        continue
                    pname    = cells[0].get_text(strip=True)
                    m        = re.match(r"Port\s*(\d+)", pname)
                    port_num = m.group(1) if m else pname
                    admin    = port_admin_states.get(port_num, "enable")

                    if admin in ("disable", "disabled"):
                        ports.append(PortData(
                            port=port_num, status=PORT_STATUS_DISABLED,
                            link="Disabled", speed="Disabled",
                            duplex="", flow_control="",
                        ))
                    else:
                        link_txt = cells[1].get_text(strip=True)
                        ports.append(PortData(
                            port=port_num,
                            status=PORT_STATUS_UP if "Up" in link_txt else PORT_STATUS_DOWN,
                            link=link_txt,
                            speed=cells[3].get_text(strip=True),
                            duplex=cells[2].get_text(strip=True),
                            flow_control=cells[4].get_text(strip=True) if len(cells) > 4 else "",
                        ))

        # ── 2b. No port table on /info.cgi → use /port.cgi status rows ──
        if not ports:
            for port_num, state, _cfg, actual, _flow_cfg, flow_actual, *_ in port_status_rows:
                if state.lower() in ("disable", "disabled"):
                    ports.append(PortData(
                        port=port_num, status=PORT_STATUS_DISABLED,
                        link="Disabled", speed="Disabled",
                        duplex="", flow_control="",
                    ))
                    continue
                speed, duplex = self._parse_speed_duplex(actual)
                up = bool(speed)
                ports.append(PortData(
                    port=port_num,
                    status=PORT_STATUS_UP if up else PORT_STATUS_DOWN,
                    link="Link Up" if up else "Link Down",
                    speed=speed,
                    duplex=duplex,
                    flow_control={"on": "Enabled", "off": "Disabled"}.get(
                        flow_actual.lower(), flow_actual
                    ),
                ))

        # ── 3. TX/RX counters from /port.cgi?page=stats ────────────────
        if stats_html and ports:
            soup = BeautifulSoup(stats_html, "html.parser")
            stats_table = soup.find("table")
            if stats_table:
                rows = stats_table.find_all("tr")
                if rows:
                    hdrs = [c.get_text(strip=True).lower() for c in rows[0].find_all(["td", "th"])]
                    tx_pkt_i = rx_pkt_i = tx_b_i = rx_b_i = tx_err_i = rx_err_i = -1
                    for idx, h in enumerate(hdrs):
                        is_bytes = any(t in h for t in ["byte", "octet"])
                        if any(t in h for t in ["txbadpkt", "txerr", "tx err"]):
                            tx_err_i = idx
                        elif any(t in h for t in ["rxbadpkt", "rxerr", "rx err"]):
                            rx_err_i = idx
                        elif not is_bytes and any(t in h for t in ["txgoodpkt", "txpackets", "tx packet", "txok"]):
                            tx_pkt_i = idx
                        elif not is_bytes and any(t in h for t in ["rxgoodpkt", "rxpackets", "rx packet", "rxok"]):
                            rx_pkt_i = idx
                        elif any(t in h for t in ["txbytes", "tx byte", "txgoodbytes", "tx_bytes"]):
                            tx_b_i = idx
                        elif any(t in h for t in ["rxbytes", "rx byte", "rxgoodbytes", "rx_bytes"]):
                            rx_b_i = idx
                    if tx_pkt_i == -1: tx_pkt_i = 3
                    if rx_pkt_i == -1: rx_pkt_i = 5 if "rxgoodpkt" in hdrs else 4

                    for row in rows[1:]:
                        cells = row.find_all("td")
                        if not cells:
                            continue
                        pname    = cells[0].get_text(strip=True)
                        m        = re.match(r"Port\s*(\d+)", pname)
                        port_num = m.group(1) if m else pname.replace("Port ", "")
                        for p in ports:
                            if p.port == port_num and len(cells) > max(tx_pkt_i, rx_pkt_i):
                                p.tx_packets = self._parse_counter(cells[tx_pkt_i].get_text(strip=True))
                                p.rx_packets = self._parse_counter(cells[rx_pkt_i].get_text(strip=True))
                                if tx_b_i != -1 and len(cells) > tx_b_i:
                                    p.tx_bytes = self._parse_counter(cells[tx_b_i].get_text(strip=True))
                                if rx_b_i != -1 and len(cells) > rx_b_i:
                                    p.rx_bytes = self._parse_counter(cells[rx_b_i].get_text(strip=True))
                                if tx_err_i != -1 and len(cells) > tx_err_i:
                                    p.tx_errors = self._parse_counter(cells[tx_err_i].get_text(strip=True))
                                if rx_err_i != -1 and len(cells) > rx_err_i:
                                    p.rx_errors = self._parse_counter(cells[rx_err_i].get_text(strip=True))
                                break

        return SwitchData(
            ip=self.ip,
            model=device_info.get("model", "Unknown"),
            mac=device_info.get("mac", ""),
            uptime=device_info.get("uptime", ""),
            firmware=device_info.get("firmware", ""),
            ports=ports,
            available=True,
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def reboot(self) -> bool:
        """POST /reboot.cgi {"cmd":"reboot"} — same endpoint as switch-dashboard."""
        try:
            await self._post(CGI_REBOOT, {"cmd": "reboot"})
            _LOGGER.warning("[%s] Reboot command sent", self.ip)
            return True
        except Exception as exc:
            _LOGGER.error("[%s] Reboot failed: %s", self.ip, exc)
            return False
