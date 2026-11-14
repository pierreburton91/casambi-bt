"""How CasambiBtCoordinator.async_setup maps connection failures for HA.

`homeassistant` isn't installed here, so the handful of HA names coordinator.py
imports are stubbed in sys.modules for the duration of each test. What matters
is the contract with HA's config entry setup: a transient failure must raise
ConfigEntryNotReady (HA retries) rather than escape (HA gives up with
setup_error), and a wrong password must raise ConfigEntryAuthFailed.
"""

import asyncio
import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Generic, TypeVar

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from custom_components.casambi_bt.CasambiBt.errors import (
    AuthenticationError,
    NetworkUpdateError,
)

_ADDRESS = "5F:5F:16:64:F5:20"
_INTEGRATION_MODULES = (
    "custom_components.casambi_bt.const",
    "custom_components.casambi_bt.coordinator",
)

_T = TypeVar("_T")


class _ConfigEntryNotReady(Exception):
    pass


class _ConfigEntryAuthFailed(Exception):
    pass


class _HomeAssistantError(Exception):
    pass


class _DataUpdateCoordinator(Generic[_T]):
    def __init__(self, hass: Any, logger: Any, **kwargs: Any) -> None:
        self.hass = hass
        self.last_update_success = False


def _module(name: str, **attrs: Any) -> ModuleType:
    module = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    return module


def _ha_stubs() -> dict[str, ModuleType]:
    bluetooth = _module(
        "homeassistant.components.bluetooth",
        async_ble_device_from_address=lambda hass, address, connectable: BLEDevice(
            address, None, {}
        ),
    )
    return {
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module(
            "homeassistant.components", bluetooth=bluetooth
        ),
        "homeassistant.components.bluetooth": bluetooth,
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.const": _module(
            "homeassistant.const",
            CONF_ADDRESS="address",
            CONF_PASSWORD="password",
            Platform=SimpleNamespace(
                LIGHT="light",
                COVER="cover",
                SENSOR="sensor",
                BINARY_SENSOR="binary_sensor",
            ),
        ),
        "homeassistant.core": _module("homeassistant.core", HomeAssistant=object),
        "homeassistant.exceptions": _module(
            "homeassistant.exceptions",
            ConfigEntryAuthFailed=_ConfigEntryAuthFailed,
            ConfigEntryNotReady=_ConfigEntryNotReady,
            HomeAssistantError=_HomeAssistantError,
        ),
        "homeassistant.helpers": _module("homeassistant.helpers"),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=_DataUpdateCoordinator,
        ),
    }


@pytest.fixture
def coordinator_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    for name, module in _ha_stubs().items():
        monkeypatch.setitem(sys.modules, name, module)
    for name in _INTEGRATION_MODULES:
        sys.modules.pop(name, None)
    try:
        yield importlib.import_module("custom_components.casambi_bt.coordinator")
    finally:
        # Don't leave modules bound to the HA stubs behind for other tests.
        for name in _INTEGRATION_MODULES:
            sys.modules.pop(name, None)


def _setup_with_connect_error(
    coordinator_module: ModuleType, tmp_path: Path, error: Exception
) -> None:
    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts)))
    )
    entry = SimpleNamespace(
        entry_id="entry", data={"address": _ADDRESS, "password": "secret"}
    )
    coordinator = coordinator_module.CasambiBtCoordinator(hass, entry)

    async def failing_connect(*args: Any, **kwargs: Any) -> None:
        raise error

    coordinator.casambi.connect = failing_connect
    asyncio.run(coordinator.async_setup())


@pytest.mark.parametrize(
    "error",
    [
        # What HA's ESPHome proxy path raised on 2026-11-14 for a weak link.
        BleakError("Bluetooth GATT Error address=5F:5F:16:64:F5:20 handle=9 error=133"),
        # Casambi cloud answering 500 while refreshing the network.
        NetworkUpdateError("Could not update network!"),
        TimeoutError(),
    ],
    ids=["bleak-gatt-error", "network-update-error", "timeout"],
)
def test_transient_failure_is_not_ready(
    coordinator_module: ModuleType, tmp_path: Path, error: Exception
) -> None:
    with pytest.raises(_ConfigEntryNotReady):
        _setup_with_connect_error(coordinator_module, tmp_path, error)


def test_wrong_password_starts_reauth(
    coordinator_module: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(_ConfigEntryAuthFailed):
        _setup_with_connect_error(
            coordinator_module, tmp_path, AuthenticationError("Login failed")
        )
