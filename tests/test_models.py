"""Tests for the account normalisation layer.

These run without Home Assistant because the arithmetic they protect — chiefly
the sign of a liability — is the single most consequential thing in the
integration, and it deserves tests that cannot fail for unrelated reasons.
"""

from __future__ import annotations

from decimal import Decimal

from custom_components.lunchmoney.const import PLAID_STATUSES
from custom_components.lunchmoney.models import (
    account_from_manual,
    account_from_plaid,
)


def test_balance_keeps_full_precision() -> None:
    """A balance the user reconciles against their bank must not drift.

    Lunch Money sends "5498.2800" as a string. Routing that through float would
    introduce representation error into a number people check to the cent.
    """
    account = account_from_plaid(
        {"id": 1, "name": "Checking", "balance": "5498.2800", "currency": "usd"}
    )

    assert account.balance == Decimal("5498.2800")


def test_liabilities_are_subtracted_from_net_worth() -> None:
    """Spending on a credit card must lower net worth, not raise it.

    Lunch Money reports a card balance as a positive "amount owed". Summing raw
    values would make debt look like wealth.
    """
    card = account_from_plaid(
        {"id": 1, "name": "Visa", "type": "credit", "to_base": 500.0, "balance": "500"}
    )
    checking = account_from_plaid(
        {
            "id": 2,
            "name": "Checking",
            "type": "cash",
            "to_base": 500.0,
            "balance": "500",
        }
    )

    assert card.is_liability
    assert card.signed_to_base == -500.0
    assert not checking.is_liability
    assert checking.signed_to_base == 500.0


def test_loans_and_other_liabilities_count_as_debt() -> None:
    """A mortgage is debt even though it is not a credit card."""
    for account_type in ("loan", "other liability"):
        account = account_from_manual(
            {"id": 1, "name": "Mortgage", "type": account_type, "balance": "1"}
        )
        assert account.is_liability, account_type


def test_manual_and_plaid_ids_do_not_collide() -> None:
    """The two endpoints number their accounts independently.

    Keying on the raw id would let a manual account silently overwrite a Plaid
    account, and the user would lose an entity with no error anywhere.
    """
    manual = account_from_manual({"id": 42, "name": "Shoebox", "balance": "1"})
    plaid = account_from_plaid({"id": 42, "name": "Checking", "balance": "1"})

    assert manual.key != plaid.key


def test_v1_field_names_are_accepted() -> None:
    """v1 named the type fields differently; the fallback path depends on this."""
    account = account_from_manual(
        {
            "id": 7,
            "name": "Brokerage",
            "type_name": "investment",
            "subtype_name": "brokerage",
            "balance": "100",
            "currency": "usd",
        }
    )

    assert account.account_type == "investment"
    assert account.subtype == "brokerage"


def test_date_only_timestamps_become_aware_datetimes() -> None:
    """Manual accounts often carry a bare date.

    Home Assistant rejects a naive datetime on a timestamp sensor, so a
    date-only value has to be anchored rather than dropped — a coarse timestamp
    still answers "is this balance stale?".
    """
    account = account_from_manual(
        {"id": 1, "name": "Shoebox", "balance": "1", "balance_as_of": "2024-06-25"}
    )

    assert account.balance_as_of is not None
    assert account.balance_as_of.tzinfo is not None


def test_closed_is_detected_from_either_signal() -> None:
    """v2 has a status field; v1 only has closed_on."""
    v2_closed = account_from_manual(
        {"id": 1, "name": "x", "balance": "1", "status": "closed"}
    )
    v1_closed = account_from_manual(
        {"id": 2, "name": "x", "balance": "1", "closed_on": "2025-07-01"}
    )
    open_account = account_from_manual(
        {"id": 3, "name": "x", "balance": "1", "status": "active"}
    )

    assert v2_closed.closed
    assert v1_closed.closed
    assert not open_account.closed


def test_currency_is_upper_cased() -> None:
    """Home Assistant matches monetary units against upper-case ISO codes.

    A lower-case unit renders oddly and never gets a long-term statistics graph.
    """
    assert (
        account_from_plaid(
            {"id": 1, "name": "x", "balance": "1", "currency": "usd"}
        ).currency
        == "USD"
    )


def test_friendly_name_prefers_what_the_user_would_recognise() -> None:
    """ "Freedom" is not a useful device name; "Chase Freedom" is."""
    assert (
        account_from_plaid(
            {"id": 1, "name": "Freedom", "institution_name": "Chase", "balance": "1"}
        ).friendly_name
        == "Chase Freedom"
    )
    assert (
        account_from_plaid(
            {
                "id": 1,
                "name": "Freedom",
                "institution_name": "Chase",
                "display_name": "Penny's Visa",
                "balance": "1",
            }
        ).friendly_name
        == "Penny's Visa"
    )


def test_manual_accounts_have_no_connection_status() -> None:
    """There is no bank link to report on, so no connection entity is created."""
    assert (
        account_from_manual(
            {"id": 1, "name": "x", "balance": "1", "status": "active"}
        ).status
        is None
    )


def test_statuses_with_spaces_become_slugs() -> None:
    """Two of Lunch Money's statuses contain a space.

    Home Assistant rejects a translation key that is not [a-z0-9-_]+, so an
    account whose bank Plaid cannot find would otherwise show a raw, unlabelled
    state — at the exact moment the user needs to read what went wrong.
    """
    for raw, expected in (
        ("not found", "not_found"),
        ("not supported", "not_supported"),
    ):
        account = account_from_plaid(
            {"id": 1, "name": "x", "balance": "1", "status": raw}
        )
        assert account.status == expected
        assert account.status in PLAID_STATUSES
