"""Async client for the Lunch Money API, covering both v1 and v2.

v2 is the current generation and the default, but Lunch Money describes it as an
open alpha that may change. Rather than leave users stranded the week a field
gets renamed, the client probes v2 and quietly falls back to the older, frozen v1
endpoints when v2 misbehaves.

One rule matters more than the rest: a 401 is never a reason to fall back. The
same token authenticates both versions, so a rejected token is rejected
everywhere. Falling through on 401 would tell a user with a typo'd token that
Lunch Money is unreachable, sending them to look at their network instead of
their clipboard.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from . import const
from .const import API_VERSION_AUTO, API_VERSION_V1, API_VERSION_V2
from .models import LunchMoneyAccount, account_from_manual, account_from_plaid

_LOGGER = logging.getLogger(__name__)

# Balances are not urgent enough to justify holding a Home Assistant update cycle
# open for long. A stalled request that fails fast simply retries next interval.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Lunch Money queues a Plaid fetch as a background job and refuses a second
# request within a minute of the last one. That refusal is an expected outcome of
# an impatient button press, not a failure, so it gets its own return value.
FETCH_QUEUED = "queued"
FETCH_TOO_EARLY = "too_early"


class LunchMoneyError(Exception):
    """Base error for every failure this client reports."""


class LunchMoneyAuthError(LunchMoneyError):
    """The access token was rejected, on every API version."""


class LunchMoneyRateLimitError(LunchMoneyError):
    """Lunch Money's 100-requests-per-minute limit was hit."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        """Record how long Lunch Money asked us to wait before retrying."""
        super().__init__(message)
        self.retry_after = retry_after


class LunchMoneyApiError(LunchMoneyError):
    """Lunch Money was reachable but the request did not succeed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Keep the HTTP status so version negotiation can decide what it means."""
        super().__init__(message)
        self.status = status


