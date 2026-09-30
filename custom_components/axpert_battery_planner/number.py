"""Slot target SOC entities for Axpert Battery Planner."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MAX_SLOT_CHARGE_CURRENT, NUM_SLOTS
from .coordinator import AxpertPlannerConfigEntry, AxpertPlannerCoordinator
from .entity import AxpertPlannerSlotEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AxpertPlannerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up slot target SOC and charge current entities."""
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = []
    for index in range(NUM_SLOTS):
        entities.append(SlotTargetSocEntity(coordinator, index))
        entities.append(SlotChargeCurrentEntity(coordinator, index))
    async_add_entities(entities)


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


class SlotChargeCurrentEntity(AxpertPlannerSlotEntity, NumberEntity):
    """Grid charge current of a plan slot; 0 uses the global setting."""

    _attr_translation_key = "slot_charge_current"
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_SLOT_CHARGE_CURRENT
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: AxpertPlannerCoordinator, slot_index: int) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, slot_index, "charge_current")

    @property
    def native_value(self) -> int:
        """Return the slot charge current."""
        return self.slot.charge_current

    async def async_set_native_value(self, value: float) -> None:
        """Change the slot charge current."""
        await self.coordinator.async_update_slot(self._slot_index, charge_current=value)
