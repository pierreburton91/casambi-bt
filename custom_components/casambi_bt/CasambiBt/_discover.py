# Modified by Pierre Burton (2026) from casambi-bt 0.3.2 by Lukas Kempf
# (https://github.com/lkempf/casambi-bt), Apache License 2.0.
# See NOTICE at the repository root for a summary of the changes.
import logging

from bleak.backends.device import BLEDevice

from ._transport import BluetoothTransport
from ._transport_factory import get_transport

_LOGGER = logging.getLogger(__name__)


async def discover(transport: BluetoothTransport | None = None) -> list[BLEDevice]:
    """Discover all Casambi networks in range.

    Uses the configured transport (ESPHome or bleak) based on environment.

    :param transport: Optional transport to use. If None, uses the default from environment.
    :return: A list of all discovered Casambi devices.
    :raises BluetoothError: Bluetooth isn't turned on or in a failed state.
    """
    # Use provided transport or get default
    actual_transport = transport or get_transport()
    return await actual_transport.discover(timeout=10.0)
