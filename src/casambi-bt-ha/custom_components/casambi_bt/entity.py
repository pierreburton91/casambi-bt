"""Base entity for the Casambi Bluetooth integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from CasambiBt import Unit

from .const import DOMAIN, MANUFACTURER_DEFAULT
from .coordinator import CasambiBtCoordinator


class CasambiBtEntity(CoordinatorEntity[CasambiBtCoordinator]):
    """Base entity tracking one Casambi unit through the coordinator's push updates."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CasambiBtCoordinator, unit: Unit, unique_id_suffix: str
    ) -> None:
        super().__init__(coordinator)
        self._unit_uuid = unit.uuid
        # Not prefixed with the config entry id: unit.uuid is already globally
        # stable (assigned by Casambi per physical unit), so removing and
        # re-adding the same network keeps entity history/customizations.
        self._attr_unique_id = f"{unit.uuid}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unit.uuid)},
            name=unit.name,
            manufacturer=unit.unitType.manufacturer or MANUFACTURER_DEFAULT,
            model=unit.unitType.model,
            sw_version=unit.firmwareVersion,
            via_device=(DOMAIN, coordinator.entry.entry_id),
        )

    @property
    def _unit(self) -> Unit | None:
        return self.coordinator.data.get(self._unit_uuid)

    @property
    def available(self) -> bool:
        unit = self._unit
        return super().available and unit is not None and unit.online
