"""Constants for the Queensland Fuel integration."""

DOMAIN = "qldfuel"
BASE_URL = "https://fppdirectapi-prod.fuelpricesqld.com.au"
COUNTRY_AU = "21"

CONF_APIKEY = "apikey"
CONF_FUELTYPES = "fueltypes"
CONF_ORIGIN_TYPE = "origin_type"
CONF_ZONE_ENTITY = "zone_entity"
CONF_TRACKED_ENTITY = "tracked_entity"
CONF_RADIUS_KM = "radius_km"
CONF_SCAN_INTERVAL = "scan_interval_minutes"

ORIGIN_TYPE_ZONE = "zone"
ORIGIN_TYPE_TRACKED = "tracked_entity"

DEFAULT_RADIUS_KM = 10.0

# Minimum distance the origin must move before stations are recomputed, so
# GPS jitter on a tracked device doesn't churn entities on every update.
MOVEMENT_THRESHOLD_KM = 1.0

# Shared price/site data coordinator poll interval, in minutes. User
# configurable per entry (CONF_SCAN_INTERVAL); when entries sharing an API
# key disagree, the coordinator polls at the fastest of their requests.
DEFAULT_SCAN_INTERVAL_MINUTES = 5
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 120

# Dispatcher signals, formatted with (entry_id, site_id).
SIGNAL_UPDATE_STATION = "qldfuel_update_{}_{}"
SIGNAL_DELETE_STATION = "qldfuel_delete_{}_{}"
