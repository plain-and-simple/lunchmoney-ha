"""Tests for the account sensors, the device tree and the totals."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lunchmoney.const import (
    API_BASE_V2,
    CONF_INCLUDE_CLOSED,
    DOMAIN,
)
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import load_fixture

# Totals implied by the captured fixtures. Assets: 41211.80 + 50000 + 500
# (manual) + 12345.67 + 5498.28 + 3001.58 (plaid). Liabilities: 1004.80 + 200
# (manual credit) + 0 (plaid credit).
EXPECTED_ASSETS = 112557.33
EXPECTED_LIABILITIES = 1204.80
EXPECTED_NET_WORTH = 111352.53


def _entity_id(hass: HomeAssistant, entry_id: str, unique_suffix: str) -> str:
    """Look an entity up by unique id rather than by guessing its entity id.

    Entity ids are derived from account names like "Penny's Visa" and would make
    these tests fragile for reasons that have nothing to do with what they check.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry_id}_{unique_suffix}"
    )
    assert entity_id is not None, f"no sensor with unique id ...{unique_suffix}"
    return entity_id


async def test_every_account_gets_a_balance(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Both manual and Plaid accounts must show up, with the right money."""
    entry_id = setup_integration.entry_id

    checking = hass.states.get(_entity_id(hass, entry_id, "plaid_119806_balance"))
    assert checking.state == "5498.2800"
    assert checking.attributes["unit_of_measurement"] == "USD"
    assert checking.attributes["device_class"] == "monetary"
    assert checking.attributes["institution_name"] == "Western Bank"

    brokerage = hass.states.get(_entity_id(hass, entry_id, "manual_219807_balance"))
    assert brokerage.state == "41211.8000"
    assert brokerage.attributes["source"] == "manual"


async def test_liability_accounts_are_flagged(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A card's balance is money owed, and a dashboard needs to be able to tell."""
    card = hass.states.get(
        _entity_id(hass, setup_integration.entry_id, "manual_219909_balance")
    )
    assert card.attributes["is_liability"] is True


async def test_totals_treat_debt_as_debt(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Net worth must fall when the user owes money.

    This is the arithmetic most likely to be silently wrong, and the number the
    user is most likely to check against the Lunch Money app.
    """
    entry_id = setup_integration.entry_id

    assert float(hass.states.get(_entity_id(hass, entry_id, "total_assets")).state) == (
        EXPECTED_ASSETS
    )
    assert (
        float(hass.states.get(_entity_id(hass, entry_id, "total_liabilities")).state)
        == EXPECTED_LIABILITIES
    )
    assert float(hass.states.get(_entity_id(hass, entry_id, "net_worth")).state) == (
        EXPECTED_NET_WORTH
    )


async def test_totals_use_the_primary_currency(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A multi-currency household still needs one coherent headline number."""
    net_worth = hass.states.get(
        _entity_id(hass, setup_integration.entry_id, "net_worth")
    )
    assert net_worth.attributes["unit_of_measurement"] == "USD"
    assert net_worth.attributes["accounts_counted"] == 9
    assert net_worth.attributes["excluded_accounts"] == []


async def test_accounts_without_a_conversion_rate_are_reported(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A total that is quietly missing an account is worse than one that says so."""
    manual = load_fixture("manual_accounts.json")
    manual["manual_accounts"][0]["to_base"] = None
    manual["manual_accounts"][0]["name"] = "Unconvertible"
    manual["manual_accounts"][0]["institution_name"] = None
    manual["manual_accounts"][0]["display_name"] = None

    aioclient_mock.get(f"{API_BASE_V2}/me", json=load_fixture("me.json"))
    aioclient_mock.get(f"{API_BASE_V2}/manual_accounts", json=manual)
    aioclient_mock.get(
        f"{API_BASE_V2}/plaid_accounts", json=load_fixture("plaid_accounts.json")
    )

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    net_worth = hass.states.get(_entity_id(hass, config_entry.entry_id, "net_worth"))
    assert net_worth.attributes["excluded_accounts"] == ["Unconvertible"]
    assert net_worth.attributes["accounts_counted"] == 8


async def test_only_plaid_accounts_get_a_connection_sensor(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A manual account has no bank link, so the entity would never have a value."""
    registry = er.async_get(hass)
    entry_id = setup_integration.entry_id

    assert (
        hass.states.get(_entity_id(hass, entry_id, "plaid_119804_connection")).state
        == "inactive"
    )

    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry_id}_manual_219807_connection"
        )
        is None
    )