class LunchMoneyApi:
    """Talk to Lunch Money on whichever API version actually works."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        version: str = API_VERSION_AUTO,
    ) -> None:
        """Store the session and the caller's version preference.

        The session belongs to Home Assistant, so this class never closes it.
        """
        self._session = session
        self._token = token
        self._preferred_version = version
        # Resolved lazily on the first call so constructing the client stays
        # synchronous and cheap, including inside the config flow.
        self._version: str | None = None if version == API_VERSION_AUTO else version

    @property
    def version(self) -> str | None:
        """Return the API version in use, or None before the first call."""
        return self._version

    @property
    def token(self) -> str:
        """Return the token in use, so the config flow can persist it."""
        return self._token

    def _base_url(self, version: str) -> str:
        """Return the base URL for a version.

        Read off the module at call time rather than imported by value, so tests
        and scripts/live_check.py can repoint the whole client at Lunch Money's
        mock server by patching a single attribute.
        """
        return const.API_BASE_V2 if version == API_VERSION_V2 else const.API_BASE_V1

    async def _request(self, version: str, method: str, path: str) -> tuple[int, Any]:
        """Make one request and return its status and decoded body.

        Returns rather than raises on a non-2xx status so that version
        negotiation can inspect the status and decide whether it is fatal or
        merely a reason to try the other version. Only genuinely unrecoverable
        conditions — no network, no JSON, a rejected token — raise from here.
        """
        url = f"{self._base_url(version)}{path}"

        try:
            async with self._session.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
            ) as response:
                status = response.status

                if status == 401:
                    raise LunchMoneyAuthError("Lunch Money rejected the access token")

                if status == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise LunchMoneyRateLimitError(
                        "Lunch Money rate limit reached",
                        retry_after=int(retry_after) if retry_after else None,
                    )

                # A 202/425 from the Plaid fetch endpoint carries no body worth
                # decoding, and some error responses are HTML. Neither should
                # crash the caller, so decoding failure degrades to None.
                try:
                    body = await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    body = None

                return status, body

        except TimeoutError as err:
            raise LunchMoneyApiError(
                f"Timed out talking to Lunch Money at {url}"
            ) from err
        except aiohttp.ClientError as err:
            raise LunchMoneyApiError(
                f"Could not reach Lunch Money at {url}: {err}"
            ) from err

    async def _get_json(self, version: str, path: str) -> dict[str, Any]:
        """Fetch a path and return its body, raising on anything unusable."""
        status, body = await self._request(version, "GET", path)

        if status >= 400:
            raise LunchMoneyApiError(
                f"Lunch Money returned {status} for {path}: {_error_text(body)}",
                status=status,
            )

        if not isinstance(body, dict):
            raise LunchMoneyApiError(
                f"Lunch Money returned an unexpected body for {path}",
                status=status,
            )

        # v1 signals some failures with a 200 and an error key in the body, a
        # habit v2 dropped in favour of real status codes. Without this check the
        # v1 path would treat an error page as an empty account list and silently
        # mark every one of the user's accounts unavailable.
        if "error" in body:
            raise LunchMoneyApiError(
                f"Lunch Money reported an error for {path}: {body['error']}",
                status=status,
            )

        return body

    async def async_resolve_version(self) -> str:
        """Return the API version to use, probing if the caller said auto.

        Probing costs one request against a 100-per-minute budget and only
        happens once per client, so it is cheaper than getting the version wrong.
        """
        if self._version is not None:
            return self._version

        try:
            await self._get_json(API_VERSION_V2, "/me")
        except LunchMoneyAuthError:
            # The token is bad everywhere. Falling back here would replace a
            # clear "check your token" with a misleading "cannot connect".
            raise
        except LunchMoneyApiError as err:
            _LOGGER.warning(
                "Lunch Money API v2 did not respond usably (%s), falling back to"
                " v1. v2 is an open alpha, so this usually means it changed"
                " under us and the integration needs an update",
                err,
            )
            await self._get_json(API_VERSION_V1, "/me")
            self._version = API_VERSION_V1
        else:
            self._version = API_VERSION_V2

        return self._version

    async def async_get_user(self) -> dict[str, Any]:
        """Return the account identity behind the token.

        v1 prefixes the person's fields with `user_`; v2 does not. The caller
        gets one shape either way. `account_id` identifies the Lunch Money budget
        rather than the person, which is exactly the right uniqueness key for a
        config entry: two people sharing a household budget should not be able to
        add it twice.
        """
        version = await self.async_resolve_version()
        body = await self._get_json(version, "/me")

        return {
            "account_id": body.get("account_id"),
            "budget_name": body.get("budget_name") or "Lunch Money",
            "primary_currency": str(body.get("primary_currency") or "usd").upper(),
            "user_name": body.get("name") or body.get("user_name"),
        }

    async def async_get_accounts(self) -> dict[str, LunchMoneyAccount]:
        """Return every account, keyed by its stable entity key.

        The two endpoints are independent, so they run concurrently — halving the
        time the coordinator spends waiting, and keeping a slow Plaid response
        from delaying manual balances.
        """
        version = await self.async_resolve_version()
        manual_path = "/manual_accounts" if version == API_VERSION_V2 else "/assets"

        manual_body, plaid_body = await asyncio.gather(
            self._get_json(version, manual_path),
            self._get_json(version, "/plaid_accounts"),
        )

        accounts: dict[str, LunchMoneyAccount] = {}

        # v2 renamed the envelope key along with the endpoint, so accept both.
        manual_rows = (
            manual_body.get("manual_accounts") or manual_body.get("assets") or []
        )
        for row in manual_rows:
            account = account_from_manual(row)
            accounts[account.key] = account

        for row in plaid_body.get("plaid_accounts") or []:
            account = account_from_plaid(row)
            accounts[account.key] = account

        return accounts

    async def async_trigger_plaid_fetch(self) -> str:
        """Ask Lunch Money to pull fresh data from the user's banks.

        This only queues a background job; balances move on a later poll, not on
        the response to this call. A 425 means the last fetch was under a minute
        ago and is reported back rather than raised, because an impatient second
        button press is a normal thing for a person to do.
        """
        version = await self.async_resolve_version()
        status, body = await self._request(version, "POST", "/plaid_accounts/fetch")

        if status == 425:
            return FETCH_TOO_EARLY

        if status >= 400:
            raise LunchMoneyApiError(
                f"Lunch Money refused the refresh request: {_error_text(body)}",
                status=status,
            )

        return FETCH_QUEUED


def _error_text(body: Any) -> str:
    """Pull the most useful message out of either version's error shape.

    v1 returns {"message": ...}; v2 returns {"message": ..., "errors": [{"errMsg":
    ...}]} where the nested messages are the specific ones. Surfacing the
    specific text is what turns a support thread into a self-service fix.
    """
    if not isinstance(body, dict):
        return "no details provided"

    if isinstance(errors := body.get("errors"), list):
        details = [
            str(item["errMsg"])
            for item in errors
            if isinstance(item, dict) and item.get("errMsg")
        ]
        if details:
            return "; ".join(details)

    for key in ("message", "error", "name"):
        if value := body.get(key):
            return str(value)

    return "no details provided"
