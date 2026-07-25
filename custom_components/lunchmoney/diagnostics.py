"""Diagnostics for the Lunch Money integration.

The point of this file is that a user can attach a bug report without ever
pasting a live access token — or their account numbers — into a public GitHub
issue.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ACCOUNT_ID, CONF_API_KEY
from .coordinator import LunchMoneyConfigEntry

TO_REDACT_ENTRY = {CONF_API_KEY, CONF_ACCOUNT_ID}

# The last four digits of a card and Plaid's item id are both account-identifying
# and irrelevant to every bug this integration is likely to have.
TO_REDACT_ACCOUNT = {"mask", "plaid_item_id", "external_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LunchMoneyConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
            "options": dict(entry.options),
        },
        "api_version": coordinator.api.version,
        "primary_currency": coordinator.primary_currency,
        "include_closed": coordinator.include_closed,
        "last_update_success": coordinator.last_update_success,
        "accounts": [
            # Balances stay in, because "the number is wrong" is the most likely
            # bug and it cannot be diagnosed without them. Decimal and datetime
            # are stringified so the payload is JSON-serialisable.
            async_redact_data(
                {
                    key: str(value) if value is not None else None
                    for key, value in asdict(account).items()
                },
                TO_REDACT_ACCOUNT,
            )
            for account in (coordinator.data or {}).values()
        ],
    }
