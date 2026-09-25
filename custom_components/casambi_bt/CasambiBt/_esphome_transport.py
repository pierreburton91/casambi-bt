"""ESPHome Bluetooth Proxy transport implementation.

Uses aioesphomeapi to perform BLE operations through an ESP32
running ESPHome with the bluetooth_proxy component.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from bleak.backends.device import BLEDevice

from ._constants import CASA_UUID
from ._transport import BluetoothTransport, TransportConnection
from .errors import BluetoothError

_LOGGER = logging.getLogger(__name__)

# Try to import aioesphomeapi, but make it optional
try:
    import aioesphomeapi
    from aioesphomeapi import BluetoothLERawAdvertisementsResponse
    from aioesphomeapi.client import APIClient

    ESPHOME_AVAILABLE = True
except ImportError:
    ESPHOME_AVAILABLE = False
    APIClient = None  # type: ignore[misc, assignment]
    BluetoothLERawAdvertisementsResponse = None


def _int_to_mac(address: int) -> str:
    """Convert an ESPHome integer BLE address to a colon-separated MAC string."""
    return ":".join(f"{b:02X}" for b in address.to_bytes(6, "big"))


def _extract_network_address(manufacturer_payload: bytes) -> str | None:
    """Extract a mesh's persistent network address from its Casambi manufacturer data.

    Any unit in a Casambi mesh can advertise on the network's behalf under its
    own outer BLE address, but embeds the mesh's fixed identity - the one
    Casambi's cloud API keys network lookups on - at a fixed offset in the
    manufacturer data payload. Returns None if the payload is too short to
    contain that field (e.g. an unrecognized/older advertisement format).
    """
    if len(manufacturer_payload) < 18:
        return None
    return ":".join(f"{b:02X}" for b in manufacturer_payload[12:18])


def _parse_ad_structures(data: bytes) -> tuple[list[str], dict[int, bytes]]:
    """Parse raw BLE advertisement payload into service UUIDs and manufacturer data.

    ESPHome's raw advertisement mode hands over the undecoded BLE AD structures
    (a sequence of [length][type][payload]) instead of pre-parsed fields, so this
    mirrors the subset of decoding CasambiBt actually needs (service UUIDs and
    manufacturer data) to identify Casambi devices.
    """
    service_uuids: list[str] = []
    manufacturer_data: dict[int, bytes] = {}
    i = 0
    while i < len(data):
        length = data[i]
        if length == 0 or i + 1 + length > len(data):
            break
        ad_type = data[i + 1]
        payload = data[i + 2 : i + 1 + length]
        if ad_type in (0x02, 0x03):  # 16-bit service UUIDs
            for j in range(0, len(payload) - 1, 2):
                uuid16 = int.from_bytes(payload[j : j + 2], "little")
                service_uuids.append(f"0000{uuid16:04x}-0000-1000-8000-00805f9b34fb")
        elif ad_type in (0x06, 0x07):  # 128-bit service UUIDs
            for j in range(0, len(payload) - 15, 16):
                service_uuids.append(str(UUID(bytes=payload[j : j + 16][::-1])))
        elif ad_type == 0xFF and len(payload) >= 2:  # manufacturer specific data
            company_id = int.from_bytes(payload[0:2], "little")
            manufacturer_data[company_id] = bytes(payload[2:])
        i += 1 + length
    return service_uuids, manufacturer_data


class ESPHomeTransport(BluetoothTransport):
    """Transport implementation using ESPHome Bluetooth Proxy.

    Connects to an ESPHome device over the network and uses it
    as a BLE passthrough proxy.
    """

    def __init__(
        self,
        host: str,
        port: int = 6053,
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
        self._password = password
        self._noise_psk = noise_psk
        self._api: APIClient | None = None
        self._scan_subscription: Callable[[], None] | None = None

    async def _get_api(self) -> APIClient:
        """Get or create the API client connection."""
        _LOGGER.debug(f"Getting API client for host={self._host}, port={self._port}")
        if self._api is None or not self._api.is_connected:
            _LOGGER.debug("Creating new API client connection")
            self._api = APIClient(
                self._host,
                self._port,
                password=self._password,
                noise_psk=self._noise_psk,
            )
            try:
                _LOGGER.debug(f"Connecting to ESPHome at {self._host}:{self._port}")
                await self._api.connect()
                _LOGGER.debug("Successfully connected to ESPHome")
            except Exception as e:
                raise BluetoothError(f"Failed to connect to ESPHome at {self._host}:{self._port}: {e}") from e
        else:
            _LOGGER.debug("Reusing existing API client connection")
        return self._api

    async def discover(self, timeout: float = 10.0) -> list[BLEDevice]:
        """Scan for Casambi devices via ESPHome Bluetooth Proxy."""
        _LOGGER.debug(f"Starting discovery with timeout={timeout}s")
        api = await self._get_api()

        # Keyed by network address (falling back to outer address if the
        # manufacturer data doesn't carry one) so that multiple relay units
        # belonging to the same mesh collapse into a single discovered entry.
        discovered_devices: dict[str, BLEDevice] = {}
        advertisement_count = 0  # Track total advertisements for debugging
        _LOGGER.debug("Initializing advertisement handler")

        def handle_raw_advertisements(
            response: BluetoothLERawAdvertisementsResponse,
        ) -> None:
            """Handle a batch of raw BLE advertisements from ESPHome."""
            nonlocal advertisement_count
            for adv in response.advertisements:
                advertisement_count += 1
                service_uuids, manufacturer_data = _parse_ad_structures(bytes(adv.data))
                _LOGGER.debug(
                    f"RECEIVED ADVERTISEMENT: address={adv.address}, rssi={adv.rssi}, "
                    f"service_uuids={service_uuids}, manufacturer_ids={list(manufacturer_data.keys())}"
                )

                # Check for Casambi devices: either service UUID or manufacturer data 963
                is_casambi = CASA_UUID.lower() in [u.lower() for u in service_uuids] or 963 in manufacturer_data

                if is_casambi:
                    address = _int_to_mac(adv.address)
                    network_address = _extract_network_address(manufacturer_data.get(963, b""))
                    key = network_address or address
                    if key not in discovered_devices:
                        discovered_devices[key] = BLEDevice(
                            address=address,
                            name="Casambi Network",
                            details={"network_address": network_address} if network_address else {},
                            rssi=adv.rssi,
                        )
                        _LOGGER.debug(
                            f"  => CASAMBI DEVICE ADDED to results: {address} "
                            f"(network_address={network_address})"
                        )

        # Subscribe to raw advertisements (this ESP32 firmware only emits the
        # raw batched format, not the legacy per-advertisement decoded one)
        _LOGGER.debug("Subscribing to raw BLE advertisements")
        self._scan_subscription = api.subscribe_bluetooth_le_raw_advertisements(
            handle_raw_advertisements
        )
        _LOGGER.debug("Advertisement subscription active")

        # Enable active scanning
        try:
            _LOGGER.debug("Setting scanner mode to ACTIVE")
            api.bluetooth_scanner_set_mode(
                aioesphomeapi.BluetoothScannerMode.ACTIVE
            )
            _LOGGER.debug("Scanner mode set successfully")
        except Exception as e:
            _LOGGER.warning(f"Could not set scanner mode: {e}")

        # Wait for advertisements
        _LOGGER.debug(f"Waiting {timeout}s for advertisements...")
        await asyncio.sleep(timeout)
        _LOGGER.debug(f"Scan complete. Received {advertisement_count} advertisement(s), {len(discovered_devices)} Casambi device(s) found")

        # Clean up
        if self._scan_subscription:
            _LOGGER.debug("Unsubscribing from advertisements")
            self._scan_subscription()
            self._scan_subscription = None

        return list(discovered_devices.values())

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
