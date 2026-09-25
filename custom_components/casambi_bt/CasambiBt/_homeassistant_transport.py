"""Home Assistant transport implementation for Casambi BT.

This transport validates connectivity against a Home Assistant instance
(and optionally checks the liveness of one HA entity), then connects
directly to a given ESPHome Bluetooth Proxy device by wrapping
ESPHomeTransport. Home Assistant is never in the BLE data path: all GATT
traffic goes straight to the ESPHome device's native API, the same way
Home Assistant's own Bluetooth proxy integration works internally.

Note: Home Assistant's REST API exposes entity state, not device-registry
data (host/port/connections), so this transport cannot auto-discover an
ESPHome proxy's address from Home Assistant - the address must be supplied
explicitly via `esphome_host`/`esphome_port`.

Note: This transport requires the homeassistant-api library and access to
a Home Assistant instance.
"""

import logging
from collections.abc import Callable

from bleak.backends.device import BLEDevice

from ._esphome_transport import ESPHomeTransport, ESPHomeTransportConnection
from ._transport import BluetoothTransport, TransportConnection
from .errors import BluetoothError

try:
    from homeassistant_api import AsyncClient
    from homeassistant_api.errors import HomeassistantAPIError

    HA_API_AVAILABLE = True
except ImportError:
    HA_API_AVAILABLE = False
    AsyncClient = None  # type: ignore[misc, assignment]
    HomeassistantAPIError = Exception  # type: ignore[misc, assignment]

_LOGGER = logging.getLogger(__name__)


class HomeAssistantTransport(BluetoothTransport):
    """Transport that validates against Home Assistant, then connects directly to an ESPHome Bluetooth Proxy device.

    Home Assistant is used only to validate connectivity/credentials (a bad
    host/token fails fast with a clear error) and, if `esphome_entity` is
    given, to do a best-effort liveness check on that entity. All BLE
    traffic is sent directly to `esphome_host`/`esphome_port` via
    ESPHomeTransport - Home Assistant's REST API cannot verify that an
    entity actually belongs to that device, so the check is a hint, not a
    guarantee.

    :param host: Home Assistant server hostname or IP address
    :param esphome_host: Hostname or IP address of the ESPHome Bluetooth Proxy device
    :param port: Home Assistant server port (default: 8123)
    :param esphome_port: ESPHome native API port (default: 6053)
    :param token: Home Assistant long-lived access token
    :param ssl: Whether to use HTTPS (default: True)
    :param verify_ssl: Whether to verify SSL certificates (default: True). Set to False for self-signed certificates.
    :param esphome_entity: Optional Home Assistant entity ID to use as a liveness hint
    :param noise_psk: Optional noise PSK for the ESPHome connection
    """

    def __init__(
        self,
        host: str,
        esphome_host: str,
        port: int = 8123,
        esphome_port: int = 6053,
        token: str | None = None,
        ssl: bool = True,
        verify_ssl: bool = True,
        esphome_entity: str | None = None,
        noise_psk: str | None = None,
    ):
        if not HA_API_AVAILABLE:
            raise ImportError(
                "homeassistant-api is required for Home Assistant transport. "
                "Install it with: pip install homeassistant-api"
            )

        self._host = host
        self._esphome_host = esphome_host
        self._port = port
        self._esphome_port = esphome_port
        self._token = token
        self._ssl = ssl
        self._verify_ssl = verify_ssl
        self._esphome_entity = esphome_entity
        self._noise_psk = noise_psk
        self._api: AsyncClient | None = None
        self._esphome_transport: ESPHomeTransport | None = None

    async def _get_api(self) -> AsyncClient:
        """Get or create the Home Assistant API client."""
        if self._api is None:
            # Strip any leading scheme (http://, https://) from host
            host = self._host
            for scheme in ("https://", "http://"):
                if host.startswith(scheme):
                    host = host[len(scheme) :]
                    break
            host = host.strip("/")

            if ":" in host and host.rfind(":") > host.rfind("/"):
                host_part, port_part = host.rsplit(":", 1)
                if port_part.isdigit():
                    host = host_part
                    port = int(port_part)
                else:
                    port = self._port
            else:
                port = self._port

            url = f"{'https' if self._ssl else 'http'}://{host}:{port}/api"
            api = AsyncClient(url, self._token, verify_ssl=self._verify_ssl)
            try:
                await api.get_states()
                _LOGGER.debug(f"Connected to Home Assistant at {url}")
            except HomeassistantAPIError as e:
                raise BluetoothError(f"Failed to connect to Home Assistant: {e}") from e
            self._api = api
        return self._api

    async def _check_esphome_entity_health(self) -> None:
        """Best-effort warning if the configured HA entity looks unavailable.

        Home Assistant's REST API cannot confirm that this entity actually
        belongs to `esphome_host`, so this is a liveness hint only and never
        raises.
        """
        try:
            api = await self._get_api()
            state = await api.get_state(entity_id=self._esphome_entity)
            if state is not None and getattr(state, "state", None) in (
                "unavailable",
                "unknown",
            ):
                _LOGGER.warning(
                    f"Home Assistant reports entity '{self._esphome_entity}' as "
                    f"'{state.state}' - the ESP32 Bluetooth proxy may be offline."
                )
        except HomeassistantAPIError as e:
            _LOGGER.warning(
                f"Could not check health of Home Assistant entity "
                f"'{self._esphome_entity}': {e}. Continuing anyway."
            )

    async def _get_esphome_transport(self) -> ESPHomeTransport:
        """Validate Home Assistant connectivity, then build the direct ESPHome transport."""
        if self._esphome_transport is None:
            await self._get_api()  # fail fast on bad HA host/token

            if self._esphome_entity:
                await self._check_esphome_entity_health()

            _LOGGER.info(
                f"Using ESPHome Bluetooth Proxy at {self._esphome_host}:{self._esphome_port} "
                f"(Home Assistant at {self._host}:{self._port} used for validation only)"
            )
            self._esphome_transport = ESPHomeTransport(
                host=self._esphome_host,
                port=self._esphome_port,
                noise_psk=self._noise_psk,
            )

        return self._esphome_transport

    async def discover(self, timeout: float = 10.0) -> list[BLEDevice]:
        """Scan for Casambi devices via the configured ESPHome proxy.

        :param timeout: Maximum time to scan in seconds
        :return: List of discovered Casambi BLEDevice objects
        """
        _LOGGER.debug(f"Starting discovery with Home Assistant transport, timeout={timeout}s")

        try:
            esphome_transport = await self._get_esphome_transport()
            devices = await esphome_transport.discover(timeout=timeout)
            _LOGGER.debug(f"Discovered {len(devices)} Casambi device(s)")
            return devices
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"Discovery failed: {e}") from e

    async def connect(self, device: BLEDevice) -> "HomeAssistantTransportConnection":
        """Connect to a Casambi device via the configured ESPHome proxy.

        :param device: The BLEDevice to connect to
        :return: A HomeAssistantTransportConnection instance
        """
        _LOGGER.debug(f"Connecting to device {device.address} via Home Assistant transport")

        try:
            esphome_transport = await self._get_esphome_transport()
            connection = await esphome_transport.connect(device)
            return HomeAssistantTransportConnection(connection, self)
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"Connection failed: {e}") from e


