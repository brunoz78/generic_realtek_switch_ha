"""Config flow for the Generic Realtek Switch integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_FIRMWARE,
    CONF_FIRMWARE_REPO,
    CONF_MIGRATED_FROM,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_FIRMWARE_REPO,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
    FIRMWARE_CGI,
    FIRMWARE_RTLPLAYGROUND,
    OLD_DOMAIN,
)
from .rtlplayground import RtlPlaygroundClient, detect_rtlplayground
from .scraper import CgiScraper, SwitchData

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
    vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
    vol.Required(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
})


async def _try_connect(hass: HomeAssistant, data: dict[str, Any]) -> tuple[SwitchData, str]:
    """Detect the firmware, log in once and return the snapshot and firmware type."""
    session = async_get_clientsession(hass)
    http_port = data.get(CONF_PORT, DEFAULT_PORT)
    rtl = await detect_rtlplayground(session, data[CONF_HOST], http_port)
    if rtl is None:
        raise ConnectionError("cannot_connect")
    scraper: CgiScraper | RtlPlaygroundClient
    if rtl:
        scraper = RtlPlaygroundClient(
            session=session, ip=data[CONF_HOST], password=data[CONF_PASSWORD], http_port=http_port,
        )
    else:
        scraper = CgiScraper(
            session=session,
            ip=data[CONF_HOST],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            http_port=http_port,
        )
    result = await scraper.scrape()
    if not result.available:
        raise ConnectionError("cannot_connect")
    return result, FIRMWARE_RTLPLAYGROUND if rtl else FIRMWARE_CGI


class SwitchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 4

    def _old_entries(self) -> list[config_entries.ConfigEntry]:
        """Entries of the integration under its former name not taken over yet."""
        taken = {e.data.get(CONF_HOST) for e in self._async_current_entries(include_ignore=False)}
        return [
            e for e in self.hass.config_entries.async_entries(OLD_DOMAIN)
            if e.data.get(CONF_HOST) not in taken
        ]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is None and self._old_entries():
            return self.async_show_menu(step_id="user", menu_options=["migrate", "manual"])
        return await self.async_step_manual(user_input)

    async def async_step_migrate(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Take over every switch of the integration under its former name."""
        old = self._old_entries()
        for entry in old:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": config_entries.SOURCE_IMPORT},
                    data={CONF_MIGRATED_FROM: entry.entry_id},
                )
            )
        return self.async_abort(
            reason="migration_started", description_placeholders={"count": str(len(old))}
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Create the entry for one switch of the integration under its former name.

        The devices and entities are moved over in async_setup_entry, so entity
        IDs, history, names and areas stay as they are.
        """
        old = self.hass.config_entries.async_get_entry(import_data[CONF_MIGRATED_FROM])
        if old is None or old.domain != OLD_DOMAIN:
            return self.async_abort(reason="migration_source_missing")
        await self.async_set_unique_id(old.data[CONF_HOST])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=old.title,
            data={**old.data, CONF_MIGRATED_FROM: old.entry_id},
            options=dict(old.options),
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                sw, firmware = await _try_connect(self.hass, user_input)
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                title = f"{sw.model} ({user_input[CONF_HOST]})"
                return self.async_create_entry(
                    title=title, data={**user_input, CONF_FIRMWARE: firmware}
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> SwitchOptionsFlow:
        return SwitchOptionsFlow(entry)


class SwitchOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            repo = user_input.get(CONF_FIRMWARE_REPO, "").strip()
            if re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                return self.async_create_entry(
                    title="", data={**user_input, CONF_FIRMWARE_REPO: repo}
                )
            errors[CONF_FIRMWARE_REPO] = "invalid_repo"
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "scan_interval",
                    default=self.entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                vol.Optional(
                    CONF_FIRMWARE_REPO,
                    default=self.entry.options.get(CONF_FIRMWARE_REPO, DEFAULT_FIRMWARE_REPO),
                ): str,
            }),
            errors=errors,
        )
