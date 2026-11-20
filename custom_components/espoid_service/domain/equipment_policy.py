"""Profile-defined commissioning and diagnostic actions over the common equipment API."""
from copy import deepcopy
import secrets

from ..equipment_contract import EQUIPMENT_DEFINITIONS
from .errors import DeviceError
from .schema_policy import schema_matches

ACTIONS = {
    "scan": "ble_scan", "pair": "ble_pair", "connect": "ble_connect",
    "diagnostics_start": "ble_diagnostics_start", "diagnostics_cancel": "ble_diagnostics_cancel",
}


def observation(value):
    if not schema_matches(EQUIPMENT_DEFINITIONS, EQUIPMENT_DEFINITIONS["EquipmentObservation"], value):
        raise DeviceError("invalid_response")
    catalog, state, commissioning = value["catalog"], value["state"], value["commissioning"]
    device = next((item for item in catalog["devices"] if item["device_id"] == state["device_id"]), None)
    if (catalog["boot_id"] != state["boot_id"] or catalog["boot_id"] != commissioning["boot_id"]
            or not device or device["binding_generation"] != state["binding_generation"]):
        raise DeviceError("equipment_context_changed")
    return deepcopy(value)


def prepare_action(value, action, body):
    value = observation(value)
    operation = ACTIONS.get(action)
    device = next(item for item in value["catalog"]["devices"] if item["device_id"] == value["state"]["device_id"])
    declared = next((item for item in device["actions"] if item["id"] == operation and item["enabled"]), None)
    if not declared:
        raise DeviceError("equipment_action_unavailable")
    request = {
        "api_version": value["catalog"]["api_version"], "request_id": secrets.token_hex(6),
        "boot_id": value["catalog"]["boot_id"],
        "device_id": device["device_id"], "binding_generation": device["binding_generation"],
        "operation": operation, "ttl_ms": 30000,
    }
    if declared["input"] == "peer":
        request["peer"] = body.get("peer")
    elif "peer" in body:
        raise DeviceError("invalid_request")
    if not schema_matches(EQUIPMENT_DEFINITIONS, EQUIPMENT_DEFINITIONS["CommandRequest"], request):
        raise DeviceError("invalid_request")
    if request.get("peer", {}).get("address") == "00:00:00:00:00:00":
        raise DeviceError("invalid_request")
    return request


def check_context(value, request):
    value = observation(value)
    catalog, state = value["catalog"], value["state"]
    if (catalog["boot_id"] != request["boot_id"]
            or state["device_id"] != request["device_id"]
            or state["binding_generation"] != request["binding_generation"]):
        raise DeviceError("equipment_context_changed")


def matching_result(value, request):
    if not schema_matches(EQUIPMENT_DEFINITIONS, EQUIPMENT_DEFINITIONS["CommandResult"], value):
        return False
    return all(value.get(key) == request[key] for key in (
        "request_id", "boot_id", "device_id", "binding_generation", "operation"))
