"""Constants for the Lunch Money integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "lunchmoney"

# Config entry data keys.
CONF_API_KEY: Final = "api_key"
CONF_API_VERSION: Final = "api_version"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_BUDGET_NAME: Final = "budget_name"
CONF_PRIMARY_CURRENCY: Final = "primary_currency"

# Options keys.
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_INCLUDE_CLOSED: Final = "include_closed"

# API version selection. AUTO probes v2 and falls back to v1; the explicit values
# are an escape hatch for the day v2's open alpha breaks between our releases and
# a user needs a working integration before we can ship a fix.
API_VERSION_AUTO: Final = "auto"
API_VERSION_V1: Final = "v1"
API_VERSION_V2: Final = "v2"
API_VERSIONS: Final = [API_VERSION_AUTO, API_VERSION_V2, API_VERSION_V1]

# Base URLs live here rather than being built from a version string, so tests and
# scripts/live_check.py can point the whole integration at mock.lunchmoney.dev by
# patching a single module attribute.
API_BASE_V2: Final = "https://api.lunchmoney.dev/v2"
API_BASE_V1: Final = "https://api.lunchmoney.dev/v1"

# Lunch Money allows 100 requests per minute per IP. A refresh costs two requests,
# so even the 5-minute floor leaves the budget almost untouched — the interval is
# about how fresh the user wants balances, not about staying under the limit.
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 15
MIN_SCAN_INTERVAL_MINUTES: Final = 5
MAX_SCAN_INTERVAL_MINUTES: Final = 1440

# Account sources. Manual accounts are typed in by the user; plaid accounts are
# synced from a real financial institution and are the only ones with a
# connection status worth surfacing.
SOURCE_MANUAL: Final = "manual"
SOURCE_PLAID: Final = "plaid"

# Lunch Money reports credit-card and loan balances as positive amounts owed, so
# these types must be subtracted rather than added when totalling net worth.
# Getting this set wrong silently doubles or inverts the headline number, which is
# why it is a named constant with a test of its own.
LIABILITY_TYPES: Final = frozenset(
    {
        "credit",
        "loan",
        "other liability",
    }
)

# The exact status enum a Plaid-linked account can report, taken from Lunch
# Money's own generated API types. Home Assistant validates an enum sensor's
# state against this list and logs an error for anything unlisted, so a value
# missing here becomes a visible bug rather than a silent one.
PLAID_STATUSES: Final = [
    "active",
    "inactive",
    "closed",
    "deactivated",
    "not found",
    "not supported",
    "relink",
    "syncing",
    "revoked",
    "error",
]

# Where the user goes to create the token, and where a device links back to.
LUNCH_MONEY_APP_URL: Final = "https://my.lunchmoney.app"
LUNCH_MONEY_DEVELOPERS_URL: Final = "https://my.lunchmoney.app/developers"
