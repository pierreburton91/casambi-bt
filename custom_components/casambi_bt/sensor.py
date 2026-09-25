"""Sensor platform for the Casambi Bluetooth integration."""

from __future__ import annotations

import re

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import LIGHT_LUX
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from CasambiBt import Unit, UnitControl

from . import _logic
from .const import DOMAIN
from .coordinator import CasambiBtCoordinator
from .entity import CasambiBtEntity

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return slug or "sensor"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities for this config entry.

    Scans every unit's controls regardless of its DeviceRole: a motorized
    shade/screen unit can carry tagged sensor controls alongside its
    SLIDER/DIMMER+ONOFF controls (see louvers.json/screen.json), so a unit that
    also gets a cover entity can still get sensor entities here.
    """
    coordinator: CasambiBtCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for unit in coordinator.data.values():
        if _logic.has_lux_control(unit.unitType):
            entities.append(CasambiBtLuxSensor(coordinator, unit))
        for control in _logic.has_tagged_sensor_controls(unit.unitType):
            entities.append(CasambiBtTaggedSensor(coordinator, unit, control))
        for control in _logic.has_plain_sensor_controls(unit.unitType):
            entities.append(CasambiBtPlainSensor(coordinator, unit, control))
    async_add_entities(entities)


class CasambiBtLuxSensor(CasambiBtEntity, SensorEntity):
    """Ambient light level from a unit's LUX control."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: CasambiBtCoordinator, unit: Unit) -> None:
        super().__init__(coordinator, unit, "lux")
        self._attr_name = "Illuminance"

    @property
    def native_value(self) -> int | None:
        unit = self._unit
        return unit.state.lux if unit is not None and unit.state is not None else None


class CasambiBtTaggedSensor(CasambiBtEntity, SensorEntity):
    """One named reading from a unit's round-robin tagged sensor group.

    An unchanged value across updates is expected (only one tag refreshes per
    update, round-robin), not a sign of a stale/unavailable sensor.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: CasambiBtCoordinator, unit: Unit, control: UnitControl
    ) -> None:
        display_name = control.name or f"Sensor {control.tag}"
        super().__init__(coordinator, unit, f"sensor_{_slugify(display_name)}")
        self._attr_name = display_name
        self._control_name = control.name
        if control.unit:
            self._attr_native_unit_of_measurement = control.unit

    @property
    def native_value(self) -> int | None:
        unit = self._unit
        if unit is None or unit.state is None:
            return None
        return unit.state.sensors.get(self._control_name)


class CasambiBtPlainSensor(CasambiBtEntity, SensorEntity):
    """A single ungrouped SENSOR control, decoded onto UnitState.sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: CasambiBtCoordinator, unit: Unit, control: UnitControl
    ) -> None:
        display_name = control.name or "Sensor"
        super().__init__(coordinator, unit, f"sensor_{_slugify(display_name)}")
        self._attr_name = display_name
        if control.unit:
            self._attr_native_unit_of_measurement = control.unit

    @property
    def native_value(self) -> int | None:
        unit = self._unit
        return (
            unit.state.sensor if unit is not None and unit.state is not None else None
        )
