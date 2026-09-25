"""Bleak-based Bluetooth transport implementation."""

import logging
from collections.abc import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from ._constants import CASA_UUID
from ._transport import BluetoothTransport, TransportConnection
from .errors import BluetoothError

_LOGGER = logging.getLogger(__name__)


class BleakTransport(BluetoothTransport):
    """Transport implementation using bleak library for local Bluetooth."""

    async def discover(self, timeout: float = 10.0) -> list[BLEDevice]:
        """Scan for Casambi devices using BleakScanner."""
        import platform

        from bleak.exc import BleakDBusError

        discovered_devices: list[BLEDevice] = []

        try:
            if platform.system() == "Darwin":
                _LOGGER.debug(
                    "MacOS operating system detected, using undocumented IOBluetooth API to fetch MAC Address."
                )
                # https://bleak.readthedocs.io/en/latest/backends/macos.html#bleak.backends.corebluetooth.scanner.CBScannerArgs.use_bdaddr
                devices_and_advertisements = await BleakScanner.discover(
                    return_adv=True, cb={"use_bdaddr": True}, timeout=timeout
                )
            else:
                devices_and_advertisements = await BleakScanner.discover(
                    return_adv=True, timeout=timeout
                )
        except BleakDBusError as e:
            raise BluetoothError(e.dbus_error, e.dbus_error_details) from e
        except BleakError as e:
            raise BluetoothError from e

        # Filter for Casambi devices
        for _, (device, advertisement) in devices_and_advertisements.items():
            if 963 in advertisement.manufacturer_data:
                if CASA_UUID in advertisement.service_uuids:
                    _LOGGER.debug(f"Discovered network at {device.address}")
                    discovered_devices.append(device)

        return discovered_devices

    async def connect(self, device: BLEDevice) -> "BleakTransportConnection":
        """Connect to a device and return a BleakTransportConnection."""
        from bleak_retry_connector import (
            BleakNotFoundError,
            close_stale_connections,
            establish_connection,
        )

        try:
            await close_stale_connections(device)
            client = await establish_connection(
                BleakClient, device, "Casambi Network"
            )
            return BleakTransportConnection(client, device)
        except BleakNotFoundError as e:
            raise BluetoothError(f"Failed to find device: {e}") from e
        except BleakError as e:
            raise BluetoothError(f"Failed to connect: {e}") from e


class BleakTransportConnection(TransportConnection):
    """Connection wrapper around BleakClient."""

    def __init__(self, client: BleakClient, device: BLEDevice):
        self._client = client
        self._device = device
        self._notify_callbacks: dict[str, Callable[[bytes], None]] = {}
        self._logger = logging.getLogger(__name__)

    @property
    def is_connected(self) -> bool:
        """Check if the BleakClient is connected."""
        return self._client.is_connected

    async def disconnect(self) -> None:
        """Disconnect the BleakClient."""
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                self._logger.error("Failed to disconnect BleakClient.", exc_info=True)

    async def read_gatt_char(self, char_uuid: str) -> bytes:
        """Read a GATT characteristic by UUID."""
        if not self._client.is_connected:
            raise BluetoothError("Not connected to device")
        return await self._client.read_gatt_char(char_uuid)

    async def write_gatt_char(self, char_uuid: str, data: bytes) -> None:
        """Write to a GATT characteristic by UUID."""
        if not self._client.is_connected:
            raise BluetoothError("Not connected to device")
        await self._client.write_gatt_char(char_uuid, data)

    async def start_notify(
        self, char_uuid: str, callback: Callable[[bytes], None]
    ) -> None:
        """Start notifications on a GATT characteristic."""
        if not self._client.is_connected:
            raise BluetoothError("Not connected to device")

        # Store the callback for this characteristic
        self._notify_callbacks[char_uuid] = callback

        # Create the internal handler that wraps the user callback
        def notify_handler(
            sender: BleakGATTCharacteristic, data: bytearray
        ) -> None:
            """Handle internal notification."""
            if sender.uuid in self._notify_callbacks:
                self._notify_callbacks[sender.uuid](bytes(data))

        # Start notifications with bluez compatibility
        await self._client.start_notify(
            char_uuid, notify_handler, bluez={"use_start_notify": True}
        )

    async def stop_notify(self, char_uuid: str) -> None:
        """Stop notifications on a GATT characteristic."""
        if self._client and self._client.is_connected:
            await self._client.stop_notify(char_uuid)
        self._notify_callbacks.pop(char_uuid, None)
