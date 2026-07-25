"""Shared fixtures for the Lunch Money tests.

The JSON fixtures are captured verbatim from Lunch Money's own mock server
(https://mock.lunchmoney.dev/v2), so the tests exercise the real field names,
the real 4-decimal balance strings, and the real mix of account types rather
than a tidied-up idea of them. Recapture with, for example:

    curl -H "Authorization: Bearer mocktoken123456" \\
        https://mock.lunchmoney.dev/v2/plaid_accounts
"""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lunchmoney.const import (
    API_BASE_V1,
    API_BASE_V2,
    CONF_ACCOUNT_ID,
    CONF_API_KEY,
    CONF_API_VERSION,
    CONF_BUDGET_NAME,
    CONF_PRIMARY_CURRENCY,
    DOMAIN,
)
from homeassistant.core import HomeAssistant

FIXTURE_DIR = Path(__file__).parent / "fixtures"

TEST_TOKEN = "test-access-token"
TEST_ACCOUNT_ID = 18221
TEST_BUDGET_NAME = "🏠 Family budget"


def load_fixture(name: str) -> dict[str, Any]:
    """Return a captured API response body."""
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Let Home Assistant load this integration at all.

    Without it every test fails at setup with "integration not found", which is
    a confusing way to learn that a fixture is missing.
    """
    yield


@pytest.fixture
def mock_v2(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Serve the full v2 API from captured fixtures."""
    aioclient_mock.get(f"{API_BASE_V2}/me", json=load_fixture("me.json"))
    aioclient_mock.get(
        f"{API_BASE_V2}/manual_accounts", json=load_fixture("manual_accounts.json")
    )
    aioclient_mock.get(
        f"{API_BASE_V2}/plaid_accounts", json=load_fixture("plaid_accounts.json")
    )
    return aioclient_mock


@pytest.fixture
def mock_v1(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Serve v2 as broken and v1 as working, to exercise the fallback."""
    aioclient_mock.get(f"{API_BASE_V2}/me", status=500, text="upstream boom")
    aioclient_mock.get(f"{API_BASE_V1}/me", json=load_fixture("v1/me.json"))
    aioclient_mock.get(f"{API_BASE_V1}/assets", json=load_fixture("v1/assets.json"))
    aioclient_mock.get(
        f"{API_BASE_V1}/plaid_accounts", json=load_fixture("v1/plaid_accounts.json")
    )
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry as the config flow would have created it."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_BUDGET_NAME,
        unique_id=str(TEST_ACCOUNT_ID),
        data={
            CONF_API_KEY: TEST_TOKEN,
            CONF_API_VERSION: "v2",
            CONF_ACCOUNT_ID: TEST_ACCOUNT_ID,
            CONF_BUDGET_NAME: TEST_BUDGET_NAME,
            CONF_PRIMARY_CURRENCY: "USD",
        },
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_v2: AiohttpClientMocker
) -> MockConfigEntry:
    """Set up the integration against the v2 fixtures and return its entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
