"""Binary sensor platform for the Casambi Bluetooth integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import _logic
from .CasambiBt import Unit
from .const import DOMAIN
from .coordinator import CasambiBtCoordinator
from .entity import CasambiBtEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensor entities for this config entry."""
    coordinator: CasambiBtCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        CasambiBtPresenceSensor(coordinator, unit)
        for unit in coordinator.data.values()
        if _logic.has_presence_control(unit.unitType)
    ]
    async_add_entities(entities)


class CasambiBtPresenceSensor(CasambiBtEntity, BinarySensorEntity):
    """Occupancy/presence from a unit's PRESENCE control."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: CasambiBtCoordinator, unit: Unit) -> None:
        super().__init__(coordinator, unit, "presence")
        self._attr_name = "Occupancy"

    @property
    def is_on(self) -> bool | None:
        unit = self._unit
        if unit is None or unit.state is None or unit.state.presence is None:
            return None
        return bool(unit.state.presence)
