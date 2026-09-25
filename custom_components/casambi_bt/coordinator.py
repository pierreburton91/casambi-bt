"""Data update coordinator for the Casambi Bluetooth integration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from CasambiBt import Casambi, Group, Unit, UnitControlType, UnitState
from CasambiBt.errors import (
    AuthenticationError,
    BluetoothError,
    NetworkNotFoundError,
    NetworkOnlineUpdateNeededError,
    ProtocolError,
    UnsupportedProtocolVersion,
)

from .const import (
    CONNECT_TIMEOUT,
    DOMAIN,
    OPERATION_TIMEOUT,
    RECONNECT_BACKOFF_FACTOR,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
)

_LOGGER = logging.getLogger(__name__)

# Every failure here just means "not connected yet / lost connection" from the
# coordinator's perspective - retried with backoff, or surfaced as
# ConfigEntryNotReady on first setup.
_CONNECT_ERRORS: tuple[type[Exception], ...] = (
    NetworkNotFoundError,
    BluetoothError,
    ProtocolError,
    UnsupportedProtocolVersion,
    NetworkOnlineUpdateNeededError,
    TimeoutError,
)


class CasambiBtCoordinator(DataUpdateCoordinator[dict[str, Unit]]):
    """Coordinates the connection lifecycle and push-based state for one Casambi network.

    Push-driven (update_interval=None): unit state arrives via BLE notifications
    through CasambiBt's registered callbacks, not polling. This coordinator also
    owns reconnection - CasambiBt has no automatic reconnect anywhere.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{entry.entry_id}",
            update_interval=None,
        )
        self.entry = entry
        self._address: str = entry.data[CONF_ADDRESS]
        self._password: str = entry.data[CONF_PASSWORD]
        cache_path = Path(hass.config.path(".storage", DOMAIN))
        self._casambi = Casambi(cachePath=cache_path)
        self._op_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self.data = {}

    @property
    def casambi(self) -> Casambi:
        return self._casambi

    async def async_setup(self) -> None:
        """Connect to the network for the first time.

        Raises ConfigEntryAuthFailed/ConfigEntryNotReady on failure, per HA's
        config entry setup contract.
        """
        self._casambi.registerUnitChangedHandler(self._handle_unit_changed)
        self._casambi.registerDisconnectCallback(self._handle_disconnect)

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            raise ConfigEntryNotReady(
                f"{self._address} is not currently visible to the Bluetooth stack"
            )

        try:
            async with self._op_lock, asyncio.timeout(CONNECT_TIMEOUT):
                await self._casambi.connect(ble_device, self._password)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Invalid Casambi network password") from err
        except _CONNECT_ERRORS as err:
            raise ConfigEntryNotReady(f"Could not connect to {self._address}") from err

        self.data = {unit.uuid: unit for unit in self._casambi.units}
        self.last_update_success = True

    def _handle_unit_changed(self, unit: Unit) -> None:
        # Fires synchronously from CasambiBt's BLE notification path - marshal
        # onto the HA event loop before touching coordinator/entity state.
        self.hass.loop.call_soon_threadsafe(self._apply_unit_update, unit)

    def _apply_unit_update(self, unit: Unit) -> None:
        self.data[unit.uuid] = unit
        self.async_set_updated_data(self.data)

    def _handle_disconnect(self) -> None:
        self.hass.loop.call_soon_threadsafe(self._start_reconnect_task)

    def _start_reconnect_task(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        _LOGGER.warning(
            "Casambi network %s disconnected; attempting to reconnect", self._address
        )
        self._reconnect_task = self.hass.async_create_background_task(
            self._reconnect_loop(),
            f"{DOMAIN}-reconnect-{self.entry.entry_id}",
        )

    async def _reconnect_loop(self) -> None:
        delay = RECONNECT_INITIAL_DELAY
        while True:
            await asyncio.sleep(delay)

            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )
            if ble_device is None:
                delay = min(delay * RECONNECT_BACKOFF_FACTOR, RECONNECT_MAX_DELAY)
                continue

            try:
                async with self._op_lock, asyncio.timeout(CONNECT_TIMEOUT):
                    await self._casambi.connect(ble_device, self._password)
            except AuthenticationError:
                _LOGGER.warning(
                    "Casambi network %s rejected the stored password; starting reauth",
                    self._address,
                )
                self.entry.async_start_reauth(self.hass)
                return
            except (
                Exception
            ):  # noqa: BLE001 - any failure here just means "keep retrying"
                _LOGGER.debug(
                    "Reconnect attempt to %s failed, retrying in %ss",
                    self._address,
                    delay,
                    exc_info=True,
                )
                delay = min(delay * RECONNECT_BACKOFF_FACTOR, RECONNECT_MAX_DELAY)
                continue

            _LOGGER.info("Reconnected to Casambi network %s", self._address)
            self.data = {unit.uuid: unit for unit in self._casambi.units}
            self.async_set_updated_data(self.data)
            return

    async def async_set_control(
        self,
        target: Unit | Group | None,
        control_type: UnitControlType,
        value: Any,
    ) -> None:
        """Send a setControl() command, bounded by a timeout.

        CasambiBt has no internal timeout on BLE protocol operations, so without
        this a stalled device could hang the calling HA service call forever.
        """
        try:
            async with self._op_lock, asyncio.timeout(OPERATION_TIMEOUT):
                await self._casambi.setControl(target, control_type, value)
        except TimeoutError as err:
            raise HomeAssistantError(
                "Timed out sending command to the Casambi network"
            ) from err

    async def async_set_unit_state(self, target: Unit, state: UnitState) -> None:
        """Send a setUnitState() command, bounded by a timeout."""
        try:
            async with self._op_lock, asyncio.timeout(OPERATION_TIMEOUT):
                await self._casambi.setUnitState(target, state)
        except TimeoutError as err:
            raise HomeAssistantError(
                "Timed out sending command to the Casambi network"
            ) from err

    async def async_shutdown(self) -> None:
        """Tear down the connection and any background tasks."""
        await super().async_shutdown()

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

        # Unregister before disconnect(): Casambi.disconnect() unconditionally
        # fires the disconnect callback if the connection was authenticated,
        # regardless of whether the disconnect was intentional. Doing this in
        # the other order would make our own intentional teardown schedule a
        # spurious reconnect against a config entry that's already unloading.
        with contextlib.suppress(ValueError):
            self._casambi.unregisterUnitChangedHandler(self._handle_unit_changed)
        with contextlib.suppress(ValueError):
            self._casambi.unregisterDisconnectCallback(self._handle_disconnect)

        await self._casambi.disconnect()
