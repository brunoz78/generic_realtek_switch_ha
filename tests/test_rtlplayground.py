"""Tests for the RTLPlayground client.

Parser tests use JSON in the format of the firmware's httpd/page_impl.c;
the session tests run the client against a small fake switch.
"""
import asyncio
import json
import pathlib

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from generic_realtek_switch import rtlplayground
from generic_realtek_switch.rtlplayground import RtlPlaygroundClient, detect_rtlplayground

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "rtlplayground_swtgw218as"
INFO = json.loads((FIXTURES / "information.json").read_text(encoding="utf-8"))
STATUS = json.loads((FIXTURES / "status.json").read_text(encoding="utf-8"))


def parse():
    return RtlPlaygroundClient(None, "192.0.2.21", "1234").parse(INFO, STATUS)


# ── Parser ─────────────────────────────────────────────────────────────────

def test_device_info():
    d = parse()
    assert d.model == "SWTGW218AS 8+1 Managed Switch"
    assert d.mac == "00:00:5e:00:53:21"
    assert d.firmware == "RTLPlayground v0.1.0-f0aea3d-de.89fcc68"
    assert d.temperature == 46.2
    assert d.hostname == "rtlplayground"
    assert d.uptime == ""


def test_ports_state_and_speed():
    d = parse()
    assert [p.port for p in d.ports] == [str(n) for n in range(1, 10)]
    got = {p.port: (p.status, p.speed) for p in d.ports}
    assert got["1"] == ("up", "2500M")
    assert got["2"] == ("up", "1000M")
    assert got["3"] == ("down", "")
    assert got["4"] == ("disable", "Disabled")
    assert got["5"] == ("up", "10M")
    assert got["6"] == ("up", "100M")
    assert got["7"] == ("up", "5000M")
    # SFP slot without module: "enabled" 0 means empty slot, not disabled
    assert got["9"] == ("down", "")


def test_counters_and_names():
    ports = {p.port: p for p in parse().ports}
    assert ports["1"].tx_packets == 0x1A2B3C
    assert ports["1"].rx_errors == 3
    assert ports["6"].rx_packets == 0x1FFFFFFFF  # 64-bit counter
    assert ports["1"].name == "NAS"
    assert ports["5"].name == "Velux"
    # Not reported by RTLPlayground: no entities for these
    assert all(p.duplex is None and p.flow_control is None for p in ports.values())
    assert all(p.tx_bytes is None and p.rx_bytes is None for p in ports.values())


def test_sfp_module():
    status = [dict(s) for s in STATUS]
    status[8].update(enabled=1, link=5, sfp_vendor="FS      ", sfp_model="SFP-10GSR-85  ")
    sfp = RtlPlaygroundClient(None, "192.0.2.21", "1234").parse(INFO, status).ports[8]
    assert (sfp.status, sfp.speed, sfp.sfp_module) == ("up", "10G", "FS SFP-10GSR-85")


def test_negative_and_missing_temperature():
    assert rtlplayground._temperature("-3.5 C") == -3.5
    assert rtlplayground._temperature(None) is None
    assert rtlplayground._temperature("") is None


# ── Against a fake switch ──────────────────────────────────────────────────

