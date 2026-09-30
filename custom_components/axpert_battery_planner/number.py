"""Slot target SOC entities for Axpert Battery Planner."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
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
    """Set up slot target SOC entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        SlotTargetSocEntity(coordinator, index) for index in range(NUM_SLOTS)
    )


class SlotTargetSocEntity(AxpertPlannerSlotEntity, NumberEntity):
    """Target SOC of a plan slot."""

    _attr_translation_key = "slot_target_soc"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: AxpertPlannerCoordinator, slot_index: int) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, slot_index, "target_soc")

    @property
    def native_value(self) -> int:
        """Return the slot target SOC."""
        return self.slot.target_soc

    async def async_set_native_value(self, value: float) -> None:
        """Change the slot target SOC."""
        await self.coordinator.async_update_slot(self._slot_index, target_soc=value)
