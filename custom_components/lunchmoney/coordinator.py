"""Poll Lunch Money and share one snapshot with every entity."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    LunchMoneyApi,
    LunchMoneyAuthError,
    LunchMoneyError,
    LunchMoneyRateLimitError,
)
from .const import (
    API_VERSION_AUTO,
    CONF_API_KEY,
    CONF_API_VERSION,
    CONF_BUDGET_NAME,
    CONF_INCLUDE_CLOSED,
    CONF_PRIMARY_CURRENCY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .models import LunchMoneyAccount

_LOGGER = logging.getLogger(__name__)

type LunchMoneyConfigEntry = ConfigEntry["LunchMoneyCoordinator"]


class LunchMoneyCoordinator(DataUpdateCoordinator[dict[str, LunchMoneyAccount]]):
    """Fetch every account on one schedule, shared by all entities.

    Without a coordinator each of the three-plus entities per account would poll
    independently, turning a dozen accounts into dozens of requests per interval
    against a 100-per-minute limit.
    """

    config_entry: LunchMoneyConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LunchMoneyConfigEntry) -> None:
        """Build the client and schedule from the entry's data and options."""
        self.api = LunchMoneyApi(
            async_get_clientsession(hass),
            entry.data[CONF_API_KEY],
            entry.options.get(
                CONF_API_VERSION, entry.data.get(CONF_API_VERSION, API_VERSION_AUTO)
            ),
        )

        # Cached from /me at config time so the hub entities have a currency and
        # a name before the first refresh completes.
        self.primary_currency: str = entry.data.get(CONF_PRIMARY_CURRENCY, "USD")
        self.budget_name: str = entry.data.get(CONF_BUDGET_NAME, "Lunch Money")

        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    @property
    def include_closed(self) -> bool:
        """Return whether closed accounts should get entities.

        Off by default: most people close an account precisely because they have
        stopped caring about its balance, and a permanently frozen sensor is
        clutter. Anyone tracking a paid-off mortgage can turn it back on.
        """
        return self.config_entry.options.get(CONF_INCLUDE_CLOSED, False)

    async def _async_update_data(self) -> dict[str, LunchMoneyAccount]:
        """Fetch all accounts, translating failures into the right HA outcome."""
        try:
            accounts = await self.api.async_get_accounts()
        except LunchMoneyAuthError as err:
            # Raising this specific error is what makes Home Assistant show the
            # "reconfigure" prompt instead of an unhelpful red error, which
            # matters because rotating an API token is routine.
            raise ConfigEntryAuthFailed(
                "Lunch Money rejected the access token"
            ) from err
        except LunchMoneyRateLimitError as err:
            # Retrying inside this call would spend the next window's budget too.
            # Skipping keeps the previous balances on screen and tries again on
            # the normal schedule.
            raise UpdateFailed(
                f"Lunch Money rate limit reached; waiting for the next update ({err})"
            ) from err
        except LunchMoneyError as err:
            raise UpdateFailed(str(err)) from err

        if self.include_closed:
            return accounts

        return {key: account for key, account in accounts.items() if not account.closed}
