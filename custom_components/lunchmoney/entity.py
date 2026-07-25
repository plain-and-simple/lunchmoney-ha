"""Shared entity bases defining the Lunch Money device tree.

Two shapes of entity exist: those describing the budget as a whole, and those
describing one account. Both live here so the device identifiers — the thing that
must never change once a user has entities, dashboards and automations built on
them — are written exactly once.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LUNCH_MONEY_APP_URL
from .coordinator import LunchMoneyCoordinator
from .models import LunchMoneyAccount


class LunchMoneyHubEntity(CoordinatorEntity[LunchMoneyCoordinator]):
    """An entity describing the whole budget rather than one account."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LunchMoneyCoordinator, suffix: str) -> None:
        """Attach this entity to the budget's hub device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry

        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.budget_name,
            manufacturer="Lunch Money",
            # SERVICE rather than the default, because there is no physical
            # device here and Home Assistant renders service entries more
            # sensibly in the device list.
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=LUNCH_MONEY_APP_URL,
        )


class LunchMoneyAccountEntity(CoordinatorEntity[LunchMoneyCoordinator]):
    """An entity describing one financial account."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: LunchMoneyCoordinator, account_key: str, suffix: str
    ) -> None:
        """Attach this entity to its account's device, under the hub."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._account_key = account_key

        account = self._account_snapshot

        self._attr_unique_id = f"{entry.entry_id}_{account_key}_{suffix}"
        self._attr_device_info = DeviceInfo(
            # Namespaced by entry so two budgets in one Home Assistant never
            # collide on a Lunch Money account id.
            identifiers={(DOMAIN, f"{entry.entry_id}_{account_key}")},
            name=account.friendly_name,
            manufacturer=account.institution_name or "Lunch Money",
            model=_device_model(account),
            # Nesting under the hub is what produces the grouped tree in the UI
            # instead of a flat list of unrelated devices.
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def _account_snapshot(self) -> LunchMoneyAccount:
        """Return the account as it was when the entity was created.

        Used only for values fixed at construction — device name, currency. It
        assumes the account is present, which is guaranteed because entities are
        only ever created from a refresh that contained it.
        """
        return self.coordinator.data[self._account_key]

    @property
    def account(self) -> LunchMoneyAccount | None:
        """Return the current account data, or None if it has gone away."""
        return (self.coordinator.data or {}).get(self._account_key)

    @property
    def available(self) -> bool:
        """Return whether Lunch Money still reports this account.

        An account can vanish because the user closed it, or because a partial
        API response omitted it. Going unavailable — rather than deleting the
        entity — means a transient blip never destroys recorded history.
        """
        return super().available and self.account is not None


def _device_model(account: LunchMoneyAccount) -> str:
    """Return a human-readable account type for the device card."""
    if account.subtype and account.subtype != account.account_type:
        return f"{account.account_type} · {account.subtype}".strip(" ·")
    return account.account_type or "account"
