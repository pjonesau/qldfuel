"""Tests for QldFuelAPI.refresh_price's data-quality guard.

_get_json is patched out so these exercise the parsing/filtering logic
without making any real HTTP requests.
"""
from unittest.mock import patch

from qldfuel.qldfuel_api import QldFuelAPI


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

    assert api._sites_by_fuel[100]["prices"]["Unleaded 91"]["price"] == 1.9
