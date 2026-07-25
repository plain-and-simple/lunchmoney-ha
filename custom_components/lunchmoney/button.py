"""A button to pull fresh balances from the user's banks on demand."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FETCH_TOO_EARLY, LunchMoneyError
from .coordinator import LunchMoneyConfigEntry, LunchMoneyCoordinator
from .entity import LunchMoneyHubEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LunchMoneyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the refresh button."""
    async_add_entities([LunchMoneyRefreshButton(entry.runtime_data)])


class LunchMoneyRefreshButton(LunchMoneyHubEntity, ButtonEntity):
    """Ask Lunch Money to fetch new data from every linked bank.

    Normal polling only re-reads what Lunch Money already has. This asks Lunch
    Money itself to go back out to the banks, which is what you want before
    checking a balance you just changed in the real world.
    """

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:bank-transfer"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LunchMoneyCoordinator) -> None:
        """Initialise the button."""
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        """Queue a bank fetch and pick up whatever is ready now."""
        try:
            result = await self.coordinator.api.async_trigger_plaid_fetch()
        except LunchMoneyError as err:
            raise HomeAssistantError(
                f"Lunch Money could not start a refresh: {err}"
            ) from err

        if result == FETCH_TOO_EARLY:
            raise HomeAssistantError(
                "Lunch Money already refreshed from your banks within the last"
                " minute. Wait a moment and try again."
            )

        # Fetching from a bank is a queued background job that can take minutes,
        # so this refresh will usually return the same balances. It is here to
        # pick up anything Lunch Money had already finished importing, and to
        # give the user immediate visible feedback that the press did something.
        await self.coordinator.async_request_refresh()
