"""Tests for the refresh-from-banks button."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lunchmoney.const import API_BASE_V2, DOMAIN
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er


def _button_id(hass: HomeAssistant, entry_id: str) -> str:
    """Return the refresh button's entity id."""
    entity_id = er.async_get(hass).async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, f"{entry_id}_refresh"
    )
    assert entity_id is not None
    return entity_id


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    """Press the button."""
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def test_pressing_queues_a_bank_fetch(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """The button exists so a user can pull a balance they just changed in real life."""
    mock_v2.post(f"{API_BASE_V2}/plaid_accounts/fetch", status=202, text="")

    await _press(hass, _button_id(hass, setup_integration.entry_id))

    assert any("plaid_accounts/fetch" in str(call[1]) for call in mock_v2.mock_calls)


async def test_pressing_twice_explains_the_wait(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """Lunch Money refuses a second fetch within a minute.

    Pressing again is a normal thing for an impatient person to do, so it should
    produce a sentence they can act on rather than a stack trace.
    """
    mock_v2.post(f"{API_BASE_V2}/plaid_accounts/fetch", status=425, text="")

    with pytest.raises(HomeAssistantError, match="within the last"):
        await _press(hass, _button_id(hass, setup_integration.entry_id))


async def test_a_failed_fetch_surfaces_as_an_error(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """A silent no-op would leave the user pressing a button that does nothing."""
    mock_v2.post(
        f"{API_BASE_V2}/plaid_accounts/fetch", status=500, json={"message": "boom"}
    )

    with pytest.raises(HomeAssistantError):
        await _press(hass, _button_id(hass, setup_integration.entry_id))
