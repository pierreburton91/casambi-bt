"""Cover platform for the Casambi Bluetooth integration."""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import _logic
from .CasambiBt import DeviceRole, Unit, UnitState
from .const import DOMAIN
from .coordinator import CasambiBtCoordinator
from .entity import CasambiBtEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up cover entities for this config entry."""
    coordinator: CasambiBtCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for unit in coordinator.data.values():
        if unit.unitType.device_role not in (
            DeviceRole.MOTORIZED_SHADE,
            DeviceRole.MOTORIZED_SCREEN,
        ):
            continue
        if _logic.resolve_position_control(unit.unitType) is None:
            continue
        entities.append(CasambiBtCover(coordinator, unit))
    async_add_entities(entities)


class CasambiBtCover(CasambiBtEntity, CoverEntity):
    """A Casambi motorized shade or screen.

    No "stop" support - there is no known protocol opcode for it, so it isn't
    guessed at.
    """

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator: CasambiBtCoordinator, unit: Unit) -> None:
        super().__init__(coordinator, unit, "cover")
        self._attr_name = None
        position = _logic.resolve_position_control(unit.unitType)
        assert position is not None
        self._field = position.field
        self._native_min = position.native_min
        self._native_max = position.native_max

    @property
    def current_cover_position(self) -> int | None:
        unit = self._unit
        if unit is None or unit.state is None:
            return None
        raw = unit.state.slider if self._field == "slider" else unit.state.dimmer
        if raw is None:
            return None
        return _logic.native_to_percent(raw, self._native_min, self._native_max)

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return position == 0 if position is not None else None

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        unit = self._unit
        if unit is None:
            return
        percent = kwargs[ATTR_POSITION]
        native = _logic.percent_to_native(percent, self._native_min, self._native_max)
        # Copy the existing state (rather than a fresh UnitState()) so we don't
        # clobber the on/off bit packed into the same state blob - mirrors how
        # the library itself handles setControl(ONOFF, ...) on these fixtures.
        state = copy.copy(unit.state) if unit.state is not None else UnitState()
        if self._field == "slider":
            state.slider = native
        else:
            state.dimmer = native
        await self.coordinator.async_set_unit_state(unit, state)

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.async_set_cover_position(**{ATTR_POSITION: 100})

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.async_set_cover_position(**{ATTR_POSITION: 0})
