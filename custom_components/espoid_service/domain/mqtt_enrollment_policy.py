"""Bounded direct-MQTT targets and enrollment evidence. No IO or HA."""
from __future__ import annotations
import re
from .errors import DeviceError
from .address_policy import validate_local_origin

from ..service_contract import ENROLLMENT_TTL_MS

ENROLLMENT_TTL = ENROLLMENT_TTL_MS / 1000
TOPIC = r"[A-Za-z0-9][A-Za-z0-9_./-]{0,111}"
NODE = r"espoid-[0-9a-f]{12}"

def mqtt_target(value):
    if (not isinstance(value, dict) or value.get("transport") != "mqtt"
            or not re.fullmatch(NODE, str(value.get("node_id")))
            or not re.fullmatch(TOPIC, str(value.get("topic")))
            or not value["topic"].endswith("/" + value["node_id"])):
        raise DeviceError("invalid_request")
    return {"transport": "mqtt", "node_id": value["node_id"], "topic": value["topic"],
            "admin_url": validate_local_origin(value.get("admin_url", ""))}

def enrollment_certificate(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{2}){100,768}", value):
        raise DeviceError("binding_identity_mismatch")
    return value
