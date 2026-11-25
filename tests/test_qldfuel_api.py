"""Tests for QldFuelAPI.refresh_price's data-quality guard.

_get_json is patched out so these exercise the parsing/filtering logic
without making any real HTTP requests.
"""
from unittest.mock import patch

from qldfuel.qldfuel_api import REFERENCE_REFRESH_SECONDS, ApiError, QldFuelAPI


def _api_with_fixtures():
    api = QldFuelAPI("dummy-token")
    api._fueltypes = {2: "Unleaded 91"}
    api._sites = {
        100: {
            "siteid": 100,
            "address": "1 Test St",
            "name": "Test Site",
            "brandid": 1,
            "postcode": "4000",
            "georegionlvl2id": 10,
            "georegionlvl3id": 20,
            "latitude": -27.0,
            "longitude": 153.0,
        }
    }
    return api


def _price_entry(price):
    return {
        "SiteId": 100,
        "FuelId": 2,
        "Price": price,
        "CollectionMethod": "T",
        "TransactionDateUtc": "2024-01-01T00:00:00Z",
    }


def test_refresh_price_skips_out_of_bounds_price():
    api = _api_with_fixtures()
    with patch.object(api, "_get_json", return_value={"SitePrices": [_price_entry(0)]}):
        api.refresh_price()

    assert api._sites_by_fuel == {}


def test_refresh_price_keeps_valid_price():
    api = _api_with_fixtures()
    # 1899 (tenths of a cent) == 189.9c/L == $1.899/L
    with patch.object(api, "_get_json", return_value={"SitePrices": [_price_entry(1899)]}):
        api.refresh_price()

    assert api._sites_by_fuel[100]["prices"]["Unleaded 91"]["price"] == 1.899


def _stub_reference_refreshes(api):
    calls = []
    for name in ("refresh_fueltype", "refresh_brand", "refresh_georegion", "refresh_site"):
        setattr(api, name, lambda name=name: calls.append(name))
    api.refresh_price = lambda: calls.append("refresh_price")
    return calls


def test_refresh_data_reuses_reference_data_within_interval():
    api = QldFuelAPI("dummy-token")
    calls = _stub_reference_refreshes(api)

    with patch("qldfuel.qldfuel_api.time.monotonic", side_effect=[1000.0, 1060.0]):
        api.refresh_data()
        api.refresh_data()

    assert calls.count("refresh_site") == 1
    assert calls.count("refresh_fueltype") == 1
    assert calls.count("refresh_price") == 2


def test_refresh_data_refetches_reference_data_after_interval():
    api = QldFuelAPI("dummy-token")
    calls = _stub_reference_refreshes(api)

    with patch(
        "qldfuel.qldfuel_api.time.monotonic",
        side_effect=[1000.0, 1000.0 + REFERENCE_REFRESH_SECONDS],
    ):
        api.refresh_data()
        api.refresh_data()

    assert calls.count("refresh_site") == 2
    assert calls.count("refresh_price") == 2


def test_refresh_data_retries_reference_data_after_a_failure():
    api = QldFuelAPI("dummy-token")
    calls = _stub_reference_refreshes(api)

    def fail():
        raise ApiError("boom")

    api.refresh_site = fail
    with patch("qldfuel.qldfuel_api.time.monotonic", return_value=1000.0):
        try:
            api.refresh_data()
        except ApiError:
            pass
        api.refresh_site = lambda: calls.append("refresh_site")
        api.refresh_data()

    assert calls.count("refresh_site") == 1
    assert calls.count("refresh_fueltype") == 2
