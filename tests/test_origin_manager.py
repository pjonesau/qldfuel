"""Tests for the pure distance/filtering logic in origin_manager.py.

These deliberately avoid any Home Assistant runtime objects (hass, config
entries, etc.) — haversine_km and _filter_stations are plain functions with
no HA dependency, so they're exercised directly.
"""
from qldfuel.origin_manager import _filter_stations, haversine_km


def test_haversine_km_same_point_is_zero():
    assert haversine_km((-27.4698, 153.0251), (-27.4698, 153.0251)) == 0


def test_haversine_km_one_degree_longitude_at_equator():
    # A great-circle degree is ~111.2km by definition; at the equator,
    # a degree of longitude is a full great-circle degree.
    distance = haversine_km((0.0, 0.0), (0.0, 1.0))
    assert 111.0 < distance < 111.3


def test_haversine_km_one_degree_latitude():
    # Meridians are great circles too, so this holds regardless of latitude.
    distance = haversine_km((10.0, 50.0), (11.0, 50.0))
    assert 111.0 < distance < 111.3


def _site(site_id, lat, lon, prices):
    return {
        "siteid": site_id,
        "name": f"Site {site_id}",
        "address": "1 Test St",
        "postcode": "4000",
        "brand": "Test Brand",
        "latitude": lat,
        "longitude": lon,
        "georegionlvl2": "Brisbane",
        "georegionlvl3": "Queensland",
        "prices": prices,
    }


def test_filter_stations_excludes_out_of_radius():
    origin = (0.0, 0.0)
    all_sites = {
        1: _site(1, 0.0, 0.0, {"Unleaded 91": {"price": 1.80}}),
        2: _site(2, 5.0, 5.0, {"Unleaded 91": {"price": 1.75}}),
    }

    stations = _filter_stations(origin, 10.0, {"Unleaded 91"}, all_sites)

    assert set(stations) == {1}
    assert stations[1]["distance_km"] == 0.0


def test_filter_stations_excludes_unwanted_fueltype():
    origin = (0.0, 0.0)
    all_sites = {1: _site(1, 0.0, 0.0, {"Diesel": {"price": 1.90}})}

    stations = _filter_stations(origin, 10.0, {"Unleaded 91"}, all_sites)

    assert stations == {}


def test_filter_stations_only_keeps_wanted_prices():
    origin = (0.0, 0.0)
    all_sites = {
        1: _site(
            1, 0.0, 0.0, {"Unleaded 91": {"price": 1.80}, "Diesel": {"price": 1.90}}
        ),
    }

    stations = _filter_stations(origin, 10.0, {"Unleaded 91"}, all_sites)

    assert set(stations[1]["prices"]) == {"Unleaded 91"}


def test_filter_stations_boundary_radius_is_inclusive():
    origin = (0.0, 0.0)
    # ~111.2km away — put radius_km exactly at that distance.
    all_sites = {1: _site(1, 0.0, 1.0, {"Diesel": {"price": 1.90}})}
    distance = haversine_km(origin, (0.0, 1.0))

    stations = _filter_stations(origin, distance, {"Diesel"}, all_sites)

    assert set(stations) == {1}


# --- OriginManager recompute behaviour, against a mocked hass/coordinator ---

from types import SimpleNamespace
from unittest.mock import MagicMock

from qldfuel.const import (
    CONF_FUELTYPES,
    CONF_ORIGIN_TYPE,
    CONF_RADIUS_KM,
    CONF_TRACKED_ENTITY,
    CONF_ZONE_ENTITY,
    ORIGIN_TYPE_TRACKED,
    ORIGIN_TYPE_ZONE,
)
from qldfuel.origin_manager import OriginManager, entry_title, is_generated_title

BRISBANE = (-27.4698, 153.0251)


class _FakeCoordinator:
    def __init__(self, sites):
        self.data = {"sites": sites}
        self.last_update_success = True
        self.listener = None

    def async_add_listener(self, update_callback):
        self.listener = update_callback
        return lambda: None


