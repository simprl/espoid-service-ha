"""Persisted resource envelope and explicit OTA confirmation policy."""
from copy import deepcopy
import re
from ..const import MAX_NODES
from .errors import DeviceError
from .interruption_policy import validate_interruption

ENTITIES = ("status", "diagnostics", "ota", "control", "mqtt", "equipment")
CONTROL_ACTIONS = ("wifi", "hold", "retry_transport", "reboot_wifi", "reboot_zigbee", "recovery_retry", "resolve", "check", "service_enter", "service_exit")


def validate_resource_records(saved):
    if not isinstance(saved, dict) or not {"status", "diagnostics", "ota"} <= set(saved) or set(saved) - set(ENTITIES):
        raise DeviceError("storage_failed")
    saved = {**saved, "control": saved.get("control", {}), "mqtt": saved.get("mqtt", {}), "equipment": saved.get("equipment", {})}
    for entity, records in saved.items():
        if not isinstance(records, dict) or len(records) > MAX_NODES:
            raise DeviceError("storage_failed")
        for node_id, record in records.items():
            if (not isinstance(node_id,str) or not re.fullmatch(r"espoid-[0-9a-f]{12}", node_id)
                or not isinstance(record, dict) or record.get("id") != node_id
                or set(record) - {"interruption"} != {"id","entity","version","updated_at","state","error","validation","data","pending"}
                or record.get("entity") != entity or type(record.get("version")) is not int
                or not 0 <= record["version"] < 2**53
                or record.get("state") not in ("idle", "refreshing", "saving", "error", "uncertain")
                or not isinstance(record.get("data"), dict)
                or not isinstance(record.get("pending"), (dict, type(None)))):
                raise DeviceError("storage_failed")
            validate_interruption(record.get('interruption'))
    return deepcopy(saved)


def ota_can_confirm(operation, status):
    return bool(operation and operation.get("artifact") and (operation["state"] == "verifying"
                or operation["action"] == "ota" and operation["state"] == "verified")
                and status and status.get("wifi_ota", {}).get("verification_pending") is True
                and status.get("ota_marker_sha256") == operation["artifact"]["sha256"])
