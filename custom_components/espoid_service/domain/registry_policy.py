"""Persisted registry records and operation-history retention rules."""

from __future__ import annotations

from typing import Any

from ..const import MAX_HISTORY
from .errors import DeviceError

ACTIVE_STATES = ("prepared", "sending", "waiting", "verifying", "uncertain")


def validate_registry_records(value: object) -> dict[str, Any]:
    """Validate existing storage fields without rewriting recovery evidence."""
    if (not isinstance(value, dict) or not isinstance(value.get("locators", {}), dict)
        or not isinstance(value.get("operations", []), list)):
        raise DeviceError("storage_failed")
    records = value.get("requests", [])
    if (not isinstance(records, list) or len(records) > 200 or any(not isinstance(item, dict)
        or not isinstance(item.get("id"), str) or not isinstance(item.get("fingerprint"), str)
        or item.get("state") not in ("running", "done", "uncertain") for item in records)):
        raise DeviceError("storage_failed")
    if any(not isinstance(op, dict) or not all(isinstance(op.get(key), str)
        for key in ("id", "node_id", "action", "state", "created_at", "updated_at"))
        for op in value.get("operations", [])):
        raise DeviceError("storage_failed")
    if any(not isinstance(locator, dict) for locator in value.get("locators", {}).values()):
        raise DeviceError("storage_failed")
    return value


def retained_history(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep all unresolved operations and fill the remaining budget with recent ones."""
    active = [op for op in operations if op["state"] in ACTIVE_STATES]
    completed = [op for op in operations if op["state"] not in ACTIVE_STATES]
    remaining = max(0, MAX_HISTORY - len(active))
    keep = {op["id"] for op in active + (completed[-remaining:] if remaining else [])}
    return [op for op in operations if op["id"] in keep]
