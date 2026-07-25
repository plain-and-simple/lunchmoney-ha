"""Live check: boot a real Home Assistant against Lunch Money's mock API.

Unlike the pytest suite this starts an actual HomeAssistant instance with real
.storage persistence and real HTTP over the wire, so it also proves the boot,
restart and manifest-loading paths — the parts unit tests mock away and where a
broken translation file or a bad manifest key actually shows up.

It talks to https://mock.lunchmoney.dev, which serves realistic canned data to
any token of 11+ characters, so it needs no real credentials and touches nobody's
finances.
"""

import asyncio
from pathlib import Path
import sys

CONFIG_DIR = Path(sys.argv[1])

# The mock server has no v1, so pin to v2 rather than letting the client probe.
MOCK_BASE = "https://mock.lunchmoney.dev/v2"
MOCK_TOKEN = "livecheck-token-1234567890"

from homeassistant import config_entries, core, loader  # noqa: E402
from homeassistant.auth import auth_manager_from_config  # noqa: E402
from homeassistant.bootstrap import async_load_base_functionality  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    """Record and print one assertion."""
    results.append((label, ok, detail))
    print(
        f"{'PASS' if ok else 'FAIL'}  {label}{'  — ' + str(detail) if detail else ''}"
    )


async def start_hass() -> core.HomeAssistant:
    """Boot a real Home Assistant against the throwaway config dir."""
    hass = core.HomeAssistant(str(CONFIG_DIR))
    hass.config.config_dir = str(CONFIG_DIR)
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    await async_load_base_functionality(hass)
    # Real boots create the auth manager after the registries, in core_config.
    # http refuses to start without it, and network depends on http.
    hass.auth = await auth_manager_from_config(hass, [{"type": "homeassistant"}], [])
    # Home Assistant's shared aiohttp session builds a DNS resolver from the
    # network component's adapter list, so a real outbound request fails without
    # it. A real boot sets this up as part of core config.
    assert await async_setup_component(hass, "network", {})
    await hass.async_start()
    await hass.async_block_till_done()
    return hass


async def main() -> None:
    """Add the integration through the real config flow, then restart."""
    hass = await start_hass()

    # Import only after the boot, so this is the copy Home Assistant actually
    # loaded out of the config directory rather than the one in the repo — and
    # so the redirect below really does apply to the running integration.
    from custom_components.lunchmoney import const

    # Point the integration at the mock server. Reading the base URL off the
    # const module at call time is what makes this one-line redirect possible.
    const.API_BASE_V2 = MOCK_BASE

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": "user"}
    )
    check("config flow opens", result["step_id"] == "user", result["step_id"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {const.CONF_API_KEY: MOCK_TOKEN}
    )
    check(
        "token is accepted and an entry is created",
        result["type"] == "create_entry",
        result.get("reason") or result.get("errors") or result["type"],
    )
    await hass.async_block_till_done()

    balances = [
        state
        for state in hass.states.async_all("sensor")
        if state.attributes.get("device_class") == "monetary"
    ]
    # Six manual + four Plaid accounts in the mock data, plus three totals. The
    # exact count is Lunch Money's to change; anything in this range means the
    # platform wired up rather than silently creating nothing.
    check(
        "balance sensors exist",
        len(balances) >= 10,
        f"{len(balances)} monetary sensors",
    )

    net_worth = next(
        (
            s
            for s in hass.states.async_all("sensor")
            if s.entity_id.endswith("_net_worth")
        ),
        None,
    )
    check(
        "net worth is computed",
        net_worth is not None and net_worth.state not in ("unknown", "unavailable"),
        net_worth.state if net_worth else "missing",
    )

    button = next(iter(hass.states.async_all("button")), None)
    check(
        "refresh button exists",
        button is not None,
        button.entity_id if button else "missing",
    )

    entry_id = hass.config_entries.async_entries(const.DOMAIN)[0].entry_id
    await hass.async_stop()

    # ---------- second boot: prove the entry survives a restart ----------
    hass = await start_hass()
    # A full boot discovers and sets up the component from the stored entry;
    # this stripped-down boot loads the entries but does not start them, so the
    # setup has to be asked for explicitly.
    assert await async_setup_component(hass, const.DOMAIN, {})
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(entry_id)
    check(
        "the entry reloads from storage",
        entry is not None and entry.state is config_entries.ConfigEntryState.LOADED,
        entry.state if entry else "missing",
    )
    check(
        "sensors come back after a restart",
        len(hass.states.async_all("sensor")) > 0,
        f"{len(hass.states.async_all('sensor'))} sensors",
    )

    await hass.async_stop()

    failed = [label for label, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
