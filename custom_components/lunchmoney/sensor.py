"""Sensors for Lunch Money accounts and totals."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PLAID_STATUSES, SOURCE_PLAID
from .coordinator import LunchMoneyConfigEntry, LunchMoneyCoordinator
from .entity import LunchMoneyAccountEntity, LunchMoneyHubEntity
from .models import LunchMoneyAccount


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LunchMoneyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the hub totals and one set of sensors per account."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            LunchMoneyTotalSensor(coordinator, description)
            for description in TOTAL_SENSORS
        ]
    )

    # Accounts come and go — a user links a new bank, or closes one — and a
    # reload should not be the price of seeing it. Entities are added for
    # whatever exists now, and again for anything that appears later.
    known: set[str] = set()

    @callback
    def _async_add_new_accounts() -> None:
        entities: list[SensorEntity] = []

        for key, account in (coordinator.data or {}).items():
            if key in known:
                continue
            known.add(key)

            entities.append(LunchMoneyBalanceSensor(coordinator, key))
            entities.append(LunchMoneyLastUpdatedSensor(coordinator, key))

            # Manual accounts have no bank connection, so a connection entity
            # would be permanently unknown. Only Plaid accounts get one.
            if account.source == SOURCE_PLAID and account.status is not None:
                entities.append(LunchMoneyConnectionSensor(coordinator, key))

        if entities:
            async_add_entities(entities)

    _async_add_new_accounts()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_accounts))


class LunchMoneyBalanceSensor(LunchMoneyAccountEntity, SensorEntity):
    """The current balance of one account."""

    _attr_translation_key = "balance"
    _attr_device_class = SensorDeviceClass.MONETARY
    # TOTAL, not TOTAL_INCREASING: a balance goes down as often as up, and
    # TOTAL_INCREASING would read every payment as a counter reset.
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: LunchMoneyCoordinator, key: str) -> None:
        """Pin the unit to the account's own currency."""
        super().__init__(coordinator, key, "balance")
        # Read once at construction: Home Assistant cannot change a sensor's unit
        # after it has statistics, and an account does not change currency.
        self._attr_native_unit_of_measurement = self._account_snapshot.currency or None

    @property
    def native_value(self) -> Decimal | None:
        """Return the balance."""
        if (account := self.account) is None:
            return None
        return account.balance

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the details worth having on a dashboard card or in a template.

        Kept short on purpose: attributes are written to the database on every
        state change, so each one is a recurring storage cost.
        """
        if (account := self.account) is None:
            return None

        return {
            "institution_name": account.institution_name,
            "account_type": account.account_type,
            "subtype": account.subtype,
            "source": account.source,
            "mask": account.mask,
            "credit_limit": account.credit_limit,
            "balance_in_primary_currency": account.to_base,
            "is_liability": account.is_liability,
        }


class LunchMoneyLastUpdatedSensor(LunchMoneyAccountEntity, SensorEntity):
    """When this account's balance was last known to be correct.

    This is the entity that answers "is this number stale?", which for a manual
    account the user updates by hand is often more useful than the balance.
    """

    _attr_translation_key = "last_updated"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LunchMoneyCoordinator, key: str) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, key, "last_updated")

    @property
    def native_value(self) -> datetime | None:
        """Return when the balance was last refreshed at Lunch Money's end."""
        if (account := self.account) is None:
            return None
        return account.balance_as_of


class LunchMoneyConnectionSensor(LunchMoneyAccountEntity, SensorEntity):
    """The health of a Plaid bank link.

    Bank connections expire quietly — a password change or a bank's periodic
    reconsent turns the status to `relink` and the balance simply stops moving.
    Exposing the status makes that automatable instead of something the user
    discovers weeks later.
    """

    _attr_translation_key = "connection"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PLAID_STATUSES
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LunchMoneyCoordinator, key: str) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, key, "connection")

    @property
    def native_value(self) -> str | None:
        """Return the connection status.

        An unrecognised value is reported as None rather than passed through:
        Home Assistant rejects an out-of-list enum state anyway, and None at
        least renders cleanly while the log records the surprise.
        """
        if (account := self.account) is None or account.status is None:
            return None
        if account.status not in PLAID_STATUSES:
            return None
        return account.status

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the sync timestamps behind the status."""
        if (account := self.account) is None:
            return None

        return {
            "last_successful_sync": account.last_successful_sync,
            "last_import": account.last_import,
        }


class TotalSensorDescription:
    """How to compute one hub-level total.

    A tiny class rather than a SensorEntityDescription because the interesting
    part is the reducer, and carrying a callable through a frozen dataclass
    adds noise without adding safety.
    """

    def __init__(
        self,
        key: str,
        compute: Callable[[list[LunchMoneyAccount]], float],
        icon: str,
    ) -> None:
        """Store the entity key, the reducer, and the icon."""
        self.key = key
        self.compute = compute
        self.icon = icon


def _net_worth(accounts: list[LunchMoneyAccount]) -> float:
    """Return assets minus liabilities, in the user's primary currency."""
    return sum(
        account.signed_to_base or 0.0
        for account in accounts
        if account.to_base is not None
    )


def _total_assets(accounts: list[LunchMoneyAccount]) -> float:
    """Return everything the user owns."""
    return sum(
        account.to_base or 0.0
        for account in accounts
        if account.to_base is not None and not account.is_liability
    )


def _total_liabilities(accounts: list[LunchMoneyAccount]) -> float:
    """Return everything the user owes, as a positive number.

    Reported positive because "I owe $15,000" is how people say it; net worth is
    where the sign flip belongs.
    """
    return sum(
        account.to_base or 0.0
        for account in accounts
        if account.to_base is not None and account.is_liability
    )


TOTAL_SENSORS: list[TotalSensorDescription] = [
    TotalSensorDescription("net_worth", _net_worth, "mdi:scale-balance"),
    TotalSensorDescription("total_assets", _total_assets, "mdi:trending-up"),
    TotalSensorDescription(
        "total_liabilities", _total_liabilities, "mdi:trending-down"
    ),
]


class LunchMoneyTotalSensor(LunchMoneyHubEntity, SensorEntity):
    """A roll-up across every account, in the user's primary currency."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: LunchMoneyCoordinator,
        description: TotalSensorDescription,
    ) -> None:
        """Initialise one total."""
        super().__init__(coordinator, description.key)
        self._description = description
        self._attr_translation_key = description.key
        self._attr_icon = description.icon
        # Totals are built from `to_base`, which Lunch Money has already
        # converted into the user's primary currency — so a household with a
        # euro account and a dollar account still gets one coherent number.
        self._attr_native_unit_of_measurement = coordinator.primary_currency

    @property
    def native_value(self) -> float | None:
        """Return the computed total."""
        if not self.coordinator.data:
            return None
        return round(self._description.compute(list(self.coordinator.data.values())), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Report which accounts could not be included.

        Lunch Money returns a null `to_base` when it has no exchange rate for an
        account's currency. Such an account is silently missing from the total,
        and a total that is quietly wrong is worse than one that says so.
        """
        excluded = [
            account.friendly_name
            for account in (self.coordinator.data or {}).values()
            if account.to_base is None
        ]

        return {
            "accounts_counted": len(self.coordinator.data or {}) - len(excluded),
            "excluded_accounts": excluded,
        }