def _hass_at(position):
    """A mock hass whose origin entity reports `position` (mutable list)."""
    hass = MagicMock()

    def get_state(entity_id):
        if position[0] is None:
            return None
        lat, lon = position[0]
        return SimpleNamespace(attributes={"latitude": lat, "longitude": lon})

    hass.states.get.side_effect = get_state
    return hass


def _manager(hass, coordinator, origin_type=ORIGIN_TYPE_ZONE):
    config = {
        CONF_ORIGIN_TYPE: origin_type,
        CONF_ZONE_ENTITY: "zone.home" if origin_type == ORIGIN_TYPE_ZONE else None,
        CONF_TRACKED_ENTITY: "device_tracker.phone" if origin_type == ORIGIN_TYPE_TRACKED else None,
        CONF_RADIUS_KM: 10.0,
        CONF_FUELTYPES: ["Unleaded 91"],
    }
    return OriginManager(hass, coordinator, config)


def _sites_with_price(price):
    return {1: _site(1, *BRISBANE, {"Unleaded 91": {"price": price}})}


async def test_coordinator_refresh_updates_prices_without_origin_moving():
    coordinator = _FakeCoordinator(_sites_with_price(1.899))
    manager = _manager(_hass_at([BRISBANE]), coordinator)
    await manager.async_setup()
    notified = []
    manager.async_add_listener(lambda: notified.append(True))

    coordinator.data = {"sites": _sites_with_price(1.759)}
    coordinator.listener()

    assert manager.stations[1]["prices"]["Unleaded 91"]["price"] == 1.759
    assert notified


async def test_small_tracked_move_is_ignored():
    position = [BRISBANE]
    coordinator = _FakeCoordinator(_sites_with_price(1.899))
    manager = _manager(_hass_at(position), coordinator, ORIGIN_TYPE_TRACKED)
    await manager.async_setup()
    notified = []
    manager.async_add_listener(lambda: notified.append(True))

    position[0] = (BRISBANE[0] + 0.001, BRISBANE[1])  # ~110 m
    manager._handle_entity_moved(MagicMock())

    assert not notified


async def test_large_tracked_move_recomputes():
    position = [BRISBANE]
    coordinator = _FakeCoordinator(_sites_with_price(1.899))
    manager = _manager(_hass_at(position), coordinator, ORIGIN_TYPE_TRACKED)
    await manager.async_setup()

    position[0] = (BRISBANE[0] + 1.0, BRISBANE[1])  # ~111 km, out of radius
    manager._handle_entity_moved(MagicMock())

    assert manager.stations == {}


async def test_refresh_with_unknown_position_uses_last_known_origin():
    position = [BRISBANE]
    coordinator = _FakeCoordinator(_sites_with_price(1.899))
    manager = _manager(_hass_at(position), coordinator, ORIGIN_TYPE_TRACKED)
    await manager.async_setup()

    position[0] = None
    coordinator.data = {"sites": _sites_with_price(1.759)}
    coordinator.listener()

    assert manager.stations[1]["prices"]["Unleaded 91"]["price"] == 1.759


async def test_failed_refresh_notifies_listeners_and_reports_unavailable():
    coordinator = _FakeCoordinator(_sites_with_price(1.899))
    manager = _manager(_hass_at([BRISBANE]), coordinator)
    await manager.async_setup()
    notified = []
    manager.async_add_listener(lambda: notified.append(True))

    coordinator.last_update_success = False
    coordinator.listener()

    assert notified
    assert manager.available is False


def test_entry_title_names_the_origin():
    hass = MagicMock()
    hass.states.get.return_value = SimpleNamespace(name="Home")
    assert entry_title(hass, "zone.home") == "Queensland Fuel Prices (Home)"

    hass.states.get.return_value = None
    assert entry_title(hass, "zone.work") == "Queensland Fuel Prices (zone.work)"


def test_is_generated_title():
    assert is_generated_title("Queensland Fuel Prices")
    assert is_generated_title("Queensland Fuel Prices (Home)")
    assert not is_generated_title("My fuel")
