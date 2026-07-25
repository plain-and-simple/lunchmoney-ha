"""Config flow for the Lunch Money integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    LunchMoneyApi,
    LunchMoneyAuthError,
    LunchMoneyError,
    LunchMoneyRateLimitError,
)
from .const import (
    API_VERSION_AUTO,
    API_VERSIONS,
    CONF_ACCOUNT_ID,
    CONF_API_KEY,
    CONF_API_VERSION,
    CONF_BUDGET_NAME,
    CONF_INCLUDE_CLOSED,
    CONF_PRIMARY_CURRENCY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    LUNCH_MONEY_DEVELOPERS_URL,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


class LunchMoneyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one Lunch Money budget per config entry."""

    VERSION = 1

    async def _async_validate_token(
        self, token: str, errors: dict[str, str]
    ) -> dict[str, Any] | None:
        """Check a token against the live API and return the budget's identity.

        Doing a real call here rather than accepting any non-empty string means a
        mistyped token is caught while the user still has the real one on their
        clipboard, instead of surfacing later as a broken integration.
        """
        api = LunchMoneyApi(async_get_clientsession(self.hass), token)

        try:
            user = await api.async_get_user()
        except LunchMoneyAuthError:
            errors["base"] = "invalid_auth"
        except LunchMoneyRateLimitError:
            errors["base"] = "rate_limited"
        except LunchMoneyError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error validating the Lunch Money token")
            errors["base"] = "unknown"
        else:
            if not user.get("account_id"):
                # A token that authenticates but resolves to no budget cannot be
                # given a unique_id, and would silently allow duplicate entries.
                errors["base"] = "no_account"
                return None
            user[CONF_API_VERSION] = api.version
            return user

        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for an access token and confirm it works."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_API_KEY].strip()

            if not token:
                errors[CONF_API_KEY] = "invalid_auth"
            elif (user := await self._async_validate_token(token, errors)) is not None:
                # The budget's account_id, not the person's user id: a shared
                # household budget must not be addable twice from two logins.
                await self.async_set_unique_id(str(user[CONF_ACCOUNT_ID]))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user[CONF_BUDGET_NAME],
                    data={
                        CONF_API_KEY: token,
                        CONF_API_VERSION: user[CONF_API_VERSION],
                        CONF_ACCOUNT_ID: user[CONF_ACCOUNT_ID],
                        CONF_BUDGET_NAME: user[CONF_BUDGET_NAME],
                        CONF_PRIMARY_CURRENCY: user[CONF_PRIMARY_CURRENCY],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"developers_url": LUNCH_MONEY_DEVELOPERS_URL},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start over when the stored token stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Swap in a fresh token without losing the entry's history.

        Deleting and re-adding the integration would work, but it would orphan
        every entity's recorded history — which for balance sensors is the whole
        point of having them.
        """
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            token = user_input[CONF_API_KEY].strip()

            if not token:
                errors[CONF_API_KEY] = "invalid_auth"
            elif (user := await self._async_validate_token(token, errors)) is not None:
                # Refuse a token belonging to a different budget. Accepting it
                # would leave every entity silently reporting another account's
                # money under the original entity IDs.
                await self.async_set_unique_id(str(user[CONF_ACCOUNT_ID]))
                self._abort_if_unique_id_mismatch(reason="wrong_account")

                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_API_KEY: token,
                        CONF_API_VERSION: user[CONF_API_VERSION],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "budget_name": reauth_entry.title,
                "developers_url": LUNCH_MONEY_DEVELOPERS_URL,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return LunchMoneyOptionsFlow()


class LunchMoneyOptionsFlow(OptionsFlow):
    """Tune polling and account filtering after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    # The selector hands back a float; timedelta(minutes=15.0)
                    # works but reads oddly in logs and diagnostics.
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_INCLUDE_CLOSED: user_input[CONF_INCLUDE_CLOSED],
                    CONF_API_VERSION: user_input[CONF_API_VERSION],
                }
            )

        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=MAX_SCAN_INTERVAL_MINUTES,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="minutes",
                        )
                    ),
                    vol.Required(
                        CONF_INCLUDE_CLOSED,
                        default=options.get(CONF_INCLUDE_CLOSED, False),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_API_VERSION,
                        default=options.get(
                            CONF_API_VERSION,
                            self.config_entry.data.get(
                                CONF_API_VERSION, API_VERSION_AUTO
                            ),
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=API_VERSIONS,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="api_version",
                        )
                    ),
                }
            ),
        )
