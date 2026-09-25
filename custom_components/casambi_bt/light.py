"""Light platform for the Casambi Bluetooth integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import _logic
from .CasambiBt import DeviceRole, Unit, UnitControlType
from .const import DOMAIN
from .coordinator import CasambiBtCoordinator
from .entity import CasambiBtEntity

_MODE_KEY_TO_HA = {
    "color_temp": ColorMode.COLOR_TEMP,
    "rgb": ColorMode.RGB,
    "xy": ColorMode.XY,
    "brightness": ColorMode.BRIGHTNESS,
    "onoff": ColorMode.ONOFF,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up light entities for this config entry."""
    coordinator: CasambiBtCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        CasambiBtLight(coordinator, unit)
        for unit in coordinator.data.values()
        if unit.unitType.device_role == DeviceRole.LIGHT
    ]
    async_add_entities(entities)


class CasambiBtLight(CasambiBtEntity, LightEntity):
    """A Casambi light unit."""

    def __init__(self, coordinator: CasambiBtCoordinator, unit: Unit) -> None:
        super().__init__(coordinator, unit, "light")
        self._attr_name = None

        mode_keys = _logic.supported_light_color_modes(unit.unitType)
        self._attr_supported_color_modes = {_MODE_KEY_TO_HA[key] for key in mode_keys}

        temp_control = unit.unitType.get_control(UnitControlType.TEMPERATURE)
        if temp_control is not None:
            if temp_control.min is not None:
                self._attr_min_color_temp_kelvin = temp_control.min
            if temp_control.max is not None:
                self._attr_max_color_temp_kelvin = temp_control.max

    @property
    def is_on(self) -> bool | None:
        unit = self._unit
        return unit.is_on if unit is not None else None

    @property
    def brightness(self) -> int | None:
        unit = self._unit
        if unit is None or unit.state is None:
            return None
        return unit.state.dimmer

    @property
    def color_mode(self) -> ColorMode | None:
        modes = self._attr_supported_color_modes or set()
        mode_keys = {
            key for key, ha_mode in _MODE_KEY_TO_HA.items() if ha_mode in modes
        }
        unit = self._unit
        colorsource = (
            unit.state.colorsource
            if unit is not None and unit.state is not None
            else None
        )
        active_key = _logic.active_light_color_mode(mode_keys, colorsource)
        return _MODE_KEY_TO_HA.get(active_key) if active_key else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        unit = self._unit
        if self.color_mode != ColorMode.RGB or unit is None or unit.state is None:
            return None
        return unit.state.rgb

    @property
    def xy_color(self) -> tuple[float, float] | None:
        unit = self._unit
        if self.color_mode != ColorMode.XY or unit is None or unit.state is None:
            return None
        return unit.state.xy

    @property
    def color_temp_kelvin(self) -> int | None:
        unit = self._unit
        if (
            self.color_mode != ColorMode.COLOR_TEMP
            or unit is None
            or unit.state is None
        ):
            return None
        return unit.state.temperature

    async def async_turn_on(self, **kwargs: Any) -> None:
        unit = self._unit
        if unit is None:
            return
        sent = False
        if ATTR_BRIGHTNESS in kwargs:
            await self.coordinator.async_set_control(
                unit, UnitControlType.DIMMER, kwargs[ATTR_BRIGHTNESS]
            )
            sent = True
        if ATTR_RGB_COLOR in kwargs:
            await self.coordinator.async_set_control(
                unit, UnitControlType.RGB, kwargs[ATTR_RGB_COLOR]
            )
            sent = True
        if ATTR_XY_COLOR in kwargs:
            await self.coordinator.async_set_control(
                unit, UnitControlType.XY, tuple(kwargs[ATTR_XY_COLOR])
            )
            sent = True
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.coordinator.async_set_control(
                unit, UnitControlType.TEMPERATURE, kwargs[ATTR_COLOR_TEMP_KELVIN]
            )
            sent = True
        if not sent:
            await self.coordinator.async_set_control(unit, UnitControlType.ONOFF, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        unit = self._unit
        if unit is None:
            return
        await self.coordinator.async_set_control(unit, UnitControlType.ONOFF, 0)