async def test_last_updated_is_a_timestamp(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Is this balance stale?" is often more useful than the balance itself."""
    state = hass.states.get(
        _entity_id(hass, setup_integration.entry_id, "plaid_119806_last_updated")
    )
    assert state.attributes["device_class"] == "timestamp"
    assert state.state == "2025-01-27T01:38:07+00:00"


async def test_accounts_are_grouped_under_a_hub_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Grouping is the whole reason for a device per account rather than a flat list."""
    devices = dr.async_get(hass)
    entry_id = setup_integration.entry_id

    hub = devices.async_get_device(identifiers={(DOMAIN, entry_id)})
    assert hub is not None

    account_device = devices.async_get_device(
        identifiers={(DOMAIN, f"{entry_id}_plaid_119805")}
    )
    assert account_device is not None
    assert account_device.name == "Penny's Visa"
    assert account_device.manufacturer == "Chase"
    assert account_device.via_device_id == hub.id


async def test_closed_accounts_are_hidden_unless_asked_for(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A closed account's balance never changes again, so it is clutter by default."""
    manual = load_fixture("manual_accounts.json")
    manual["manual_accounts"][3]["status"] = "closed"

    aioclient_mock.get(f"{API_BASE_V2}/me", json=load_fixture("me.json"))
    aioclient_mock.get(f"{API_BASE_V2}/manual_accounts", json=manual)
    aioclient_mock.get(
        f"{API_BASE_V2}/plaid_accounts", json=load_fixture("plaid_accounts.json")
    )

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{config_entry.entry_id}_manual_220001_balance"
        )
        is None
    )

    # ...and turning the option on brings it back.
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_INCLUDE_CLOSED: True}
    )
    await hass.async_block_till_done()

    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{config_entry.entry_id}_manual_220001_balance"
        )
        is not None
    )


async def test_a_vanished_account_goes_unavailable_rather_than_disappearing(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """A partial API response must never destroy a user's recorded history."""
    entity_id = _entity_id(hass, setup_integration.entry_id, "manual_219807_balance")
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    manual = load_fixture("manual_accounts.json")
    manual["manual_accounts"] = manual["manual_accounts"][1:]

    mock_v2.clear_requests()
    mock_v2.get(f"{API_BASE_V2}/manual_accounts", json=manual)
    mock_v2.get(
        f"{API_BASE_V2}/plaid_accounts", json=load_fixture("plaid_accounts.json")
    )

    coordinator = setup_integration.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_a_newly_linked_account_appears_without_a_reload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_v2: AiohttpClientMocker,
) -> None:
    """Linking a bank in Lunch Money should just show up in Home Assistant."""
    registry = er.async_get(hass)
    entry_id = setup_integration.entry_id
    new_unique_id = f"{entry_id}_plaid_555555_balance"

    assert registry.async_get_entity_id("sensor", DOMAIN, new_unique_id) is None

    plaid = load_fixture("plaid_accounts.json")
    plaid["plaid_accounts"].append(
        plaid["plaid_accounts"][2] | {"id": 555555, "name": "Brand New Checking"}
    )

    mock_v2.clear_requests()
    mock_v2.get(
        f"{API_BASE_V2}/manual_accounts", json=load_fixture("manual_accounts.json")
    )
    mock_v2.get(f"{API_BASE_V2}/plaid_accounts", json=plaid)

    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert registry.async_get_entity_id("sensor", DOMAIN, new_unique_id) is not None
