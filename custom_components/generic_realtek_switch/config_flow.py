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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
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
from .rtlplayground import AuthFailed, RtlPlaygroundClient, detect_rtlplayground
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


async def _check(hass: HomeAssistant, data: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    """Connect with the given data; return form errors and the detected firmware."""
    try:
        _, firmware = await _try_connect(hass, data)
    except AuthFailed:
        return {"base": "invalid_auth"}, None
    except ConnectionError:
        return {"base": "cannot_connect"}, None
    except Exception:
        _LOGGER.exception("Unexpected error")
        return {"base": "unknown"}, None
    return {}, firmware


def _move_host(hass: HomeAssistant, entry: config_entries.ConfigEntry, old: str, new: str) -> None:
    """Point the unique IDs of the switch at its new address.

    Entity IDs, names, history and dashboards stay as they are.
    """
    ent_reg = er.async_get(hass)
    prefix = f"{DOMAIN}_{old}_"
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent.unique_id.startswith(prefix):
            ent_reg.async_update_entity(
                ent.entity_id, new_unique_id=f"{DOMAIN}_{new}_" + ent.unique_id[len(prefix):]
            )
    dev_reg = dr.async_get(hass)
    for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if (DOMAIN, old) in dev.identifiers:
            dev_reg.async_update_device(
                dev.id, new_identifiers=(dev.identifiers - {(DOMAIN, old)}) | {(DOMAIN, new)}
            )


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
            except AuthFailed:
                errors["base"] = "invalid_auth"
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

    def _entry(self) -> config_entries.ConfigEntry:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        return entry

    async def _apply(self, entry: config_entries.ConfigEntry, **changes: Any) -> None:
        """Store the new settings and start the switch again with them."""
        if entry.state is config_entries.ConfigEntryState.LOADED:
            await self.hass.config_entries.async_unload(entry.entry_id)
        old_host = entry.data[CONF_HOST]
        new_host = changes["data"][CONF_HOST]
        if new_host != old_host:
            _move_host(self.hass, entry, old_host, new_host)
            changes["unique_id"] = new_host
            changes["title"] = entry.title.replace(old_host, new_host)
        self.hass.config_entries.async_update_entry(entry, **changes)
        await self.hass.config_entries.async_reload(entry.entry_id)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """The switch rejected the stored password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self._entry()
        cgi = entry.data.get(CONF_FIRMWARE) != FIRMWARE_RTLPLAYGROUND
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            errors, firmware = await _check(self.hass, data)
            if not errors:
                await self._apply(entry, data={**data, CONF_FIRMWARE: firmware})
                return self.async_abort(reason="reauth_successful")
        fields: dict[Any, Any] = {}
        if cgi:
            fields[vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, DEFAULT_USERNAME))] = str
        fields[vol.Required(CONF_PASSWORD)] = str
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Change the address or the credentials of a configured switch."""
        entry = self._entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input, CONF_HOST: user_input[CONF_HOST].strip()}
            # Empty password field: keep the stored one
            if not user_input.get(CONF_PASSWORD):
                data[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
            taken = {
                e.data.get(CONF_HOST)
                for e in self._async_current_entries(include_ignore=False)
                if e.entry_id != entry.entry_id
            }
            if data[CONF_HOST] in taken:
                return self.async_abort(reason="already_configured")
            errors, firmware = await _check(self.hass, data)
            if not errors:
                await self._apply(entry, data={**data, CONF_FIRMWARE: firmware})
                return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                vol.Optional(CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)): vol.Coerce(int),
                vol.Optional(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
                vol.Optional(CONF_PASSWORD): str,
            }),
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
