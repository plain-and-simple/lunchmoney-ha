"""Tests for adding, re-authenticating and configuring the integration."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lunchmoney.const import (
    API_BASE_V1,
    API_BASE_V2,
    CONF_API_KEY,
    CONF_API_VERSION,
    CONF_INCLUDE_CLOSED,
    CONF_PRIMARY_CURRENCY,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import TEST_BUDGET_NAME, TEST_TOKEN, load_fixture


async def _start(hass: HomeAssistant) -> str:
    """Open the user flow and return its id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


async def test_a_valid_token_creates_the_entry(
    hass: HomeAssistant, mock_v2: AiohttpClientMocker
) -> None:
    """The happy path: paste a token, get a budget."""
    result = await hass.config_entries.flow.async_configure(
        await _start(hass), {CONF_API_KEY: TEST_TOKEN}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Titled with the budget name so a household running two budgets can tell
    # them apart at a glance.
    assert result["title"] == TEST_BUDGET_NAME
    assert result["data"][CONF_API_VERSION] == "v2"
    assert result["data"][CONF_PRIMARY_CURRENCY] == "USD"


async def test_a_bad_token_says_so_and_lets_the_user_retry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A mistyped token is caught while the real one is still on the clipboard."""
    aioclient_mock.get(f"{API_BASE_V2}/me", status=401, json={"message": "nope"})
    flow_id = await _start(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: "wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    # The same flow must accept a corrected token without starting over.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_V2}/me", json=load_fixture("me.json"))

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: TEST_TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_an_unreachable_api_is_not_reported_as_a_bad_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Sending someone to regenerate a working token wastes their afternoon."""
    aioclient_mock.get(f"{API_BASE_V2}/me", status=500, text="boom")
    aioclient_mock.get(f"{API_BASE_V1}/me", status=500, text="boom")

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), {CONF_API_KEY: TEST_TOKEN}
    )

    assert result["errors"] == {"base": "cannot_connect"}


async def test_the_same_budget_cannot_be_added_twice(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """Two people sharing a household budget would otherwise double every total."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), {CONF_API_KEY: "a-different-token-same-budget"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_swaps_the_token_and_keeps_the_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """Rotating a token must not cost the user their recorded balance history."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "rotated-token"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "rotated-token"


async def test_reauth_rejects_a_token_for_a_different_budget(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Accepting it would silently report someone else's money under these entities."""
    config_entry.add_to_hass(hass)
    other = load_fixture("me.json") | {"account_id": 99999}
    aioclient_mock.get(f"{API_BASE_V2}/me", json=other)

    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "token-for-another-budget"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_options_are_saved(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Changing the interval should stick, and as an int rather than a float."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 30,
            CONF_INCLUDE_CLOSED: True,
            CONF_API_VERSION: "auto",
        },
    )
    await hass.async_block_till_done()

    assert result["data"][CONF_SCAN_INTERVAL] == 30
    assert isinstance(result["data"][CONF_SCAN_INTERVAL], int)
    assert result["data"][CONF_INCLUDE_CLOSED] is True
