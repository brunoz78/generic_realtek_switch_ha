"""Sensor platform for HORACO Managed Switch.

Architecture:
  • One Device per switch (model, firmware, uptime, MAC, ports summary)
  • Per-port entities live on that same device:
      "Port N"   → one enum sensor combining link and speed
                   (disconnected / disabled / 100m / 1000m / 2500m / 10g …)
      "Port N …" → duplex, flow control, packet/error/byte counters, disabled by default
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HoracoCoordinator
from .const import DOMAIN, PORT_ID_SUFFIX, PORT_STATUS_DISABLED, PORT_STATUS_UP, object_id
from .scraper import PortData, SwitchData

_LOGGER = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Device helpers
# ────────────────────────────────────────────────────────────────────────────

def switch_device_info(coordinator: HoracoCoordinator) -> DeviceInfo:
    """DeviceInfo for the physical switch (parent device)."""
    d = coordinator.data
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.scraper.ip)},
        name=f"Switch {coordinator.scraper.ip}",
        manufacturer="HORACO",
        model=d.model if d else "Unknown",
        sw_version=d.firmware if d else None,
        hw_version=None,
        connections={("mac", d.mac)} if d and d.mac else set(),
        configuration_url=f"http://{coordinator.scraper.ip}",
    )



# ────────────────────────────────────────────────────────────────────────────
# Switch-level sensor descriptors
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class SwitchSensorDesc(SensorEntityDescription):
    value_fn: Callable[[SwitchData], Any] | None = None


SWITCH_SENSORS: tuple[SwitchSensorDesc, ...] = (
    SwitchSensorDesc(
        key="uptime",
        translation_key="uptime",
        icon="mdi:timer-outline",
        value_fn=lambda d: d.uptime or None,
    ),
    SwitchSensorDesc(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
        value_fn=lambda d: d.firmware or None,
    ),
    SwitchSensorDesc(
        key="mac_address",
        translation_key="mac_address",
        icon="mdi:identifier",
        value_fn=lambda d: d.mac or None,
    ),
    SwitchSensorDesc(
        key="ports_up",
        translation_key="ports_up",
        icon="mdi:ethernet",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(1 for p in d.ports if p.status == PORT_STATUS_UP),
    ),
    SwitchSensorDesc(
        key="ports_total",
        translation_key="ports_total",
        icon="mdi:ethernet",
        value_fn=lambda d: len(d.ports),
    ),
    SwitchSensorDesc(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.temperature,
    ),
)

# Switch sensors that exist only on firmware reporting the value
_OPTIONAL_SWITCH_SENSORS = {"uptime", "temperature"}


# ────────────────────────────────────────────────────────────────────────────
# Per-port sensor descriptors
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class PortSensorDesc(SensorEntityDescription):
    value_fn: Callable[[PortData], Any] | None = None


PORT_STATE_OPTIONS = [
    "disconnected", "disabled", "10m", "100m", "1000m", "2500m", "5000m", "10g",
]


def port_state(p: PortData) -> str | None:
    """Combine link and speed into one state: "disconnected", "disabled" or the speed."""
    if p.status == PORT_STATUS_DISABLED:
        return "disabled"
    if p.status != PORT_STATUS_UP:
        return "disconnected"
    m = re.match(r"(\d+)\s*([MG])?", p.speed, re.IGNORECASE)
    if not m:
        return None
    mbit = int(m.group(1)) * (1000 if (m.group(2) or "").upper() == "G" else 1)
    state = f"{mbit // 1000}g" if mbit >= 10000 else f"{mbit}m"
    if state not in PORT_STATE_OPTIONS:
        _LOGGER.warning("Unknown port speed %r", p.speed)
        return None
    return state


PORT_SENSORS: tuple[PortSensorDesc, ...] = (
    PortSensorDesc(
        key="state",
        translation_key="port",
        device_class=SensorDeviceClass.ENUM,
        options=PORT_STATE_OPTIONS,
        value_fn=port_state,
    ),
    PortSensorDesc(
        key="duplex",
        translation_key="duplex",
        entity_registry_enabled_default=False,
        icon="mdi:transfer",
        device_class=SensorDeviceClass.ENUM,
        options=["full", "half"],
        value_fn=lambda p: (p.duplex or "").lower() or None,
    ),
    PortSensorDesc(
        key="tx_bytes",
        translation_key="tx_bytes",
        entity_registry_enabled_default=False,
        icon="mdi:upload-network-outline",
        native_unit_of_measurement="B",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.tx_bytes,
    ),
    PortSensorDesc(
        key="rx_bytes",
        translation_key="rx_bytes",
        entity_registry_enabled_default=False,
        icon="mdi:download-network-outline",
        native_unit_of_measurement="B",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.rx_bytes,
    ),
    PortSensorDesc(
        key="tx_packets",
        translation_key="tx_packets",
        entity_registry_enabled_default=False,
        icon="mdi:arrow-up-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.tx_packets,
    ),
    PortSensorDesc(
        key="rx_packets",
        translation_key="rx_packets",
        entity_registry_enabled_default=False,
        icon="mdi:arrow-down-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.rx_packets,
    ),
    PortSensorDesc(
        key="tx_errors",
        translation_key="tx_errors",
        entity_registry_enabled_default=False,
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.tx_errors,
    ),
    PortSensorDesc(
        key="rx_errors",
        translation_key="rx_errors",
        entity_registry_enabled_default=False,
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.rx_errors,
    ),
    PortSensorDesc(
        key="flow_control",
        translation_key="flow_control",
        entity_registry_enabled_default=False,
        icon="mdi:swap-horizontal",
        device_class=SensorDeviceClass.ENUM,
        options=["enabled", "disabled"],
        value_fn=lambda p: (p.flow_control or "").lower() or None,
    ),
)

# Port sensors that exist only where the firmware reports the value (None = not reported)
_OPTIONAL_PORT_SENSORS = {"tx_bytes", "rx_bytes", "tx_errors", "rx_errors", "duplex", "flow_control"}


# ────────────────────────────────────────────────────────────────────────────
# Platform setup
# ────────────────────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HoracoCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    data = coordinator.data
    ent_reg = er.async_get(hass)

    # Switch-level sensors (skip uptime/temperature on firmware that doesn't report them)
    for desc in SWITCH_SENSORS:
        if desc.key in _OPTIONAL_SWITCH_SENSORS and data and desc.value_fn(data) is None:
            # Remove an entry left behind by earlier versions or the other firmware
            stale = ent_reg.async_get_entity_id(
                "sensor", DOMAIN, f"{DOMAIN}_{coordinator.scraper.ip}_{desc.key}"
            )
            if stale:
                ent_reg.async_remove(stale)
            continue
        entities.append(SwitchLevelSensor(coordinator, desc))

    # Port-level sensors (on the switch device)
    if data:
        for port in data.ports:
            for desc in PORT_SENSORS:
                # Only what the firmware actually reports: bytes and errors are
                # missing on some CGI firmware, duplex and flow control on RTLPlayground
                if desc.key in _OPTIONAL_PORT_SENSORS and getattr(port, desc.key) is None:
                    # Duplex and flow control vanish for good after flashing
                    # RTLPlayground; counters may just be missing for one poll
                    if desc.key in ("duplex", "flow_control"):
                        stale = ent_reg.async_get_entity_id(
                            "sensor", DOMAIN,
                            f"{DOMAIN}_{coordinator.scraper.ip}_port{port.port}_{desc.key}",
                        )
                        if stale:
                            ent_reg.async_remove(stale)
                    continue
                entities.append(PortLevelSensor(coordinator, port.port, desc))

    async_add_entities(entities)


# ────────────────────────────────────────────────────────────────────────────
# Entity classes
# ────────────────────────────────────────────────────────────────────────────

class SwitchLevelSensor(CoordinatorEntity[HoracoCoordinator], SensorEntity):
    """Sensor attached to the parent switch device."""

    entity_description: SwitchSensorDesc

    def __init__(self, coordinator: HoracoCoordinator, desc: SwitchSensorDesc) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_unique_id = f"{DOMAIN}_{coordinator.scraper.ip}_{desc.key}"
        self.entity_id = f"sensor.{object_id(coordinator.scraper.ip, desc.key)}"
        self._attr_has_entity_name = True
        self._attr_device_info = switch_device_info(coordinator)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data) if self.coordinator.data else None


class PortLevelSensor(CoordinatorEntity[HoracoCoordinator], SensorEntity):
    """Per-port sensor, attached to the switch device."""

    entity_description: PortSensorDesc

    def __init__(
        self,
        coordinator: HoracoCoordinator,
        port_num: str,
        desc: PortSensorDesc,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._port_num = port_num
        self._attr_unique_id = f"{DOMAIN}_{coordinator.scraper.ip}_port{port_num}_{desc.key}"
        suffix = PORT_ID_SUFFIX.get(desc.key, desc.key)
        self.entity_id = "sensor." + object_id(
            coordinator.scraper.ip, f"port_{port_num}" + (f"_{suffix}" if suffix else "")
        )
        self._attr_has_entity_name = True
        self._attr_translation_placeholders = {"port": port_num}
        self._attr_device_info = switch_device_info(coordinator)

    def _port(self) -> PortData | None:
        if not self.coordinator.data:
            return None
        return next((p for p in self.coordinator.data.ports if p.port == self._port_num), None)

    @property
    def native_value(self) -> Any:
        p = self._port()
        return self.entity_description.value_fn(p) if p else None

    @property
    def icon(self) -> str | None:
        if self.entity_description.key != "state":
            return super().icon
        p = self._port()
        return "mdi:ethernet" if (p and p.status == PORT_STATUS_UP) else "mdi:ethernet-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # All port details on the main "Port N" sensor, nothing on the optional ones
        if self.entity_description.key != "state":
            return None
        p = self._port()
        if not p:
            return {}
        attrs = {
            "link":         p.link,
            "speed":        p.speed,
            "duplex":       p.duplex,
            "flow_control": p.flow_control,
            "tx_packets":   p.tx_packets,
            "rx_packets":   p.rx_packets,
            "tx_errors":    p.tx_errors,
            "rx_errors":    p.rx_errors,
            "tx_bytes":     p.tx_bytes,
            "rx_bytes":     p.rx_bytes,
        }
        if p.name:
            attrs["port_name"] = p.name
        if p.sfp_module:
            attrs["sfp_module"] = p.sfp_module
        return attrs
