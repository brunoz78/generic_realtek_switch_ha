"""RTLPlayground firmware releases on GitHub.

A release carries one 512 KiB image per board, named like
rtlplayground-v0.1.0-e67c928-p5-KP_9000_9XHML_X_V3_1.bin. Which one fits a
switch is told by the board name the firmware reports as hw_ver: every image
contains its board name as a NUL-terminated string, the same check the web
interface makes before an upload.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import aiohttp

_LOGGER = logging.getLogger(__name__)

IMAGE_SIZE = 524288
_API = "https://api.github.com/repos/{repo}/releases/latest"
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "generic_realtek_switch"}
# rtlplayground-<version>-<BOARD>.bin, the version being v0.1.0-<commit>[-pN]
_ASSET = re.compile(r"^rtlplayground-(v\d+\.\d+\.\d+-[0-9a-z.\-]+?)-([A-Z][A-Z0-9_]*)\.bin$")


@dataclass
class FirmwareAsset:
    name: str
    board: str
    url: str


@dataclass
class FirmwareRelease:
    tag: str
    version: str
    url: str
    notes: str
    assets: list[FirmwareAsset] = field(default_factory=list)


def parse_release(data: dict) -> FirmwareRelease | None:
    """The images of a release; None if it holds no RTLPlayground image."""
    assets, versions = [], set()
    for a in data.get("assets", []):
        m = _ASSET.match(a.get("name", ""))
        if not m:
            continue  # checksums, OEM installers and the like
        versions.add(m.group(1))
        # Through the API rather than the download link: github.com answers that
        # with a Content-Security-Policy header longer than aiohttp reads (8190 bytes)
        url = a.get("url") or a["browser_download_url"]
        assets.append(FirmwareAsset(a["name"], m.group(2), url))
    if len(versions) != 1:
        return None
    return FirmwareRelease(
        tag=data.get("tag_name", ""),
        version=versions.pop(),
        url=data.get("html_url", ""),
        notes=data.get("body") or "",
        assets=assets,
    )


def image_valid(image: bytes) -> bool:
    """Size, start bytes and CRC16 as the web interface checks them."""
    if len(image) != IMAGE_SIZE or image[:3] != b"\x00\x40\x02":
        return False
    crc = 0
    for byte in image:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc == 0xB001


def image_for_board(image: bytes, board_name: str) -> bool:
    """True if the image was built for the board that reports board_name."""
    return bool(board_name) and (board_name.encode("latin-1", "replace") + b"\x00") in image


class ReleaseCache:
    """Latest release per repository, fetched at most once per max_age."""

    def __init__(self, session: aiohttp.ClientSession, max_age: float) -> None:
        self._session = session
        self._max_age = max_age
        self._cache: dict[str, tuple[float, FirmwareRelease | None]] = {}
        # (release tag, board name) → name of the fitting image, None if none fits
        self._fits: dict[tuple[str, str], str | None] = {}
        self._fit_lock = asyncio.Lock()

    async def latest(self, repo: str, force: bool = False) -> FirmwareRelease | None:
        cached = self._cache.get(repo)
        if cached and not force and time.monotonic() - cached[0] < self._max_age:
            return cached[1]
        try:
            async with self._session.get(
                _API.format(repo=repo), headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                release = parse_release(await resp.json())
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            _LOGGER.warning("Firmware release of %s not readable: %s", repo, exc)
            return cached[1] if cached else None
        self._cache[repo] = (time.monotonic(), release)
        return release

    async def _download(self, asset: FirmwareAsset) -> bytes | None:
        try:
            async with self._session.get(
                asset.url,
                headers={"Accept": "application/octet-stream", "User-Agent": _HEADERS["User-Agent"]},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
                return await resp.read()
        except (aiohttp.ClientError, TimeoutError) as exc:
            _LOGGER.warning("Download of %s failed: %s", asset.name, exc)
            return None

    async def image_for(self, release: FirmwareRelease, board_name: str) -> bytes | None:
        """Download the images of a release until one fits the board."""
        known = self._fits.get((release.tag, board_name), ...)
        if known is None:
            return None  # checked before: no image of this release fits
        # The board target usually resembles the reported name: try those first
        key = re.sub(r"[^A-Z0-9]", "", board_name.upper())
        ordered = sorted(
            release.assets,
            key=lambda a: (a.name != known, a.board.replace("_", "") not in key),
        )
        complete = True
        loop = asyncio.get_running_loop()
        for asset in ordered:
            image = await self._download(asset)
            if image is None:
                complete = False
                continue
            # The CRC runs over 512 KiB in pure Python: not on the event loop
            valid = await loop.run_in_executor(None, image_valid, image)
            if valid and image_for_board(image, board_name):
                _LOGGER.debug("%s fits %s", asset.name, board_name)
                self._fits[(release.tag, board_name)] = asset.name
                return image
        if complete:
            # Remember only a definite answer, not one cut short by a failed download
            self._fits[(release.tag, board_name)] = None
        return None

    async def has_image_for(self, release: FirmwareRelease, board_name: str) -> bool:
        """Whether the release holds an image for the board; checked once per release."""
        async with self._fit_lock:
            if (release.tag, board_name) not in self._fits:
                await self.image_for(release, board_name)
            return self._fits.get((release.tag, board_name)) is not None
