"""Top-level module for CasambiBt."""

# Import everything that should be public
# ruff: noqa: F401

from ._casambi import Casambi
from ._discover import discover
from ._transport import BluetoothTransport, TransportConnection
from ._transport_factory import get_transport
from ._unit import (
    ColorSource,
    DeviceRole,
    Group,
    Scene,
    Unit,
    UnitControl,
    UnitControlType,
    UnitState,
    UnitType,
)

# Optionally import transport implementations if available
try:
    from ._homeassistant_transport import (
        HomeAssistantTransport,
        HomeAssistantTransportConnection,
    )

    _HOME_ASSISTANT_AVAILABLE = True
except ImportError:
    _HOME_ASSISTANT_AVAILABLE = False

__all__ = [
    "Casambi",
    "discover",
    "BluetoothTransport",
    "TransportConnection",
    "get_transport",
    "ColorSource",
    "DeviceRole",
    "Group",
    "Scene",
    "Unit",
    "UnitControl",
    "UnitControlType",
    "UnitState",
    "UnitType",
]

if _HOME_ASSISTANT_AVAILABLE:
    __all__.extend(["HomeAssistantTransport", "HomeAssistantTransportConnection"])
