"""Slot start time entities for Axpert Battery Planner."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NUM_SLOTS
from .coordinator import AxpertPlannerConfigEntry, AxpertPlannerCoordinator
from .entity import AxpertPlannerSlotEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AxpertPlannerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up slot start time entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        SlotStartTimeEntity(coordinator, index) for index in range(NUM_SLOTS)
    )


class SlotStartTimeEntity(AxpertPlannerSlotEntity, TimeEntity):
    """Start time of a plan slot."""

    _attr_translation_key = "slot_start_time"

    def __init__(self, coordinator: AxpertPlannerCoordinator, slot_index: int) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, slot_index, "start_time")

    @property
    def native_value(self) -> time:
        """Return the slot start time."""
        return self.slot.start_time

    async def async_set_value(self, value: time) -> None:
        """Change the slot start time."""
        await self.coordinator.async_update_slot(self._slot_index, start_time=value)
