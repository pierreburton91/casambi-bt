"""ESPHome Bluetooth Proxy transport implementation.

Uses aioesphomeapi to perform BLE operations through an ESP32
running ESPHome with the bluetooth_proxy component.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from bleak.backends.device import BLEDevice

from ._constants import CASA_UUID
from ._transport import BluetoothTransport, TransportConnection
from .errors import BluetoothError

_LOGGER = logging.getLogger(__name__)

# Try to import aioesphomeapi, but make it optional
try:
    import aioesphomeapi
    from aioesphomeapi import BluetoothLEAdvertisement
    from aioesphomeapi.client import APIClient

    ESPHOME_AVAILABLE = True
except ImportError:
    ESPHOME_AVAILABLE = False
    APIClient = None  # type: ignore[misc, assignment]
    BluetoothLEAdvertisement = None  # type: ignore[misc, assignment]


class ESPHomeTransport(BluetoothTransport):
    """Transport implementation using ESPHome Bluetooth Proxy.

    Connects to an ESPHome device over the network and uses it
    as a BLE passthrough proxy.
    """

    def __init__(
        self,
        host: str,
        port: int = 6053,
        username: str | None = None,
        password: str | None = None,
        noise_psk: str | None = None,
    ):
        if not ESPHOME_AVAILABLE:
            raise ImportError(
                "aioesphomeapi is required for ESPHome transport. "
                "Install it with: pip install aioesphomeapi"
            )
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._noise_psk = noise_psk
        self._api: APIClient | None = None
        self._scan_subscription: Callable[[], None] | None = None

    async def _get_api(self) -> APIClient:
        """Get or create the API client connection."""
        if self._api is None or not self._api.is_connected:
            self._api = APIClient(
                self._host,
                self._port,
                username=self._username,
                password=self._password,
                noise_psk=self._noise_psk,
            )
            try:
                await self._api.connect()
            except Exception as e:
                raise BluetoothError(f"Failed to connect to ESPHome at {self._host}:{self._port}: {e}") from e
        return self._api

    async def discover(self, timeout: float = 10.0) -> list[BLEDevice]:
        """Scan for Casambi devices via ESPHome Bluetooth Proxy."""
        api = await self._get_api()

        discovered_devices: list[BLEDevice] = []

        def handle_advertisement(adv: BluetoothLEAdvertisement) -> None:
            """Handle a BLE advertisement from ESPHome."""
            # Check if this device advertises the Casambi service UUID
            # ESPHome provides service_uuids as a list of strings
            if hasattr(adv, 'service_uuids') and adv.service_uuids:
                if CASA_UUID.lower() in [uuid.lower() for uuid in adv.service_uuids]:
                    # Also check for manufacturer data 963 (Casambi)
                    if hasattr(adv, 'manufacturer_data'):
                        for mfg_id, _mfg_data in adv.manufacturer_data.items():
                            if mfg_id == 963:
                                device = BLEDevice(
                                    address=adv.address,
                                    name=adv.name or "Casambi Network",
                                    details={},
                                    rssi=adv.rssi,
                                )
                                discovered_devices.append(device)
                                _LOGGER.debug(f"Discovered Casambi device: {adv.name} at {adv.address}")
                                break

        # Subscribe to advertisements
        try:
            self._scan_subscription = aioesphomeapi.APIClient.subscribe_bluetooth_le_advertisements(
                api, handle_advertisement
            )
        except AttributeError:
            # Fallback for older aioesphomeapi versions
            self._scan_subscription = api.subscribe_bluetooth_le_advertisements(
                handle_advertisement
            )

        # Enable active scanning
        try:
            await api.bluetooth_scanner_set_mode(
                aioesphomeapi.BluetoothScannerMode.ACTIVE
            )
        except Exception as e:
            _LOGGER.warning(f"Could not set scanner mode: {e}")

        # Wait for advertisements
        await asyncio.sleep(timeout)

        # Clean up
        if self._scan_subscription:
            self._scan_subscription()
            self._scan_subscription = None

        return discovered_devices

    async def connect(self, device: BLEDevice) -> "ESPHomeTransportConnection":
        """Connect to a Casambi device via ESPHome."""
        api = await self._get_api()
        return ESPHomeTransportConnection(api, device.address)


class ESPHomeTransportConnection(TransportConnection):
    """Connection wrapper using ESPHome Bluetooth Proxy.

    Maps BLE operations to aioesphomeapi calls.
    """

    def __init__(self, api: APIClient, device_address: str):
        self._api = api
        self._device_address = device_address
        self._device_address_int = self._mac_to_int(device_address)
        self._is_connected = False
        self._services: Any | None = None  # Cached services
        self._notify_subscriptions: dict[int, tuple[Callable[[int, bytes], None], Callable[[], None]]] = {}
        self._logger = logging.getLogger(__name__)

    def _mac_to_int(self, mac: str) -> int:
        """Convert MAC address string to integer format used by ESPHome API."""
        # ESPHome expects MAC as integer (e.g., 0xAABBCCDDEEFF)
        # Remove colons/dashes and parse as hex
        clean_mac = mac.replace(":", "").replace("-", "").replace(" ", "")
        return int(clean_mac, 16)

    @property
    def is_connected(self) -> bool:
        """Check if connected to the BLE device."""
        return self._is_connected

    async def _ensure_connected(self) -> None:
        """Ensure the connection to the BLE device is established."""
        if not self._is_connected:
            await self._connect()

    async def _connect(self) -> None:
        """Establish connection to the BLE device."""
        connection_complete = asyncio.Event()

        def connection_callback(connected: bool, mtu: int, error: int) -> None:
            if connected:
                self._is_connected = True
                _LOGGER.debug(f"Connected to {self._device_address}, MTU={mtu}")
            else:
                self._is_connected = False
                _LOGGER.error(f"Connection failed to {self._device_address}, error={error}")
            connection_complete.set()

        try:
            # Connect with a timeout
            unsub = self._api.bluetooth_device_connect(
                self._device_address_int,
                connection_callback,
            )

            # Wait for connection to complete
            try:
                await asyncio.wait_for(connection_complete.wait(), timeout=30.0)
            except TimeoutError:
                unsub()
                raise BluetoothError(f"Timeout connecting to {self._device_address}")

            if not self._is_connected:
                unsub()
                raise BluetoothError(f"Failed to connect to {self._device_address}")

            # Store unsubscribe function for later
            self._connection_unsub = unsub

        except Exception as e:
            raise BluetoothError(f"ESPHome connection error: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from the BLE device."""
        if self._is_connected:
            try:
                await self._api.bluetooth_device_disconnect(
                    self._device_address_int,
                    timeout=10.0
                )
                self._is_connected = False
            except Exception as e:
                _LOGGER.error(f"Error disconnecting: {e}")

        # Clean up connection subscription
        if hasattr(self, '_connection_unsub'):
            self._connection_unsub()

        # Clean up notifications
        for _handle, (_callback, unsub) in list(self._notify_subscriptions.items()):
            unsub()
        self._notify_subscriptions.clear()

    async def read_gatt_char(self, char_uuid: str) -> bytes:
        """Read a GATT characteristic by UUID."""
        await self._ensure_connected()

        # Get services if not cached
        if self._services is None:
            self._services = await self._api.bluetooth_gatt_get_services(
                self._device_address_int
            )

        # Find the handle for this UUID
        handle = self._find_handle(char_uuid, is_characteristic=True)
        if handle is None:
            raise BluetoothError(f"Characteristic {char_uuid} not found")

        try:
            data = await self._api.bluetooth_gatt_read(
                self._device_address_int,
                handle,
                timeout=10.0,
            )
            return bytes(data)
        except Exception as e:
            raise BluetoothError(f"Failed to read characteristic {char_uuid}: {e}") from e

    async def write_gatt_char(self, char_uuid: str, data: bytes) -> None:
        """Write to a GATT characteristic by UUID."""
        await self._ensure_connected()

        # Get services if not cached
        if self._services is None:
            self._services = await self._api.bluetooth_gatt_get_services(
                self._device_address_int
            )

        # Find the handle for this UUID
        handle = self._find_handle(char_uuid, is_characteristic=True)
        if handle is None:
            raise BluetoothError(f"Characteristic {char_uuid} not found")

        try:
            await self._api.bluetooth_gatt_write(
                self._device_address_int,
                handle,
                data,
                response=True,
                timeout=10.0,
            )
        except Exception as e:
            raise BluetoothError(f"Failed to write characteristic {char_uuid}: {e}") from e

    async def start_notify(
        self, char_uuid: str, callback: Callable[[bytes], None]
    ) -> None:
        """Start notifications on a GATT characteristic."""
        await self._ensure_connected()

        # Get services if not cached
        if self._services is None:
            self._services = await self._api.bluetooth_gatt_get_services(
                self._device_address_int
            )

        # Find the handle for this UUID
        handle = self._find_handle(char_uuid, is_characteristic=True)
        if handle is None:
            raise BluetoothError(f"Characteristic {char_uuid} not found")

        # Define the notify callback
        def notify_handler(handle: int, data: bytearray) -> None:
            callback(bytes(data))

        # Start notification
        try:
            unsub_sync = self._api.bluetooth_gatt_start_notify(
                self._device_address_int,
                handle,
                notify_handler,
            )

            # For ESPHome, the unsubscribe is synchronous
            self._notify_subscriptions[handle] = (callback, unsub_sync)
        except Exception as e:
            raise BluetoothError(f"Failed to start notifications for {char_uuid}: {e}") from e

    async def stop_notify(self, char_uuid: str) -> None:
        """Stop notifications on a GATT characteristic."""
        if not self._is_connected:
            return

        # Get services if not cached
        if self._services is None:
            self._services = await self._api.bluetooth_gatt_get_services(
                self._device_address_int
            )

        # Find the handle for this UUID
        handle = self._find_handle(char_uuid, is_characteristic=True)
        if handle is None:
            return

        # Stop notification
        if handle in self._notify_subscriptions:
            callback, unsub = self._notify_subscriptions.pop(handle)
            try:
                unsub()
            except Exception as e:
                _LOGGER.warning(f"Error stopping notification: {e}")

    def _find_handle(self, uuid: str, is_characteristic: bool = True) -> int | None:
        """Find a GATT handle by UUID in cached services."""
        if self._services is None:
            return None

        # Convert UUID to integer format (ESPHome uses integer UUIDs)
        uuid_int = self._uuid_to_int(uuid)

        # Search through services and characteristics
        for service in self._services.services:
            if is_characteristic:
                for char in service.characteristics:
                    if char.uuid == uuid_int:
                        return char.handle
            else:
                for descriptor in service.descriptors:
                    if descriptor.uuid == uuid_int:
                        return descriptor.handle

        return None

    def _uuid_to_int(self, uuid: str) -> int:
        """Convert standard UUID string to ESPHome integer format."""
        # Remove hyphens and parse as hex
        clean_uuid = uuid.replace("-", "").lower()
        return int(clean_uuid, 16)
