"""Tests for entry setup, polling behaviour and recovery."""

from __future__ import annotations

from datetime import timedelta

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lunchmoney.const import (
    API_BASE_V1,
    API_BASE_V2,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import load_fixture


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The integration must come up and go away cleanly."""
    assert setup_integration.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_lunch_money_is_down(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An outage during a restart should resolve itself, not need a human."""
    aioclient_mock.get(f"{API_BASE_V2}/me", status=500, text="boom")
    aioclient_mock.get(f"{API_BASE_V1}/me", status=500, text="boom")

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_revoked_token_starts_a_reauth_flow(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """Revoking a token should prompt for a new one, not just log errors forever."""
    mock_v2.clear_requests()
    mock_v2.get(f"{API_BASE_V2}/manual_accounts", status=401, json={})
    mock_v2.get(f"{API_BASE_V2}/plaid_accounts", status=401, json={})

    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["handler"] == DOMAIN and flow["context"]["source"] == "reauth"
    ]
    assert len(flows) == 1


async def test_balances_survive_a_transient_failure(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """One failed poll should not blank out every balance on the dashboard."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{setup_integration.entry_id}_plaid_119806_balance"
    )

    mock_v2.clear_requests()
    mock_v2.get(f"{API_BASE_V2}/manual_accounts", status=503, text="")
    mock_v2.get(f"{API_BASE_V2}/plaid_accounts", status=503, text="")

    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # Unavailable, not unknown: the last known balance is still the best answer,
    # and the entity says plainly that it is not current.
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    mock_v2.clear_requests()
    mock_v2.get(
        f"{API_BASE_V2}/manual_accounts", json=load_fixture("manual_accounts.json")
    )
    mock_v2.get(
        f"{API_BASE_V2}/plaid_accounts", json=load_fixture("plaid_accounts.json")
    )

    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "5498.2800"


async def test_the_configured_interval_is_used(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """An interval that silently ignores the option would be worse than no option."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SCAN_INTERVAL: 60}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.runtime_data.update_interval == timedelta(minutes=60)

    calls_before = len(mock_v2.mock_calls)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=61))
    await hass.async_block_till_done()

    assert len(mock_v2.mock_calls) > calls_before


async def test_diagnostics_never_leak_the_token(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Diagnostics exist to be pasted into a public issue."""
    from custom_components.lunchmoney.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    result = await async_get_config_entry_diagnostics(hass, setup_integration)
    serialised = str(result)

    assert "test-access-token" not in serialised
    assert result["entry"]["data"]["api_key"] == "**REDACTED**"
    # Balances stay in, because "the number is wrong" cannot be diagnosed without them.
    assert any(account["balance"] == "5498.2800" for account in result["accounts"])
    # No card's last four digits reach the payload. Checked by value rather than
    # by key, because the redactor leaves a null mask as null and a test that
    # only looked at manual accounts would pass while leaking every real one.
    assert "7468" not in serialised
    assert "1973" not in serialised
