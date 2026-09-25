"""Config flow for the Casambi Bluetooth integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .CasambiBt import Casambi
from .CasambiBt.errors import (
    AuthenticationError,
    BluetoothError,
    NetworkNotFoundError,
    NetworkOnlineUpdateNeededError,
    ProtocolError,
    UnsupportedProtocolVersion,
)
from .const import CASAMBI_SERVICE_UUID, CONNECT_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def _async_try_connect(
    hass: HomeAssistant, address: str, password: str
) -> str | None:
    """Attempt to connect to a Casambi network. Return an error key, or None on success."""
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is None:
        return "cannot_connect"

    probe = Casambi()
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            await probe.connect(ble_device, password)
    except AuthenticationError:
        return "invalid_auth"
    except (NetworkNotFoundError, BluetoothError):
        return "cannot_connect"
    except TimeoutError:
        return "timeout_connect"
    except (ProtocolError, UnsupportedProtocolVersion, NetworkOnlineUpdateNeededError):
        _LOGGER.debug(
            "Protocol-level error while validating Casambi network", exc_info=True
        )
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error while validating Casambi network")
        return "unknown"
    else:
        return None
    finally:
        await probe.disconnect()


class CasambiBtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Casambi Bluetooth integration."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Casambi network discovered by Home Assistant's Bluetooth stack."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the network password after discovery, or after a manual pick."""
        assert self._address is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _async_try_connect(
                self.hass, self._address, user_input[CONF_PASSWORD]
            )
            if error is None:
                return self.async_create_entry(
                    title=self._name or self._address,
                    data={
                        CONF_ADDRESS: self._address,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"name": self._name or self._address},
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a manually initiated flow, listing already-discovered networks."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._name = self._discovered.get(self._address, self._address)
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_bluetooth_confirm()

        current_addresses = self._async_current_ids()
        self._discovered = {
            info.address: info.name or info.address
            for info in bluetooth.async_discovered_service_info(self.hass)
            if CASAMBI_SERVICE_UUID in info.service_uuids
            and info.address not in current_addresses
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a reauth triggered when the stored password stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        assert reauth_entry is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _async_try_connect(
                self.hass, reauth_entry.data[CONF_ADDRESS], user_input[CONF_PASSWORD]
            )
            if error is None:
                self.hass.config_entries.async_update_entry(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"name": reauth_entry.title},
            errors=errors,
        )
