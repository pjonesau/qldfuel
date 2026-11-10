"""Tests for the orphaned-registry-entry cleanup in geo_location.py.

_async_purge_orphaned_registry_entries is pure removal logic layered on top
of the entity registry, so it's tested here against a mocked registry
rather than a running Home Assistant instance (see the testing boundary
documented in CLAUDE.md for why entities otherwise aren't unit tested).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qldfuel.geo_location import _async_purge_orphaned_registry_entries


def _registry_entry(entity_id: str, unique_id: str, domain: str) -> SimpleNamespace:
    return SimpleNamespace(entity_id=entity_id, unique_id=unique_id, domain=domain)


@patch("qldfuel.geo_location.er")
def test_purge_removes_station_no_longer_in_radius(mock_er: MagicMock) -> None:
    entity_registry = MagicMock()
    mock_er.async_get.return_value = entity_registry
    mock_er.async_entries_for_config_entry.return_value = [
        _registry_entry("geo_location.in_range", "entry1_siteA", "geo_location"),
        _registry_entry("geo_location.out_of_range", "entry1_siteB", "geo_location"),
    ]
    manager = SimpleNamespace(stations={"siteA": {}})
    entry = SimpleNamespace(entry_id="entry1")

    _async_purge_orphaned_registry_entries(hass=MagicMock(), entry=entry, manager=manager)

    entity_registry.async_remove.assert_called_once_with("geo_location.out_of_range")


@patch("qldfuel.geo_location.er")
def test_purge_leaves_other_domains_alone(mock_er: MagicMock) -> None:
    """A sensor entity sharing the same config entry must never be touched."""
    entity_registry = MagicMock()
    mock_er.async_get.return_value = entity_registry
    mock_er.async_entries_for_config_entry.return_value = [
        _registry_entry("sensor.cheapest_unleaded_91", "entry1_cheapest_Unleaded 91", "sensor"),
    ]
    manager = SimpleNamespace(stations={})
    entry = SimpleNamespace(entry_id="entry1")

    _async_purge_orphaned_registry_entries(hass=MagicMock(), entry=entry, manager=manager)

    entity_registry.async_remove.assert_not_called()


@patch("qldfuel.geo_location.er")
def test_purge_keeps_stations_still_in_radius(mock_er: MagicMock) -> None:
    entity_registry = MagicMock()
    mock_er.async_get.return_value = entity_registry
    mock_er.async_entries_for_config_entry.return_value = [
        _registry_entry("geo_location.in_range", "entry1_siteA", "geo_location"),
    ]
    manager = SimpleNamespace(stations={"siteA": {}})
    entry = SimpleNamespace(entry_id="entry1")

    _async_purge_orphaned_registry_entries(hass=MagicMock(), entry=entry, manager=manager)

    entity_registry.async_remove.assert_not_called()
