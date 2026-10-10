"""Generic Realtek Switch — Home Assistant integration.

Talks directly to the switch, no intermediate service needed: to the CGI
pages of the original firmware (scraping logic based on
https://github.com/byte4geek/switch-dashboard) or to the JSON interface of
the RTLPlayground firmware.
"""
from __future__ import annotations

import inspect
import logging
import re
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FIRMWARE,
    CONF_MIGRATED_FROM,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FIRMWARE_CGI,
    FIRMWARE_RTLPLAYGROUND,
    OLD_DOMAIN,
    object_id,
)
from .rtlplayground import RtlPlaygroundClient, detect_rtlplayground
from .scraper import CgiScraper, SwitchData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.UPDATE,
]


async def _async_take_over(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move devices and entities of the switch from the former integration name.

    Entity IDs, history, names, areas and the device stay as they are; only
    the owning integration, config entry and unique IDs change. The old entry
    is removed afterwards.
    """
    old_id = entry.data[CONF_MIGRATED_FROM]
    old = hass.config_entries.async_get_entry(old_id)
    if old is not None and old.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(old_id)

    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, old_id):
        if hass.states.get(ent.entity_id) is not None:
            hass.states.async_remove(ent.entity_id)
        new_unique_id = ent.unique_id
        if new_unique_id.startswith(f"{OLD_DOMAIN}_"):
            new_unique_id = DOMAIN + new_unique_id[len(OLD_DOMAIN):]
        ent_reg.async_update_entity_platform(
            ent.entity_id, DOMAIN, new_config_entry_id=entry.entry_id, new_unique_id=new_unique_id
        )

    dev_reg = dr.async_get(hass)
    # Newer Home Assistant versions move a device in one step and deprecate
    # adding and removing config entries on it
    can_move = "new_config_entry_id" in inspect.signature(dev_reg.async_update_device).parameters
    for dev in dr.async_entries_for_config_entry(dev_reg, old_id):
        identifiers = {
            (DOMAIN, ident) if domain == OLD_DOMAIN else (domain, ident)
            for domain, ident in dev.identifiers
        }
        if can_move:
            dev_reg.async_update_device(
                dev.id, new_config_entry_id=entry.entry_id, new_identifiers=identifiers
            )
        else:
            dev_reg.async_update_device(dev.id, add_config_entry_id=entry.entry_id)
            dev_reg.async_update_device(
                dev.id, remove_config_entry_id=old_id, new_identifiers=identifiers
            )

    data = {k: v for k, v in entry.data.items() if k != CONF_MIGRATED_FROM}
    hass.config_entries.async_update_entry(entry, data=data)
    if old is not None:
        await hass.config_entries.async_remove(old_id)
    _LOGGER.info("[%s] Taken over from %s", entry.data[CONF_HOST], OLD_DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a switch from a config entry."""
    if CONF_MIGRATED_FROM in entry.data:
        await _async_take_over(hass, entry)

    session = async_get_clientsession(hass)
    ip = entry.data[CONF_HOST]
    http_port = entry.data.get(CONF_PORT, 80)

    # Re-check the firmware on every start, so a switch flashed with
    # RTLPlayground (or back to the original) keeps working after a reload.
    rtl = await detect_rtlplayground(session, ip, http_port)
    firmware = entry.data.get(CONF_FIRMWARE, FIRMWARE_CGI)
    if rtl is not None:
        detected = FIRMWARE_RTLPLAYGROUND if rtl else FIRMWARE_CGI
        if detected != firmware:
            _LOGGER.info("[%s] Firmware changed: %s → %s", ip, firmware, detected)
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_FIRMWARE: detected}
            )
            firmware = detected

    scraper: CgiScraper | RtlPlaygroundClient
    if firmware == FIRMWARE_RTLPLAYGROUND:
        scraper = RtlPlaygroundClient(
            session=session, ip=ip, password=entry.data[CONF_PASSWORD], http_port=http_port,
        )
    else:
        scraper = CgiScraper(
            session=session,
            ip=ip,
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            http_port=http_port,
        )

    coordinator = SwitchCoordinator(hass, scraper, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Changed options (polling interval, firmware repository) apply right away
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries.

    v1 → v2: ports are no longer child devices. Port entities move onto the
    switch device, get IDs like binary_sensor.switch_10_0_1_4_port_1_link,
    everything except link and speed is disabled by default, and the empty
    port devices are removed.
    v2 → v3: link and speed are merged into one "Port N" sensor; the old
    link/speed entries are removed.
    v3 → v4: error sensors get fixed English entity IDs.
    """
    if entry.version > 4:
        return False

    if entry.version == 1:
        ip = entry.data[CONF_HOST]
        slug = ip.replace(".", "_")
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        switch_dev = next(
            (
                dev
                for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
                if (DOMAIN, ip) in dev.identifiers
            ),
            None,
        )
        pattern = re.compile(rf"^{DOMAIN}_{re.escape(ip)}_port(\d+)_(\w+)$")
        suffix = {"tx_bytes": "tx", "rx_bytes": "rx"}

        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            m = pattern.match(ent.unique_id)
            if not m:
                continue
            port, key = m.groups()
            changes: dict = {}
            if switch_dev:
                changes["device_id"] = switch_dev.id
            new_id = f"{ent.domain}.switch_{slug}_port_{port}_{suffix.get(key, key)}"
            # Only replace auto-generated IDs ("…port_1_link_4"), never user-chosen ones
            if ent.entity_id.split(".", 1)[1].startswith("port_") and not ent_reg.async_get(new_id):
                changes["new_entity_id"] = new_id
            if key not in ("link", "speed") and ent.disabled_by is None:
                changes["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
            ent_reg.async_update_entity(ent.entity_id, **changes)

        if switch_dev:
            for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
                if any(d == DOMAIN and i.startswith(f"{ip}_port") for d, i in dev.identifiers):
                    dev_reg.async_remove_device(dev.id)

        hass.config_entries.async_update_entry(entry, version=2)
        _LOGGER.info("[%s] Migrated config entry to version 2", ip)

    if entry.version == 2:
        # v2 → v3: "Port N Link" (binary_sensor) and "Port N Speed" are replaced
        # by one combined "Port N" sensor; drop the old registry entries.
        ip = entry.data[CONF_HOST]
        ent_reg = er.async_get(hass)
        pattern = re.compile(rf"^{DOMAIN}_{re.escape(ip)}_port\d+_(link|speed)$")
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if pattern.match(ent.unique_id):
                ent_reg.async_remove(ent.entity_id)

        hass.config_entries.async_update_entry(entry, version=3)
        _LOGGER.info("[%s] Migrated config entry to version 3", ip)

    if entry.version == 3:
        # v3 → v4: the error sensors added in v3 got IDs from the translated
        # name ("…_port_2_sendefehler"); give them the fixed English IDs.
        ip = entry.data[CONF_HOST]
        ent_reg = er.async_get(hass)
        pattern = re.compile(rf"^{DOMAIN}_{re.escape(ip)}_port(\d+)_(tx_errors|rx_errors)$")
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            m = pattern.match(ent.unique_id)
            if not m:
                continue
            new_id = f"sensor.{object_id(ip, f'port_{m.group(1)}_{m.group(2)}')}"
            if ent.entity_id != new_id and not ent_reg.async_get(new_id):
                ent_reg.async_update_entity(ent.entity_id, new_entity_id=new_id)

        hass.config_entries.async_update_entry(entry, version=4)
        _LOGGER.info("[%s] Migrated config entry to version 4", ip)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok


class SwitchCoordinator(DataUpdateCoordinator[SwitchData]):
    """Central coordinator — polls the switch at a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        scraper: CgiScraper | RtlPlaygroundClient,
        entry: ConfigEntry,
    ) -> None:
        self.scraper = scraper
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{scraper.ip}",
            update_interval=timedelta(
                seconds=entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
            ),
        )

    async def _async_update_data(self) -> SwitchData:
        data = await self.scraper.scrape()
        if not data.available:
            raise UpdateFailed(f"Switch {self.scraper.ip} is unreachable")
        return data
