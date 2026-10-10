"""Tests for picking and checking RTLPlayground release images."""
from generic_realtek_switch.firmware import (
    IMAGE_SIZE,
    image_for_board,
    image_valid,
    parse_release,
)


def _crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def make_image(board: str) -> bytes:
    """A 512 KiB image with the start bytes, the board name and a closing CRC."""
    body = bytearray(IMAGE_SIZE - 2)
    body[:3] = b"\x00\x40\x02"
    name = board.encode() + b"\x00"
    body[0x1000:0x1000 + len(name)] = name
    state = _crc(body)
    for tail in range(0x10000):
        two = tail.to_bytes(2, "little")
        if _crc(two, state) == 0xB001:
            return bytes(body) + two
    raise AssertionError("no CRC trailer found")


RELEASE = {
    "tag_name": "fw-20261009-1621-e67c928",
    "html_url": "https://github.com/brunoz78/RTLPlayground/releases/tag/fw-20261009-1621-e67c928",
    "body": "Notizen",
    "assets": [
        {"name": f"rtlplayground-v0.1.0-e67c928-p5-{b}.bin", "browser_download_url": f"https://x/{b}.bin"}
        for b in ("KP_9000_9XHML_X_V3_1", "KP_9000_9XHML_X_V3_2", "LIANGUO_ZX_SWTGW215AS", "SWTGW218AS")
    ] + [{"name": "SHA256SUMS.txt", "browser_download_url": "https://x/sums"}],
}


def test_parse_release():
    r = parse_release(RELEASE)
    assert r.version == "v0.1.0-e67c928-p5"
    assert r.tag == "fw-20261009-1621-e67c928"
    assert [a.board for a in r.assets] == [
        "KP_9000_9XHML_X_V3_1", "KP_9000_9XHML_X_V3_2", "LIANGUO_ZX_SWTGW215AS", "SWTGW218AS",
    ]


def test_parse_release_without_suffix_and_installers():
    data = {"tag_name": "t", "assets": [
        {"name": "rtlplayground-v0.1.0-0e9c997-SWTGW218AS.bin", "browser_download_url": "u"},
        {"name": "rtlplayground-oem-installer-SWTGW218AS.bin", "browser_download_url": "u"},
    ]}
    r = parse_release(data)
    assert r.version == "v0.1.0-0e9c997" and len(r.assets) == 1


def test_parse_release_without_images():
    assert parse_release({"tag_name": "erstinstallation", "assets": []}) is None


def test_image_checks():
    image = make_image("keepLink KP-9000-9XHML-X V3.1")
    assert image_valid(image)
    assert image_for_board(image, "keepLink KP-9000-9XHML-X V3.1")
    # V3.2 must not match a V3.1 image, nor a prefix of the name
    assert not image_for_board(image, "keepLink KP-9000-9XHML-X V3.2")
    assert not image_for_board(image, "keepLink KP-9000-9XHML-X V3")
    assert not image_for_board(image, "")
    broken = bytearray(image)
    broken[0x2000] ^= 1
    assert not image_valid(bytes(broken))
    assert not image_valid(image[:-1])