class FakeSwitch:
    """Like the real firmware: one session at a time, or up to `slots` with
    newer firmware, the least recently created one replaced first."""

    def __init__(self, password="1234", slots=1):
        self.password = password
        self.slots = slots
        self.sessions = []
        self.logins = 0
        self.reset = False
        self.uploaded = None
        self.refuse_upload = False

    @property
    def session(self):
        return self.sessions[-1] if self.sessions else None

    @session.setter
    def session(self, value):
        self.sessions = [value]

    def _add(self, sid):
        self.sessions = (self.sessions + [sid])[-self.slots:]

    def restart(self):
        self.sessions = []

    def app(self):
        app = web.Application()
        app.router.add_get("/login.html", self.login_page)
        app.router.add_post("/login", self.login)
        app.router.add_get("/information.json", self.json(INFO))
        app.router.add_get("/status.json", self.json(STATUS))
        app.router.add_get("/reset", self.do_reset)
        app.router.add_post("/upload", self.upload)
        return app

    async def login_page(self, request):
        return web.Response(text="<p id=sub>RTLPlayground management interface</p>", content_type="text/html")

    async def login(self, request):
        form = await request.post()
        if form.get("pwd") != self.password:
            raise web.HTTPFound("login.html")
        self.logins += 1
        self._add(f"s{self.logins:015d}")
        resp = web.HTTPFound("index.html")
        resp.headers["Set-Cookie"] = f"session={self.session}; SameSite=Strict"
        raise resp

    def json(self, payload):
        async def handler(request):
            if request.cookies.get("session") not in self.sessions:
                return web.Response(status=401)
            return web.json_response(payload)
        return handler

    async def do_reset(self, request):
        self.reset = True
        request.transport.close()  # the switch resets without answering
        return web.Response()

    async def upload(self, request):
        if request.cookies.get("session") not in self.sessions:
            return web.Response(status=401)
        if self.refuse_upload:
            return web.Response(status=400, text="Checksum error")
        form = await request.post()
        self.uploaded = form["uploadedfile"].file.read()
        return web.Response(text="OK")

    def browser_login(self):
        self.logins += 1
        self._add("browser")


def run(fake, coro_fn):
    async def main():
        server = TestServer(fake.app(), host="127.0.0.1")
        await server.start_server()
        try:
            async with aiohttp.ClientSession() as session:
                client = RtlPlaygroundClient(session, "127.0.0.1", "1234", http_port=server.port)
                return await coro_fn(session, client, server.port)
        finally:
            await server.close()
    return asyncio.run(main())


def no_delay(monkeypatch):
    monkeypatch.setattr(rtlplayground, "_REQUEST_DELAY", 0)
    monkeypatch.setattr(rtlplayground, "_RETRY_DELAY", 0)


def test_detect_and_scrape(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch()

    async def go(session, client, port):
        assert await detect_rtlplayground(session, "127.0.0.1", port) is True
        return await client.scrape()

    d = run(fake, go)
    assert d.available and len(d.ports) == 9 and fake.logins == 2


def test_wrong_password(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch(password="geheim")
    d = run(fake, lambda s, c, p: c.scrape())
    assert not d.available


def test_session_kept_between_polls(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch()

    async def go(session, client, port):
        await client.scrape()
        return await client.scrape()

    assert run(fake, go).available
    assert fake.logins == 2


def test_takeover_by_browser_pauses_polling(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch()

    async def go(session, client, port):
        await client.scrape()
        fake.browser_login()                 # web UI logs in, our session is gone
        second = await client.scrape()
        third = await client.scrape()        # still paused, browser keeps its session
        return second, third

    second, third = run(fake, go)
    assert not second.available and not third.available
    assert fake.session == "browser"


def test_expired_session_relogs_in(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch()

    async def go(session, client, port):
        await client.scrape()
        fake.session = "expired"
        client._last_ok -= 1000              # longer idle than the session timeout
        return await client.scrape()

    assert run(fake, go).available
    assert fake.logins == 4


def test_reboot(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch()

    async def go(session, client, port):
        await client.scrape()
        return await client.reboot()

    assert run(fake, go) is True
    assert fake.reset


def test_several_sessions_browser_does_not_pause(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch(slots=4)

    async def go(session, client, port):
        await client.scrape()
        fake.browser_login()                 # gets a session of its own
        return await client.scrape()

    assert run(fake, go).available
    assert "browser" in fake.sessions


def test_several_sessions_restart_relogs_in_at_once(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch(slots=4)

    async def go(session, client, port):
        await client.scrape()
        fake.restart()                       # all sessions gone, ours still fresh
        return await client.scrape()

    assert run(fake, go).available
    assert fake.logins == 4


def test_upload_firmware(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch(slots=4)
    image = bytes(range(256)) * 2048

    async def go(session, client, port):
        await client.scrape()
        await client.upload_firmware(image)

    run(fake, go)
    assert fake.uploaded == image


def test_upload_refused(monkeypatch):
    no_delay(monkeypatch)
    fake = FakeSwitch(slots=4)
    fake.refuse_upload = True

    async def go(session, client, port):
        try:
            await client.upload_firmware(b"x" * 10)
        except RuntimeError as exc:
            return str(exc)

    assert "HTTP 400" in run(fake, go)
