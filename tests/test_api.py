"""Tests for the API client and its version negotiation."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lunchmoney.api import (
    FETCH_QUEUED,
    FETCH_TOO_EARLY,
    LunchMoneyApi,
    LunchMoneyApiError,
    LunchMoneyAuthError,
    LunchMoneyRateLimitError,
)
from custom_components.lunchmoney.const import API_BASE_V1, API_BASE_V2
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import TEST_TOKEN


def _api(hass: HomeAssistant) -> LunchMoneyApi:
    """Build a client on Home Assistant's shared session."""
    return LunchMoneyApi(async_get_clientsession(hass), TEST_TOKEN)


async def test_uses_v2_when_it_works(
    hass: HomeAssistant, mock_v2: AiohttpClientMocker
) -> None:
    """A healthy Lunch Money means the user gets the current API."""
    api = _api(hass)
    assert await api.async_resolve_version() == "v2"


async def test_falls_back_to_v1_when_v2_is_broken(
    hass: HomeAssistant, mock_v1: AiohttpClientMocker
) -> None:
    """A v2 outage must not take the user's balances down with it.

    v2 is an open alpha, so this is the failure this integration is most likely
    to actually meet in the wild.
    """
    api = _api(hass)
    assert await api.async_resolve_version() == "v1"

    accounts = await api.async_get_accounts()
    # v1 calls them assets and names the type field differently; the caller
    # should not be able to tell.
    assert accounts["manual_219807"].account_type == "investment"
    assert accounts["manual_219909"].is_liability


async def test_bad_token_never_triggers_a_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected token must say so, not claim Lunch Money is unreachable.

    The same token authenticates both API versions, so retrying v1 after a 401
    would waste a request and then report the wrong problem, sending the user to
    debug their network instead of their clipboard.
    """
    aioclient_mock.get(f"{API_BASE_V2}/me", status=401, json={"message": "nope"})

    with pytest.raises(LunchMoneyAuthError):
        await _api(hass).async_resolve_version()

    assert all(API_BASE_V1 not in str(call[1]) for call in aioclient_mock.mock_calls)


async def test_rate_limit_is_its_own_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Being throttled is temporary and must be distinguishable from a real failure."""
    aioclient_mock.get(
        f"{API_BASE_V2}/me", status=429, headers={"Retry-After": "30"}, json={}
    )

    with pytest.raises(LunchMoneyRateLimitError) as err:
        await _api(hass).async_resolve_version()

    assert err.value.retry_after == 30


async def test_v1_error_in_a_200_body_is_still_an_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """v1 reports some failures with a 200 and an error key.

    Taken at face value that looks like an empty account list, which would mark
    every one of the user's accounts unavailable instead of reporting a problem.
    """
    aioclient_mock.get(f"{API_BASE_V2}/me", status=404, json={})
    aioclient_mock.get(f"{API_BASE_V1}/me", json={"error": "something went wrong"})

    with pytest.raises(LunchMoneyApiError):
        await _api(hass).async_resolve_version()


async def test_normalises_the_user_across_versions(
    hass: HomeAssistant, mock_v1: AiohttpClientMocker
) -> None:
    """v1 prefixes the person's fields with user_; callers should not care."""
    user = await _api(hass).async_get_user()

    assert user["account_id"] == 18221
    assert user["user_name"] == "User 1"
    # Upper-cased so it can be used directly as a Home Assistant unit.
    assert user["primary_currency"] == "USD"


async def test_plaid_fetch_reports_queued_and_too_early(
    hass: HomeAssistant, mock_v2: AiohttpClientMocker
) -> None:
    """An impatient second press is a normal outcome, not an exception."""
    mock_v2.post(f"{API_BASE_V2}/plaid_accounts/fetch", status=202, text="")
    api = _api(hass)
    assert await api.async_trigger_plaid_fetch() == FETCH_QUEUED

    mock_v2.clear_requests()
    mock_v2.post(f"{API_BASE_V2}/plaid_accounts/fetch", status=425, text="")
    assert await api.async_trigger_plaid_fetch() == FETCH_TOO_EARLY
