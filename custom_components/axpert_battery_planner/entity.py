"""Base entities for Axpert Battery Planner."""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import AxpertPlannerCoordinator
from .planner import PlanSlot


class AxpertPlannerEntity(CoordinatorEntity[AxpertPlannerCoordinator]):
    """Common base: one service device per config entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AxpertPlannerCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )


class AxpertPlannerControlEntity(AxpertPlannerEntity):
    """Entity holding plan configuration: always available, even if evaluation fails."""

    @property
    def available(self) -> bool:
        """Plan settings can always be edited."""
        return True


class AxpertPlannerSlotEntity(AxpertPlannerControlEntity):
    """Entity bound to one of the six plan slots."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: AxpertPlannerCoordinator, slot_index: int, key: str
    ) -> None:
        """Initialise the slot entity."""
        super().__init__(coordinator, f"slot{slot_index + 1}_{key}")
        self._slot_index = slot_index
        self._attr_translation_placeholders = {"slot": str(slot_index + 1)}

    @property
    def slot(self) -> PlanSlot:
        """The slot this entity edits."""
        return self.coordinator.slots[self._slot_index]
