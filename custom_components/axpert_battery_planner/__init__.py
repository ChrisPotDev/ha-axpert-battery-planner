"""Axpert Battery Planner: Sunsynk/Deye style SOC-based time slot scheduling."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import PLATFORMS, STORAGE_VERSION, storage_key
from .coordinator import AxpertPlannerConfigEntry, AxpertPlannerCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: AxpertPlannerConfigEntry) -> bool:
    """Set up Axpert Battery Planner from a config entry."""
    coordinator = AxpertPlannerCoordinator(hass, entry)
    await coordinator.async_load_plan()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AxpertPlannerConfigEntry) -> bool:
    """Unload a config entry, flushing any pending plan changes to disk."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_save_plan()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: AxpertPlannerConfigEntry) -> None:
    """Delete the stored plan when the integration is removed."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()


async def _async_update_listener(
    hass: HomeAssistant, entry: AxpertPlannerConfigEntry
) -> None:
    """Reload so new entities, mappings and timings take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
