"""Validation of persistent site/node data; no network work on HA startup."""
from __future__ import annotations

import re
from .client import DeviceError, local_url
from .service_contract import NODE_PATTERN, SERVICE_VERSION
from .discovery import search_network


def node_id(value):
    if not isinstance(value, str) or not re.fullmatch(NODE_PATTERN, value):
        raise DeviceError("invalid_identity")
    return value


def topic_prefix(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,127}", value) or value.endswith("/"):
        raise DeviceError("invalid_topic")
    return value


def ieee(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-f]{16}", value):
        raise DeviceError("invalid_identity")
    return value


def settings(data):
    networks = data.get("search_networks", [])
    prefixes = data.get("z2m_prefixes", [])
    if isinstance(networks, str): networks = [v.strip() for v in networks.split(",") if v.strip()]
    if isinstance(prefixes, str): prefixes = [v.strip() for v in prefixes.split(",") if v.strip()]
    if not isinstance(networks, list) or len(networks) > 16 or not isinstance(prefixes, list) or len(prefixes) > 8:
        raise DeviceError("invalid_request")
    return {"search_networks": list(dict.fromkeys(str(search_network(v)) for v in networks)),
            "z2m_prefixes": list(dict.fromkeys(topic_prefix(v) for v in prefixes)),
            "announcement_prefix": topic_prefix(data.get("announcement_prefix", "espoid")),
            "firmware_base_url": local_url(data["firmware_base_url"]) if data.get("firmware_base_url") else ""}


def identity(value):
    if not isinstance(value, dict) or value.get("ok") is not True or type(value.get("api_version")) is not int or value.get("api_version") != SERVICE_VERSION:
        raise DeviceError("unsupported_service")
    node_id(value.get("node_id"))
    if not re.fullmatch(r"[a-f0-9]{16}", str(value.get("boot_id"))): raise DeviceError("invalid_identity")
    if value.get("family") != "esp-c6-io-node" or not re.fullmatch(r"0x[0-9a-f]{8}", str(value.get("firmware_version"))):
        raise DeviceError("invalid_identity")
    for section, fields in (("transports", ("zigbee", "mqtt")), ("ota", ("url", "upload", "confirm", "passive_status"))):
        if not isinstance(value.get(section), dict) or any(type(value[section].get(k)) is not bool for k in fields):
            raise DeviceError("invalid_identity")
    if type(value.get("diagnostics")) is not bool or value["ota"]["passive_status"] is not True:
        raise DeviceError("unsupported_service")
    if "zigbee_ieee" in value: ieee(value["zigbee_ieee"])
    return value


def node_settings(data):
    key = node_id(data.get("node_id"))
    name = data.get("name", key)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise DeviceError("invalid_name")
    result = {"node_id": key, "name": name.strip(), "base_url": local_url(data["base_url"]) if data.get("base_url") else ""}
    binding = data.get("z2m")
    if binding:
        if not isinstance(binding, dict): raise DeviceError("invalid_request")
        result["z2m"] = {"prefix": topic_prefix(binding.get("prefix")), "ieee": ieee(binding.get("ieee"))}
    return result
