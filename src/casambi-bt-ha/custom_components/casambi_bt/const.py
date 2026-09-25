"""Constants for the Casambi Bluetooth integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "casambi_bt"

PLATFORMS: Final = [
    Platform.LIGHT,
    Platform.COVER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

MANUFACTURER_DEFAULT: Final = "Casambi"

# Matches CASA_UUID in CasambiBt._bleak_transport - what the library's own
# discover() filters advertisements on.
CASAMBI_SERVICE_UUID: Final = "0000fe4d-0000-1000-8000-00805f9b34fb"

# CasambiBt has no internal timeout on BLE protocol operations (ROADMAP item 5) -
# every call into it from this integration must be bounded on our side.
CONNECT_TIMEOUT: Final = 30
OPERATION_TIMEOUT: Final = 10

RECONNECT_INITIAL_DELAY: Final = 5
RECONNECT_MAX_DELAY: Final = 300
RECONNECT_BACKOFF_FACTOR: Final = 2
