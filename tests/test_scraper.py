"""Parser tests against real switch pages (see tests/fixtures/*)."""
import pathlib

import pytest

from generic_realtek_switch.scraper import CgiScraper

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(device: str, page: str) -> str:
    return (FIXTURES / device / f"{page}.html").read_text(encoding="utf-8")


def parse(device: str, *, stats: bool = True):
    scraper = CgiScraper(None, "192.0.2.10", "admin", "admin")
    return scraper.parse(
        load(device, "info"),
        load(device, "port"),
        load(device, "stats") if stats else None,
    )


# ── keepLink KP-9000-9XHML-X, FW V100.9.9.1.7 ──────────────────────────────

def test_kp9000_device_info():
    d = parse("kp9000_9xhml_x")
    assert d.model == "KP-9000-9XHML-X"
    assert d.mac == "00:00:5E:00:53:01"
    assert d.firmware == "V100.9.9.1.7"
    assert d.uptime == ""  # this firmware does not report uptime


def test_kp9000_ports():
    d = parse("kp9000_9xhml_x")
    assert [p.port for p in d.ports] == [str(n) for n in range(1, 10)]
    got = {p.port: (p.status, p.speed, p.duplex, p.flow_control) for p in d.ports}
    assert got["1"] == ("up", "1000M", "Full", "Disabled")
    assert got["2"] == ("up", "2500M", "Full", "Disabled")
    assert got["3"] == ("down", "", "", "Disabled")
    assert got["7"] == ("up", "100M", "Full", "Disabled")
    assert got["9"] == ("down", "", "", "Disabled")


def test_kp9000_counters():
    d = parse("kp9000_9xhml_x")
    p1 = d.ports[0]
    # "0-3792066" = high/low 32-bit words
    assert (p1.tx_packets, p1.rx_packets) == (3792066, 4292483)
    assert (p1.tx_errors, p1.rx_errors) == (0, 0)
    # no byte columns on this firmware → no invented values
    assert p1.tx_bytes is None and p1.rx_bytes is None


# ── HORACO ZX-SWTGW215AS, FW V1.9 ──────────────────────────────────────────

def test_zx215_device_info():
    d = parse("zx_swtgw215as")
    assert d.model == "ZX-SWTGW215AS"
    assert d.firmware == "V1.9"
    assert d.uptime == ""


def test_zx215_ports():
    d = parse("zx_swtgw215as")
    assert len(d.ports) == 6
    assert [p.status for p in d.ports] == ["up", "down", "down", "down", "up", "down"]
    assert d.ports[0].speed == "2500M"
    assert d.ports[4].speed == "2500M"


def test_zx215_counters_plain_decimal():
    d = parse("zx_swtgw215as")
    assert (d.ports[0].tx_packets, d.ports[0].rx_packets) == (3357168, 9440681)
    # a port that is down now can still carry counts from earlier
    assert (d.ports[1].tx_packets, d.ports[1].rx_packets) == (559875, 344424)
    assert d.ports[0].tx_errors == 0


# ── behaviour shared by all devices ────────────────────────────────────────

@pytest.mark.parametrize("device", ["kp9000_9xhml_x", "zx_swtgw215as"])
def test_missing_stats_page_leaves_counters_unknown(device):
    """A failed stats fetch must not report 0 (HA would treat it as a reset)."""
    d = parse(device, stats=False)
    assert d.ports, "link state comes from /port.cgi and must survive"
    for p in d.ports:
        assert p.tx_packets is None and p.rx_packets is None
        assert p.tx_errors is None and p.rx_errors is None


def test_no_pages_no_ports():
    scraper = CgiScraper(None, "192.0.2.10", "admin", "admin")
    assert scraper.parse(None, None, None).ports == []


@pytest.mark.parametrize("raw, expected", [
    ("1000Full", ("1000M", "Full")),
    ("2500Full", ("2500M", "Full")),
    ("100Full", ("100M", "Full")),
    ("10GFull", ("10G", "Full")),
    ("10000Full", ("10G", "Full")),
    ("100M/Half", ("100M", "Half")),
    ("Link Down", ("", "")),
])
def test_parse_speed_duplex(raw, expected):
    assert CgiScraper._parse_speed_duplex(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("0-3792066", 3792066),
    ("1-0", 4_294_967_296),
    ("3357168", 3357168),
    ("0x10", 16),
    ("garbage", 0),
])
def test_parse_counter(raw, expected):
    assert CgiScraper._parse_counter(raw) == expected
