"""Profile JSON, confirmed revisions and durable-record rules, independent of HA."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..const import MAX_NODES, PROFILE_MAX_BYTES
from .errors import DeviceError
from .interruption_policy import validate_interruption
from .configuration_files_policy import file_references, validate_staged_files, verify_file_boot

ACTIVE_STATES = ("refreshing", "saving", "validating", "uploading")


def profile_json(value: object) -> bytes:
    if not isinstance(value, dict):
        raise DeviceError("invalid_profile")
    try:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as err:
        raise DeviceError("invalid_profile") from err
    if len(data) > PROFILE_MAX_BYTES:
        raise DeviceError("profile_too_large")
    return data


def confirmed_profile(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("source") not in ("stored", "default"):
        raise DeviceError("invalid_response")
    config = value.get("config")
    if config is not None:
        profile_json(config)
    elif value["source"] != "default":
        raise DeviceError("invalid_response")
    # Older ESP HTTP APIs do not supply a revision. Canonicalize their observation.
    revision = value.get("revision") or hashlib.sha256(
        json.dumps([value["source"], config], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
        raise DeviceError("invalid_response")
    if "files" in value: file_references(value["files"])
    return {"source": value["source"], "config": config, "revision": revision,
            "requiresReboot": value.get("requiresReboot", False),
            **{key: value[key] for key in ('zigbeeAction', 'validation', 'files') if key in value}}


def validate_profile_records(value: object) -> dict[str, Any]:
    """Check persisted records without normalizing or discarding recovery fields."""
    if not isinstance(value, dict) or len(value) > MAX_NODES:
        raise DeviceError("storage_failed")
    for node_id, record in value.items():
        if (not isinstance(record, dict) or record.get("id") != node_id
            or record.get("entity") != "profile" or type(record.get("version")) is not int
            or record["version"] < 0 or record.get("state") not in (*ACTIVE_STATES, "idle", "error", "uncertain")):
            raise DeviceError("storage_failed")
        validate_interruption(record.get('interruption'))
        validate_staged_files(record.get("staged_files", []))
        if record.get("staged_boot") is not None: verify_file_boot(record["staged_boot"],None)
        if record.get("data") is not None:
            confirmed_profile(record["data"])
        if record.get("desired") is not None:
            profile_json(record["desired"])
        pending = record.get("pending")
        if record["state"] in ACTIVE_STATES and not pending:
            raise DeviceError("storage_failed")
        if pending and (not isinstance(pending, dict) or pending.get("action") not in ("refresh", "save", "validate", "check", "upload")):
            raise DeviceError("storage_failed")
        if pending:
            if pending["action"] == "upload": validate_staged_files([pending.get("file")])
            if "files" in pending: file_references(pending["files"])
            if pending["action"] in ('save','validate'):
                profile_json(pending.get("profile"))
            if pending.get("job_id") is not None and (
                not isinstance(pending["job_id"], str) or len(pending["job_id"]) != 32
                or any(c not in "0123456789abcdef" for c in pending["job_id"])):
                raise DeviceError("storage_failed")
    return value
