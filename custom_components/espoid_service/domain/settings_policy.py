"""Service settings values, validation and revisions, independent of the host."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any, TypedDict

from .address_policy import (
    validate_local_origin,
    validate_search_network,
    validate_service_origin,
)
from .errors import DeviceError


class ServiceSettings(TypedDict):
    firmware_base_url: str
    service_base_url: str
    search_networks: list[str]
    z2m_prefixes: list[str]
    announcement_prefix: str


class SettingsMetadata(TypedDict):
    revision: str
    version: int
    updated_at: str | None


def validate_settings(value: object) -> ServiceSettings:
    """Validate the complete save DTO; persisted config may use older defaults."""
    if not isinstance(value, dict) or set(value) != ServiceSettings.__required_keys__:
        raise DeviceError("invalid_request")
    if any(
        not isinstance(value[key], str)
        for key in ("firmware_base_url", "service_base_url", "announcement_prefix")
    ) or any(
        not isinstance(value[key], list)
        or any(not isinstance(item, str) for item in value[key])
        for key in ("search_networks", "z2m_prefixes")
    ):
        raise DeviceError("invalid_request")
    return normalize_settings(value)


def normalize_settings(data: Mapping[str, Any]) -> ServiceSettings:
    """Keep config-entry defaults and comma-separated legacy lists unchanged."""
    networks = data.get("search_networks", [])
    prefixes = data.get("z2m_prefixes", [])
    if isinstance(networks, str):
        networks = [value.strip() for value in networks.split(",") if value.strip()]
    if isinstance(prefixes, str):
        prefixes = [value.strip() for value in prefixes.split(",") if value.strip()]
    if (
        not isinstance(networks, list)
        or len(networks) > 16
        or not isinstance(prefixes, list)
        or len(prefixes) > 8
    ):
        raise DeviceError("invalid_request")
    return {
        "search_networks": list(
            dict.fromkeys(str(validate_search_network(value)) for value in networks)
        ),
        "z2m_prefixes": list(
            dict.fromkeys(validate_topic_prefix(value) for value in prefixes)
        ),
        "announcement_prefix": validate_topic_prefix(
            data.get("announcement_prefix", "espoid")
        ),
        "firmware_base_url": (
            validate_local_origin(data["firmware_base_url"])
            if data.get("firmware_base_url")
            else ""
        ),
        "service_base_url": (
            validate_service_origin(data["service_base_url"])
            if data.get("service_base_url")
            else ""
        ),
    }


def validate_settings_metadata(value: object) -> SettingsMetadata:
    if (
        not isinstance(value, dict)
        or set(value) != {"revision", "version", "updated_at"}
        or type(value["version"]) is not int
        or not 0 <= value["version"] < 2**53
        or not isinstance(value["revision"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["revision"])
        or (value["updated_at"] is not None and not isinstance(value["updated_at"], str))
    ):
        raise DeviceError("storage_failed")
    return {
        "revision": value["revision"],
        "version": value["version"],
        "updated_at": value["updated_at"],
    }


def settings_revision(value: ServiceSettings) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_topic_prefix(value: str) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,127}", value)
        or value.endswith("/")
    ):
        raise DeviceError("invalid_topic")
    return value
