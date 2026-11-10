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
