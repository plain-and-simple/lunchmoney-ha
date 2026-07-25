"""Checks that every user-visible string actually exists.

A missing translation key does not raise. It produces an entity with no name, a
blank dropdown option, or an error box with a raw key in it — all of which reach
the user before they reach a developer. These tests turn that into a CI failure.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lunchmoney.const import API_VERSIONS, DOMAIN, PLAID_STATUSES
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "lunchmoney"
STRINGS = json.loads((COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))


def test_english_translations_match_strings() -> None:
    """The two files must not drift apart.

    Home Assistant reads strings.json for the config flow and translations/en.json
    for entities, so a change made in only one place is invisible until exactly
    the wrong moment.
    """
    en = json.loads(
        (COMPONENT_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert en == STRINGS


def test_manifest_agrees_with_the_code() -> None:
    """A domain mismatch stops the integration loading at all."""
    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"] is True
    # HACS matches the manifest version against the release tag, so a
    # non-semver value breaks installs rather than just looking untidy.
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])


def test_every_config_flow_message_exists() -> None:
    """An unlisted error key shows the user the raw key instead of a sentence."""
    source = (COMPONENT_DIR / "config_flow.py").read_text(encoding="utf-8")

    for key in re.findall(r'errors\[[^\]]+\] = "([a-z_]+)"', source):
        assert key in STRINGS["config"]["error"], f"missing config.error.{key}"

    for key in re.findall(r'reason="([a-z_]+)"', source):
        assert key in STRINGS["config"]["abort"], f"missing config.abort.{key}"


def test_every_api_version_option_is_labelled() -> None:
    """An unlabelled dropdown option renders as an empty row."""
    options = STRINGS["selector"]["api_version"]["options"]
    for version in API_VERSIONS:
        assert version in options, f"missing selector.api_version.options.{version}"


def test_every_connection_status_is_labelled() -> None:
    """Lunch Money can report any of these, including on a bad day.

    An unlabelled state is exactly the one a user sees when something has gone
    wrong, which is the worst moment for it to render as `not_supported`.
    """
    states = STRINGS["entity"]["sensor"]["connection"]["state"]
    for status in PLAID_STATUSES:
        assert status in states, f"missing entity.sensor.connection.state.{status}"


async def test_every_entity_has_a_name(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """An entity whose translation key is missing shows up with no name at all."""
    registry = er.async_get(hass)

    entities = [
        entry
        for entry in registry.entities.values()
        if entry.config_entry_id == setup_integration.entry_id
    ]
    assert entities, "the integration created no entities to check"

    for entry in entities:
        platform_strings = STRINGS["entity"].get(entry.domain, {})
        assert entry.translation_key in platform_strings, (
            f"missing entity.{entry.domain}.{entry.translation_key}.name"
        )
        assert platform_strings[entry.translation_key].get("name")
