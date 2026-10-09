"""Constants for the existing IO-node service API, not the future gateway API."""

DOMAIN = "espoid_service"
VERSION = "0.1.2"
PANEL_PATH = "espoid-service"
API_PREFIX = f"/api/{DOMAIN}"
PROFILE_MAX_BYTES = 4095
STATUS_MAX_BYTES = 65536
DIAGNOSTICS_MAX_BYTES = 2 * 1024 * 1024
APP_MAX_BYTES = 0x1E0000
FAMILY = "esp-c6-io-node"

