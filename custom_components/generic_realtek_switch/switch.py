"""Switch platform — turn single ports on and off (RTLPlayground only).

One switch per RJ45 port, under the parent switch device. Like the web
interface they change the running configuration only: after a restart the
port is as saved in flash. Disabled by default, because turning off the port
Home Assistant reaches the switch through locks it out until a restart.
SFP cages get none: their "enabled" only says whether a module is plugged in.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SwitchCoordinator
from .const import DOMAIN, PORT_STATUS_DISABLED, object_id
from .rtlplayground import RtlPlaygroundClient
from .scraper import PortData
from .sensor import switch_device_info   # reuse the helper

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SwitchCoordinator = hass.data[DOMAIN][entry.entry_id]
    if not isinstance(coordinator.scraper, RtlPlaygroundClient) or not coordinator.data:
        return
    async_add_entities(
        PortEnabledSwitch(coordinator, p.port) for p in coordinator.data.ports if not p.sfp
    )


class PortEnabledSwitch(CoordinatorEntity[SwitchCoordinator], SwitchEntity):
    """On = the port is enabled on the switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "port_enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SwitchCoordinator, port_num: str) -> None:
        super().__init__(coordinator)
        self._port_num = port_num
        self._attr_unique_id = f"{DOMAIN}_{coordinator.scraper.ip}_port{port_num}_enabled"
        self.entity_id = "switch." + object_id(coordinator.scraper.ip, f"port_{port_num}_enabled")
        self._attr_translation_placeholders = {"port": port_num}
        self._attr_device_info = switch_device_info(coordinator)
        # State sent to the switch, shown until the next poll confirms it
        self._pending: bool | None = None

    def _port(self) -> PortData | None:
        if not self.coordinator.data:
            return None
        return next((p for p in self.coordinator.data.ports if p.port == self._port_num), None)

    @property
    def available(self) -> bool:
        return super().available and self._port() is not None

    @property
    def is_on(self) -> bool | None:
        if self._pending is not None:
            return self._pending
        p = self._port()
        return p.status != PORT_STATUS_DISABLED if p else None

    @property
    def icon(self) -> str:
        return "mdi:ethernet" if self.is_on is not False else "mdi:ethernet-off"

    @callback
    def _handle_coordinator_update(self) -> None:
        self._pending = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.scraper.set_port_enabled(self._port_num, enabled)
        except Exception as exc:
            raise HomeAssistantError(
                f"Port {self._port_num} of {self.coordinator.scraper.ip}: {exc}"
            ) from exc
        self._pending = enabled
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
