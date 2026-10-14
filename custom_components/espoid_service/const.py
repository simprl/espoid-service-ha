"""Constants for the existing IO-node service API, not the future gateway API."""

DOMAIN = "espoid_service"
VERSION = "0.2.2"
PANEL_PATH = "espoid-service"
API_PREFIX = f"/api/{DOMAIN}"
STATIC_PREFIX = f"/{DOMAIN}-static/{VERSION}"
PROFILE_MAX_BYTES = 4095
STATUS_MAX_BYTES = 65536
DIAGNOSTICS_MAX_BYTES = 2 * 1024 * 1024
APP_MAX_BYTES = 0x1E0000
FAMILY = "esp-c6-io-node"
MIN_HA_VERSION = "2026.3.4"
STORE_VERSION = 1
MAX_NODES = 200
MAX_HISTORY = 200
Z2M_CATALOG_MAX_BYTES = 4 * 1024 * 1024
