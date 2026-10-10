"""
Client for switches running the RTLPlayground firmware
(https://github.com/logicog/RTLPlayground).

Auth flow:
  1. POST /login  pwd=<password>  →  302 with "Set-Cookie: session=<id>"
  2. GET /information.json  → hostname, MAC, firmware, model, chip temperature
  3. GET /status.json       → per port: enabled, link speed, packet/error counters
  4. GET /reset             → reboot (the switch closes the connection)

Older firmware keeps a single session: logging in from Home Assistant logs
out an open browser tab and vice versa. When the session is taken over while
it was still fresh, polling pauses for a while instead of logging straight
back in, so the web interface stays usable. Firmware with several sessions is
recognised at login (a second login leaves the first session valid); there a
lost session can only mean a restart of the switch, so the client logs in
again right away.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import (
    PORT_STATUS_DISABLED,
    PORT_STATUS_DOWN,
    PORT_STATUS_UP,
    RTL_INFO,
    RTL_LOGIN,
    RTL_LOGIN_PAGE,
    RTL_RESET,
    RTL_STATUS,
    RTL_UPLOAD,
)
from .scraper import PortData, SwitchData

_LOGGER = logging.getLogger(__name__)

# The firmware shares one output buffer between connections: one request at a time
_REQUEST_DELAY = 0.4
_MAX_ATTEMPTS = 3
_RETRY_DELAY = 1.0

# Session timeout of the firmware if /information.json was not read yet
_DEFAULT_SESSION_TIMEOUT = 200
# How long to leave the switch to the web interface after it took the session
_TAKEOVER_PAUSE = 300
# After a firmware upload: time the switch takes to verify the image and reset
_UPDATE_SETTLE = 15
# A boot time that moves by less than this is still the same boot
_BOOT_JITTER = 120

# "link" of /status.json → speed; index into LINKS in the firmware's app.js
_LINK_SPEED = {1: "10M", 2: "100M", 3: "1000M", 4: "500M", 5: "10G", 6: "2500M", 7: "5000M"}


class SessionLost(Exception):
    """The switch answered 401: our session expired or was taken over."""


async def detect_rtlplayground(
    session: aiohttp.ClientSession, ip: str, http_port: int = 80
) -> bool | None:
    """True if the switch runs RTLPlayground, False if not, None if unreachable.

    The login page is served without authentication on both firmwares.
    """
    base = f"http://{ip}:{http_port}" if http_port != 80 else f"http://{ip}"
    try:
        async with session.get(
            f"{base}{RTL_LOGIN_PAGE}",
            timeout=aiohttp.ClientTimeout(total=10),
            allow_redirects=False,
        ) as resp:
            text = await resp.text(encoding="utf-8", errors="replace")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None
    return "RTLPlayground" in text


class RtlPlaygroundClient:
    """Async client for the JSON interface of RTLPlayground."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        ip: str,
        password: str,
        http_port: int = 80,
    ) -> None:
        self._session = session
        self.ip = ip
        self._password = password
        self._port = http_port
        self._base_url = (
            f"http://{ip}:{http_port}" if http_port != 80 else f"http://{ip}"
        )
        self._session_id: str | None = None
        # The switch serves one connection at a time: polls wait for an upload
        self._lock = asyncio.Lock()
        self._last_ok = 0.0          # monotonic time of the last authenticated reply
        self._session_timeout = _DEFAULT_SESSION_TIMEOUT
        self._paused_until = 0.0
        self._boot_time: datetime | None = None
        self._multi_session: bool | None = None  # known after the first login

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with self._session.post(
                    f"{self._base_url}{RTL_LOGIN}",
                    data={"pwd": self._password},
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=False,
                ) as resp:
                    cookie = resp.cookies.get("session")
                    if not cookie or not cookie.value:
                        raise RuntimeError("password rejected")
                    self._session_id = cookie.value
                    self._last_ok = time.monotonic()
                    _LOGGER.debug("[%s] Login OK", self.ip)
                    return
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                raise RuntimeError(f"Login failed for {self.ip}: {exc}") from exc

    async def _login_and_probe(self) -> None:
        """Log in twice and check whether the first session survived the second.

        On single-session firmware the second login only replaces our own
        first one, so this costs nothing over a single login.
        """
        await self._login()
        first = self._session_id
        await self._login()
        second = self._session_id
        self._session_id = first
        try:
            await self._get_json(RTL_INFO)
            multi = True
        except SessionLost:
            multi = False
        self._session_id = second
        if multi != self._multi_session:
            _LOGGER.debug("[%s] Firmware keeps %s", self.ip, "several sessions" if multi else "one session")
        self._multi_session = multi

    async def _get_json(self, path: str) -> Any:
        """GET a JSON endpoint; raises SessionLost on 401."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            await asyncio.sleep(_REQUEST_DELAY)
            try:
                async with self._session.get(
                    f"{self._base_url}{path}",
                    headers={"Cookie": f"session={self._session_id}"},
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=False,
                ) as resp:
                    if resp.status == 401:
                        raise SessionLost
                    resp.raise_for_status()
                    text = await resp.text(encoding="utf-8", errors="replace")
                data = json.loads(text)
                self._last_ok = time.monotonic()
                return data
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError, ValueError) as exc:
                # ValueError: a reply garbled by a parallel browser request
                if attempt < _MAX_ATTEMPTS:
                    _LOGGER.debug("[%s] %s attempt %d failed (%s), retrying", self.ip, path, attempt, exc)
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                raise

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> SwitchData:
        async with self._lock:
            return await self._scrape()

    async def _scrape(self) -> SwitchData:
        unavailable = SwitchData(ip=self.ip, model="Unknown", mac="", uptime="", firmware="", available=False)
        if time.monotonic() < self._paused_until:
            _LOGGER.debug("[%s] Web interface has the session, polling paused", self.ip)
            return unavailable
        try:
            if not self._session_id:
                await self._login_and_probe()
            try:
                info = await self._get_json(RTL_INFO)
                status = await self._get_json(RTL_STATUS)
            except SessionLost:
                idle = time.monotonic() - self._last_ok
                if self._multi_session:
                    # Browsers get sessions of their own: the switch restarted
                    _LOGGER.info("[%s] Session lost, the switch probably restarted; logging in again", self.ip)
                elif idle < self._session_timeout:
                    # Our session was still valid: someone logged in through the web UI
                    _LOGGER.info(
                        "[%s] Session taken over by the web interface, pausing for %d s",
                        self.ip, _TAKEOVER_PAUSE,
                    )
                    self._session_id = None
                    self._paused_until = time.monotonic() + _TAKEOVER_PAUSE
                    return unavailable
                await self._login_and_probe()
                info = await self._get_json(RTL_INFO)
                status = await self._get_json(RTL_STATUS)
        except Exception as exc:
            _LOGGER.error("[%s] RTLPlayground poll failed: %s", self.ip, exc)
            self._session_id = None
            return unavailable

        timeout = info.get("session_timeout") if isinstance(info, dict) else None
        if isinstance(timeout, int) and timeout > 0:
            self._session_timeout = timeout
        data = self.parse(info, status)
        if data.uptime_seconds is not None:
            boot = datetime.now(timezone.utc) - timedelta(seconds=data.uptime_seconds)
            # The same boot, give or take the polling delay: keep the time stable
            if self._boot_time and abs((boot - self._boot_time).total_seconds()) < _BOOT_JITTER:
                boot = self._boot_time
            self._boot_time = boot
            data.boot_time = boot
        return data

    def parse(self, info: dict[str, Any] | None, status: list[dict[str, Any]] | None) -> SwitchData:
        """Turn /information.json and /status.json into a SwitchData snapshot."""
        info = info or {}
        ports: list[PortData] = []
        for p in sorted(status or [], key=lambda x: x.get("portNum", 0)):
            port_num = str(p.get("portNum", ""))
            is_sfp = bool(p.get("isSFP"))
            enabled = bool(p.get("enabled"))
            link = int(p.get("link") or 0)
            if not is_sfp and not enabled:
                status_, link_txt, speed = PORT_STATUS_DISABLED, "Disabled", "Disabled"
            elif link:
                status_, link_txt, speed = PORT_STATUS_UP, "Link Up", _LINK_SPEED.get(link, "")
            else:
                # For SFP ports "enabled" only says whether a module is plugged in
                status_, link_txt, speed = PORT_STATUS_DOWN, "Link Down", ""
            ports.append(PortData(
                port=port_num,
                status=status_,
                link=link_txt,
                speed=speed,
                duplex=None,           # not reported by RTLPlayground
                flow_control=None,
                tx_packets=_hex(p.get("txG")),
                rx_packets=_hex(p.get("rxG")),
                tx_errors=_hex(p.get("txB")),
                rx_errors=_hex(p.get("rxB")),
                name=p.get("name") or "",
                sfp_module=" ".join(
                    s for s in (p.get("sfp_vendor", "").strip(), p.get("sfp_model", "").strip()) if s
                ) if is_sfp and enabled else "",
            ))

        firmware = info.get("sw_ver", "")
        return SwitchData(
            ip=self.ip,
            model=info.get("hw_ver") or "RTLPlayground",
            mac=info.get("mac_address", ""),
            uptime="",
            firmware=f"RTLPlayground {firmware}" if firmware else "",
            ports=ports,
            available=True,
            temperature=_temperature(info.get("chip_temp")),
            hostname=info.get("hostname", ""),
            uptime_seconds=_hex(info.get("uptime")),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def reboot(self) -> bool:
        """GET /reset — the switch resets right away and never answers."""
        try:
            if not self._session_id:
                await self._login()
            async with self._session.get(
                f"{self._base_url}{RTL_RESET}",
                headers={"Cookie": f"session={self._session_id}"},
                timeout=aiohttp.ClientTimeout(total=5),
                allow_redirects=False,
            ) as resp:
                if resp.status == 401:
                    _LOGGER.error("[%s] Reboot refused: not logged in", self.ip)
                    return False
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            pass  # expected: the connection drops when the switch resets
        except Exception as exc:
            _LOGGER.error("[%s] Reboot failed: %s", self.ip, exc)
            return False
        self._session_id = None
        _LOGGER.warning("[%s] Reboot command sent", self.ip)
        return True

    async def upload_firmware(self, image: bytes) -> None:
        """POST the image to /upload like the web interface; the switch then resets.

        Raises RuntimeError if the switch refuses the image. A connection that
        drops after the image went out is taken as the reset, not an error.
        """
        async with self._lock:
            if not self._session_id:
                await self._login_and_probe()
            try:
                await self._get_json(RTL_INFO)  # make sure the session is still ours
            except SessionLost:
                await self._login_and_probe()
            form = aiohttp.FormData()
            form.add_field(
                "uploadedfile", image, filename="rtlplayground.bin",
                content_type="application/octet-stream",
            )
            _LOGGER.warning("[%s] Uploading firmware (%d bytes)", self.ip, len(image))
            try:
                async with self._session.post(
                    f"{self._base_url}{RTL_UPLOAD}",
                    data=form,
                    headers={"Cookie": f"session={self._session_id}"},
                    timeout=aiohttp.ClientTimeout(total=300),
                    allow_redirects=False,
                ) as resp:
                    if resp.status != 200:
                        why = (await resp.text(errors="replace")).strip().splitlines()
                        raise RuntimeError(
                            f"switch refused the image (HTTP {resp.status}"
                            + (f": {why[0]}" if why else "") + ")"
                        )
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
                _LOGGER.debug("[%s] Connection closed after the upload: %s", self.ip, exc)
            self._session_id = None

    async def wait_until_back(self, timeout: float = 240) -> bool:
        """After an update: wait for the reset, then for the web server to answer."""
        await asyncio.sleep(_UPDATE_SETTLE)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await detect_rtlplayground(self._session, self.ip, self._port):
                return True
            await asyncio.sleep(3)
        return False


def _hex(val: Any) -> int | None:
    """Counters come as "0x…" strings."""
    if not isinstance(val, str):
        return None
    try:
        return int(val, 16)
    except ValueError:
        return None


def _temperature(raw: Any) -> float | None:
    """"45.3 C" → 45.3"""
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", raw) if isinstance(raw, str) else None
    return float(m.group(1)) if m else None
