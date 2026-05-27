"""Bluetooth transport abstraction layer.

Supports multiple transport backends:
- BleakTransport: Local Bluetooth using bleak library
- ESPHomeTransport: Remote Bluetooth via ESPHome Bluetooth Proxy
"""

from abc import ABC, abstractmethod
from collections.abc import Callable

from bleak.backends.device import BLEDevice


class TransportConnection(ABC):
    """Abstract base class for a BLE connection."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the connection is currently active."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the BLE device."""
        ...

    @abstractmethod
    async def read_gatt_char(self, char_uuid: str) -> bytes:
        """Read a GATT characteristic by UUID.

        :param char_uuid: The UUID of the characteristic to read.
        :return: The raw bytes read from the characteristic.
        """
        ...

    @abstractmethod
    async def write_gatt_char(self, char_uuid: str, data: bytes) -> None:
        """Write to a GATT characteristic by UUID.

        :param char_uuid: The UUID of the characteristic to write to.
        :param data: The raw bytes to write.
        """
        ...

    @abstractmethod
    async def start_notify(
        self,
        char_uuid: str,
        callback: Callable[[bytes], None],
    ) -> None:
        """Start notifications on a GATT characteristic.

        :param char_uuid: The UUID of the characteristic to enable notifications for.
        :param callback: Function to call when notification data is received.
                        The callback receives the raw notification data as bytes.
        """
        ...

    @abstractmethod
    async def stop_notify(self, char_uuid: str) -> None:
        """Stop notifications on a GATT characteristic.

        :param char_uuid: The UUID of the characteristic to disable notifications for.
        """
        ...


class BluetoothTransport(ABC):
    """Abstract base class for Bluetooth transport implementations."""

    @abstractmethod
    async def discover(self, timeout: float = 10.0) -> list[BLEDevice]:
        """Scan for Casambi BLE devices.

        :param timeout: Maximum time to scan in seconds.
        :return: A list of discovered Casambi BLEDevice objects.
        """
        ...

    @abstractmethod
    async def connect(self, device: BLEDevice) -> TransportConnection:
        """Connect to a BLE device and return a connection object.

        :param device: The BLEDevice to connect to.
        :return: A TransportConnection instance for the established connection.
        """
        ...