class HomeAssistantTransportConnection(TransportConnection):
    """Connection wrapper for Home Assistant transport."""

    def __init__(
        self,
        esphome_connection: ESPHomeTransportConnection,
        transport: HomeAssistantTransport,
    ):
        self._esphome_connection = esphome_connection
        self._transport = transport
        self._logger = logging.getLogger(__name__)

    @property
    def is_connected(self) -> bool:
        return self._esphome_connection.is_connected

    async def disconnect(self) -> None:
        try:
            await self._esphome_connection.disconnect()
            self._logger.debug("Disconnected from device via Home Assistant transport")
        except Exception as e:
            self._logger.error(f"Error disconnecting: {e}")
            raise BluetoothError(f"Disconnect failed: {e}") from e

    async def read_gatt_char(self, char_uuid: str) -> bytes:
        try:
            return await self._esphome_connection.read_gatt_char(char_uuid)
        except Exception as e:
            raise BluetoothError(f"Failed to read characteristic {char_uuid}: {e}") from e

    async def write_gatt_char(self, char_uuid: str, data: bytes) -> None:
        try:
            await self._esphome_connection.write_gatt_char(char_uuid, data)
        except Exception as e:
            raise BluetoothError(f"Failed to write characteristic {char_uuid}: {e}") from e

    async def start_notify(self, char_uuid: str, callback: Callable[[bytes], None]) -> None:
        try:
            await self._esphome_connection.start_notify(char_uuid, callback)
        except Exception as e:
            raise BluetoothError(f"Failed to start notifications for {char_uuid}: {e}") from e

    async def stop_notify(self, char_uuid: str) -> None:
        try:
            await self._esphome_connection.stop_notify(char_uuid)
        except Exception as e:
            self._logger.warning(f"Error stopping notifications: {e}")
