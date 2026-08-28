"""Raw client for the Queensland Fuel Prices API.

This client is shared across every config entry that uses the same API key
(see coordinator.py) — it fetches and caches the full statewide site/price
dataset, unfiltered. Per-origin radius and fuel-type filtering happens in
origin_manager.py, not here.
"""
from datetime import datetime
import logging

import requests

from .const import BASE_URL, COUNTRY_AU

_LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    """Raised when the API cannot be reached or returns an unexpected response."""


class ApiAuthError(ApiError):
    """Raised when the API rejects the configured subscriber token."""


def _get_json(url: str, headers: dict[str, str]) -> dict:
    try:
        response = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as err:
        raise ApiError(f"Could not reach {url}: {err}") from err

    if response.status_code in (401, 403):
        raise ApiAuthError(f"API key rejected ({response.status_code})")
    if response.status_code != 200:
        raise ApiError(f"Unexpected response {response.status_code} from {url}")

    try:
        return response.json()
    except ValueError as err:
        raise ApiError(f"Invalid JSON from {url}: {err}") from err


class QldFuelAPI:
    """Client for the Fuel Prices Qld Subscriber API."""

    def __init__(self, access_token: str) -> None:
        self._subscriber_token = str(access_token)
        self.headers = {"Authorization": f"FPDAPI SubscriberToken={self._subscriber_token}"}
        self._geolookup2city: dict[int, str] = {}
        self._geolookup3state: dict[int, str] = {}
        self._brands: dict[int, str] = {}
        self._fueltypes: dict[int, str] = {}
        self._sites: dict[int, dict] = {}
        self._sites_by_fuel: dict[int, dict] = {}

    def refresh_georegion(self) -> None:
        url = f"{BASE_URL}/Subscriber/GetCountryGeographicRegions?countryId={COUNTRY_AU}"
        data = _get_json(url, self.headers)

        geolookup2city: dict[int, str] = {}
        geolookup3state: dict[int, str] = {}
        for region in data["GeographicRegions"]:
            level = region["GeoRegionLevel"]
            region_id = region["GeoRegionId"]
            if level == 2:
                geolookup2city[region_id] = region["Name"]
            elif level == 3:
                geolookup3state[region_id] = region["Name"]

        self._geolookup2city = geolookup2city
        self._geolookup3state = geolookup3state

    def get_fueltype(self) -> dict[int, str]:
        """Return the fuel type id -> name lookup (for the config flow)."""
        return self._fueltypes

    def refresh_fueltype(self) -> None:
        url = f"{BASE_URL}/Subscriber/GetCountryFuelTypes?countryId={COUNTRY_AU}"
        data = _get_json(url, self.headers)
        self._fueltypes = {fuel["FuelId"]: fuel["Name"] for fuel in data["Fuels"]}

    def refresh_brand(self) -> None:
        url = f"{BASE_URL}/Subscriber/GetCountryBrands?countryId={COUNTRY_AU}"
        data = _get_json(url, self.headers)
        self._brands = {brand["BrandId"]: brand["Name"] for brand in data["Brands"]}

    def refresh_site(self) -> None:
        url = (
            f"{BASE_URL}/Subscriber/GetFullSiteDetails?countryId={COUNTRY_AU}"
            "&geoRegionLevel=3&geoRegionId=1"
        )
        data = _get_json(url, self.headers)

        sites = {}
        for site in data["S"]:
            sites[site["S"]] = {
                "siteid": site["S"],
                "address": site["A"],
                "name": site["N"],
                "brandid": site["B"],
                "postcode": site["P"],
                "georegionlvl2id": site["G2"],
                "georegionlvl3id": site["G3"],
                "latitude": site["Lat"],
                "longitude": site["Lng"],
            }
        self._sites = sites

    def refresh_price(self) -> None:
        url = (
            f"{BASE_URL}/Price/GetSitesPrices?countryId={COUNTRY_AU}"
            "&geoRegionLevel=3&geoRegionId=1"
        )
        data = _get_json(url, self.headers)

        sites_by_fuel: dict[int, dict] = {}
        for entry in data["SitePrices"]:
            site = self._sites.get(entry["SiteId"])
            if site is None:
                # Price quoted for a site GetFullSiteDetails didn't return.
                continue

            fuel_id = entry["FuelId"]
            fuel_name = self._fueltypes.get(fuel_id)
            if fuel_name is None:
                continue

            site_bucket = sites_by_fuel.setdefault(
                entry["SiteId"],
                {
                    "siteid": site["siteid"],
                    "name": site["name"],
                    "address": site["address"],
                    "postcode": site["postcode"],
                    "brand": self._brands.get(site["brandid"], "Unknown"),
                    "latitude": site["latitude"],
                    "longitude": site["longitude"],
                    "georegionlvl2": self._geolookup2city.get(site["georegionlvl2id"]),
                    "georegionlvl3": self._geolookup3state.get(site["georegionlvl3id"]),
                    "prices": {},
                },
            )
            site_bucket["prices"][fuel_name] = {
                "fueltypeid": fuel_id,
                "price": round(entry["Price"] / 1000, 2),
                "collection_method": entry["CollectionMethod"],
                "collection_date": entry["TransactionDateUtc"],
            }

        self._sites_by_fuel = sites_by_fuel

    def refresh_data(self) -> None:
        """Refresh fuel types, brands, sites and prices in one pass."""
        self.refresh_fueltype()
        self.refresh_brand()
        self.refresh_georegion()
        self.refresh_site()
        self.refresh_price()

    def get_data(self) -> dict:
        """Return the full, unfiltered statewide site/price dataset."""
        return {"updated": datetime.now(), "sites": self._sites_by_fuel}
