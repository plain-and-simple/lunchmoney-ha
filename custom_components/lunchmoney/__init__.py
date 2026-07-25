"""The Lunch Money integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import LunchMoneyConfigEntry, LunchMoneyCoordinator

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: LunchMoneyConfigEntry) -> bool:
    """Set up one Lunch Money budget from a config entry."""
    coordinator = LunchMoneyCoordinator(hass, entry)

    # Fail setup loudly if the very first fetch does not work, so the user sees
    # the problem immediately rather than a set of entities stuck at unknown.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: LunchMoneyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: LunchMoneyConfigEntry) -> None:
    """Reload when options change, so a new interval takes effect at once."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: LunchMoneyConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow deleting the device for an account Lunch Money no longer returns.

    Entities for a vanished account go unavailable rather than disappearing, so
    that a temporary API hiccup never destroys a user's history. That leaves a
    genuinely closed account sitting in the UI forever, so this gives the user a
    delete button — but only for accounts that really are gone.
    """
    coordinator = entry.runtime_data
    prefix = f"{entry.entry_id}_"

    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        # The hub device holds the totals and must live as long as the entry.
        if identifier == entry.entry_id:
            return False
        if identifier.startswith(prefix):
            account_key = identifier.removeprefix(prefix)
            if account_key in (coordinator.data or {}):
                return False

    return True
