"""One normalised account shape for every flavour Lunch Money returns.

Lunch Money describes the same financial account four different ways: manual or
Plaid-linked, on API v1 or v2. The field names differ (`type_name` vs `type`),
some fields exist on one side only (`status` is Plaid-only, and absent entirely
from v1 manual accounts), and balances arrive as 4-decimal-place strings.

Everything downstream — coordinator, sensors, button, diagnostics — reads
`LunchMoneyAccount` and never branches on version or source again. If a new API
shape appears, it is absorbed here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.util import dt as dt_util

from .const import LIABILITY_TYPES, SOURCE_MANUAL, SOURCE_PLAID


@dataclass(frozen=True, slots=True)
class LunchMoneyAccount:
    """A single financial account, normalised across API versions and sources."""

    key: str
    account_id: int
    source: str
    name: str
    display_name: str | None
    institution_name: str | None
    account_type: str
    subtype: str | None
    balance: Decimal | None
    currency: str
    to_base: float | None
    balance_as_of: datetime | None
    status: str | None
    credit_limit: float | None
    mask: str | None
    last_successful_sync: datetime | None
    last_import: datetime | None
    closed: bool

    @property
    def is_liability(self) -> bool:
        """Return True when this account's balance represents money owed."""
        return self.account_type in LIABILITY_TYPES

    @property
    def signed_to_base(self) -> float | None:
        """Return the base-currency balance signed for net-worth arithmetic.

        Lunch Money reports a $500 credit card balance as +500, meaning "you owe
        500". Summing raw values would grow net worth every time the user spends
        on a card, so liabilities are negated exactly once, here.
        """
        if self.to_base is None:
            return None
        return -self.to_base if self.is_liability else self.to_base

    @property
    def friendly_name(self) -> str:
        """Return the label a person would recognise on a dashboard.

        Lunch Money's own UI shows `display_name` when the user has set one. When
        they have not, "Chase Freedom" reads far better than the bare "Freedom"
        that the API returns as `name`.
        """
        if self.display_name:
            return self.display_name
        if self.institution_name:
            return f"{self.institution_name} {self.name}"
        return self.name


def _parse_decimal(raw: Any) -> Decimal | None:
    """Parse a Lunch Money balance without going through float.

    Balances arrive as strings like "5498.2800". Routing them through float would
    introduce representation error into a number the user reconciles against
    their bank, so the string goes straight to Decimal.
    """
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _parse_float(raw: Any) -> float | None:
    """Parse an already-numeric API field, tolerating nulls and stray strings."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse a Lunch Money timestamp into an aware datetime, or None.

    Two shapes turn up in practice: full ISO 8601 with a Z suffix on Plaid
    accounts, and a bare YYYY-MM-DD on manual accounts whose balance the user
    updated by hand. Home Assistant rejects naive datetimes on a timestamp
    sensor, so a date-only value is anchored to midnight UTC rather than dropped
    — a slightly coarse timestamp is far more useful than none at all.
    """
    if not raw:
        return None

    if (parsed := dt_util.parse_datetime(str(raw))) is not None:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt_util.UTC)
        return parsed

    if (parsed_date := dt_util.parse_date(str(raw))) is not None:
        return datetime(
            parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=dt_util.UTC
        )

    return None


def normalise_status(raw: Any) -> str | None:
    """Return a Plaid status Home Assistant can actually label.

    Lunch Money reports two of its statuses with a space in them — "not found"
    and "not supported". Home Assistant requires translation keys to match
    [a-z0-9-_]+, so passing those through unchanged produces a state with no
    label, at precisely the moment the user needs to read one.
    """
    if not raw:
        return None
    return str(raw).replace(" ", "_")


def _normalise_currency(raw: Any) -> str:
    """Return an upper-case ISO currency code for Home Assistant's unit check.

    Lunch Money returns lower-case ("usd"). Home Assistant matches a monetary
    sensor's unit against upper-case ISO 4217 codes to pick the right formatting
    and to group long-term statistics, so a lower-case unit produces an oddly
    rendered entity that never gets a statistics graph.
    """
    if not raw:
        return ""
    return str(raw).upper()


def account_from_plaid(raw: dict[str, Any]) -> LunchMoneyAccount:
    """Build an account from a Plaid-linked account object.

    The field names are identical on v1 and v2, so one parser serves both.
    """
    account_id = int(raw["id"])
    status = normalise_status(raw.get("status"))

    return LunchMoneyAccount(
        key=f"{SOURCE_PLAID}_{account_id}",
        account_id=account_id,
        source=SOURCE_PLAID,
        name=str(raw.get("name") or ""),
        display_name=raw.get("display_name"),
        institution_name=raw.get("institution_name"),
        account_type=str(raw.get("type") or "").lower(),
        subtype=raw.get("subtype"),
        balance=_parse_decimal(raw.get("balance")),
        currency=_normalise_currency(raw.get("currency")),
        to_base=_parse_float(raw.get("to_base")),
        balance_as_of=_parse_timestamp(raw.get("balance_last_update")),
        status=status,
        credit_limit=_parse_float(raw.get("limit")),
        mask=raw.get("mask"),
        last_successful_sync=_parse_timestamp(raw.get("plaid_last_successful_update")),
        last_import=_parse_timestamp(raw.get("last_import")),
        # A Plaid account the user has closed reports it in the same status field
        # that also carries connection health, so closure has to be read out of
        # the enum rather than from a dedicated field.
        closed=status in ("closed", "deactivated", "revoked"),
    )


def account_from_manual(raw: dict[str, Any]) -> LunchMoneyAccount:
    """Build an account from a manual account (v2) or asset (v1) object.

    v1 named the type fields `type_name` / `subtype_name` and has no `status`
    field at all, so closure is inferred from `closed_on`. Both spellings are
    accepted here so the caller never has to know which version produced the row.
    """
    account_id = int(raw["id"])
    status = raw.get("status")
    closed_on = raw.get("closed_on")

    return LunchMoneyAccount(
        key=f"{SOURCE_MANUAL}_{account_id}",
        account_id=account_id,
        source=SOURCE_MANUAL,
        name=str(raw.get("name") or ""),
        display_name=raw.get("display_name"),
        institution_name=raw.get("institution_name"),
        account_type=str(raw.get("type") or raw.get("type_name") or "").lower(),
        subtype=raw.get("subtype") or raw.get("subtype_name"),
        balance=_parse_decimal(raw.get("balance")),
        currency=_normalise_currency(raw.get("currency")),
        to_base=_parse_float(raw.get("to_base")),
        balance_as_of=_parse_timestamp(raw.get("balance_as_of")),
        # Manual accounts have no bank connection to report on. Leaving this None
        # is what tells the sensor platform not to create a connection entity.
        status=None,
        credit_limit=None,
        mask=None,
        last_successful_sync=None,
        last_import=None,
        closed=status == "closed" or closed_on is not None,
    )
