"""Firmware update for switches running RTLPlayground.

The latest release of a GitHub repository (option "firmware_repo") is the
offered version. Installing downloads the image built for the switch's board,
uploads it like the web interface does and waits for the switch to come back.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SwitchCoordinator
from .const import (
    CONF_FIRMWARE,
    CONF_FIRMWARE_REPO,
    DEFAULT_FIRMWARE_REPO,
    DOMAIN,
    FIRMWARE_RTLPLAYGROUND,
    RELEASE_CHECK_INTERVAL,
    object_id,
)
from .firmware import FirmwareRelease, ReleaseCache
from .sensor import switch_device_info

_LOGGER = logging.getLogger(__name__)

_CACHE_KEY = f"{DOMAIN}_releases"
_PREFIX = "RTLPlayground "


def _releases(hass: HomeAssistant) -> ReleaseCache:
    """One cache for all switches: GitHub is asked once per interval and repository."""
    if _CACHE_KEY not in hass.data:
        hass.data[_CACHE_KEY] = ReleaseCache(
            async_get_clientsession(hass), RELEASE_CHECK_INTERVAL - 60
        )
    return hass.data[_CACHE_KEY]


def _error(key: str, **placeholders: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_FIRMWARE) != FIRMWARE_RTLPLAYGROUND:
        return  # the original firmware is not updated from here
    coordinator: SwitchCoordinator = hass.data[DOMAIN][entry.entry_id]
    repo = entry.options.get(CONF_FIRMWARE_REPO) or DEFAULT_FIRMWARE_REPO
    async_add_entities([FirmwareUpdate(coordinator, repo)])


class FirmwareUpdate(CoordinatorEntity[SwitchCoordinator], UpdateEntity):
    """Offers the latest RTLPlayground release of the configured repository."""

    _attr_has_entity_name = True
    _attr_translation_key = "firmware_update"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )
    _attr_title = "RTLPlayground"

    def __init__(self, coordinator: SwitchCoordinator, repo: str) -> None:
        super().__init__(coordinator)
        ip = coordinator.scraper.ip
        self._attr_unique_id = f"{DOMAIN}_{ip}_firmware_update"
        self.entity_id = f"update.{object_id(ip, 'firmware')}"
        self._attr_device_info = switch_device_info(coordinator)
        self._repo = repo
        self._release: FirmwareRelease | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_check()
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_check, timedelta(seconds=RELEASE_CHECK_INTERVAL)
            )
        )

    async def _async_check(self, _now: Any = None) -> None:
        self._release = await _releases(self.hass).latest(self._repo)
        self.async_write_ha_state()

    @property
    def installed_version(self) -> str | None:
        data = self.coordinator.data
        firmware = data.firmware if data else ""
        return firmware.removeprefix(_PREFIX).strip() or None

    @property
    def latest_version(self) -> str | None:
        return self._release.version if self._release else self.installed_version

    @property
    def release_url(self) -> str | None:
        return self._release.url if self._release else None

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        # Versions are commit hashes: the latest release is newer whenever it differs
        return latest_version != installed_version

    async def async_release_notes(self) -> str | None:
        return self._release.notes if self._release else None

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        scraper = self.coordinator.scraper
        release = await _releases(self.hass).latest(self._repo, force=True)
        if release is None:
            raise _error("update_no_release", repo=self._repo)
        board = self.coordinator.data.model if self.coordinator.data else ""
        if not board or board == "Unknown":
            raise _error("update_no_board")

        self._attr_in_progress = True
        self.async_write_ha_state()
        try:
            image = await _releases(self.hass).image_for(release, board)
            if image is None:
                raise _error("update_no_image", release=release.tag, board=board)
            try:
                await scraper.upload_firmware(image)
            except RuntimeError as exc:
                raise _error("update_refused", reason=str(exc)) from exc
            if not await scraper.wait_until_back():
                raise _error("update_not_back")
            await self.coordinator.async_refresh()
            if self.installed_version != release.version:
                raise _error(
                    "update_wrong_version",
                    expected=release.version,
                    found=self.installed_version or "?",
                )
            self._release = release
            _LOGGER.warning("[%s] Firmware updated to %s", scraper.ip, release.version)
        finally:
            self._attr_in_progress = False
            self.async_write_ha_state()
