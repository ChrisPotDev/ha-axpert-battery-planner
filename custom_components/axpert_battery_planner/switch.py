"""Switch entities for Axpert Battery Planner."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NUM_SLOTS
from .coordinator import AxpertPlannerConfigEntry, AxpertPlannerCoordinator
from .entity import AxpertPlannerControlEntity, AxpertPlannerSlotEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AxpertPlannerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the master switch and per-slot switches."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [PlanEnabledSwitch(coordinator)]
    for index in range(NUM_SLOTS):
        entities.append(SlotActiveSwitch(coordinator, index))
        entities.append(SlotGridChargeSwitch(coordinator, index))
    async_add_entities(entities)


class PlanEnabledSwitch(AxpertPlannerControlEntity, SwitchEntity):
    """Master switch; off leaves the inverter untouched (bypass)."""

    _attr_translation_key = "plan_enabled"

    def __init__(self, coordinator: AxpertPlannerCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, "plan_enabled")

    @property
    def is_on(self) -> bool:
        """Return whether the plan is controlling the inverter."""
        return self.coordinator.plan_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the plan."""
        await self.coordinator.async_set_plan_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Bypass the plan."""
        await self.coordinator.async_set_plan_enabled(False)


class SlotActiveSwitch(AxpertPlannerSlotEntity, SwitchEntity):
    """Whether a slot takes part in the schedule."""

    _attr_translation_key = "slot_active"

    def __init__(self, coordinator: AxpertPlannerCoordinator, slot_index: int) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, slot_index, "active")

    @property
    def is_on(self) -> bool:
        """Return whether the slot is enabled."""
        return self.slot.active

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the slot."""
        await self.coordinator.async_update_slot(self._slot_index, active=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the slot."""
        await self.coordinator.async_update_slot(self._slot_index, active=False)


class SlotGridChargeSwitch(AxpertPlannerSlotEntity, SwitchEntity):
    """Whether a slot may charge the battery from the grid up to its target."""

    _attr_translation_key = "slot_grid_charge"

    def __init__(self, coordinator: AxpertPlannerCoordinator, slot_index: int) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, slot_index, "grid_charge")

    @property
    def is_on(self) -> bool:
        """Return whether grid charging is allowed in this slot."""
        return self.slot.grid_charge

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow grid charging."""
        await self.coordinator.async_update_slot(self._slot_index, grid_charge=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disallow grid charging."""
        await self.coordinator.async_update_slot(self._slot_index, grid_charge=False)
