"""Generic configuration attachments and exact selection; no equipment or transport logic."""
from copy import deepcopy
import hashlib
import json
import re
import struct

from .errors import DeviceError

FILE_BYTES = 8192
FILE_COUNT = 4
FILE_HEADER_BYTES = 512
FILE_TRANSFER_BYTES = FILE_BYTES + FILE_HEADER_BYTES + 6
PROFILE_TRANSFER_BYTES = 6144


def file_upload(identifier, mime_type, content, revision):
    declaration({"id": identifier, "label": identifier, "mimeType": mime_type})
    if not hex_value(revision) or not isinstance(content, bytes):
        raise DeviceError("invalid_request")
    if not 0 < len(content) <= FILE_BYTES:
        raise DeviceError("file_too_large")
    header = json.dumps({"id": identifier, "mimeType": mime_type}, separators=(",", ":")).encode()
    if len(header) > FILE_HEADER_BYTES:
        raise DeviceError("invalid_request")
    candidate = {"id": identifier, "mimeType": mime_type, "length": len(content),
                 "sha256": hashlib.sha256(content).hexdigest(), "expected_revision": revision}
    return candidate, b"ECFU" + struct.pack("<H", len(header)) + header + content


def selected_files(config, confirmed, staged):
    declarations = file_declarations(config)
    previous = {item["id"]: item for item in file_declarations((confirmed or {}).get("config") or {})}
    saved = {item["id"]: item for item in (confirmed or {}).get("files", [])}
    candidates = {item["id"]: item for item in staged}
    selected = []
    for item in declarations:
        candidate = candidates.get(item["id"])
        if candidate and candidate["expected_revision"] == (confirmed or {}).get("revision") and candidate["mimeType"] == item["mimeType"]:
            selected.append(reference(candidate))
        elif item["id"] in saved and previous.get(item["id"], {}).get("mimeType") == item["mimeType"]:
            selected.append(reference(saved[item["id"]]))
        else:
            raise DeviceError("file_missing")
    return selected


def profile_transfer(value):
    from .profile_policy import profile_json
    if not isinstance(value, dict) or set(value) != {"config", "files"}:
        raise DeviceError("invalid_profile")
    profile_json(value["config"])
    file_references(value["files"])
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > PROFILE_TRANSFER_BYTES:
        raise DeviceError("profile_too_large")
    return raw


def verify_file_receipt(result, candidate, request_id):
    if not isinstance(result, dict) or set(result) != {"request_id", "file"} or result["request_id"] != request_id:
        raise DeviceError("invalid_response")
    actual = reference(result["file"])
    if actual != reference(candidate):
        raise DeviceError("readback_failed")
    return deepcopy(candidate)


def verify_file_boot(boot, current):
    if not isinstance(boot, str) or not re.fullmatch("[a-f0-9]{16}", boot):
        raise DeviceError("invalid_response")
    if current and current != boot:
        raise DeviceError("readback_failed")


def same_selection(profile, pending):
    return (profile["config"] == pending.get("profile") and
            sorted(profile.get("files", []), key=lambda item: item["id"]) ==
            sorted(pending.get("files", []), key=lambda item: item["id"]))


def file_declarations(config):
    items = config.get("files", [])
    if not isinstance(items, list) or len(items) > FILE_COUNT:
        raise DeviceError("invalid_profile")
    for item in items:
        declaration(item)
    if len({item["id"] for item in items}) != len(items):
        raise DeviceError("invalid_profile")
    return items


def declaration(item):
    if (not isinstance(item, dict) or set(item) != {"id", "label", "mimeType"}
        or not isinstance(item["id"], str) or not re.fullmatch("[A-Za-z0-9_-]{1,24}", item["id"])
        or not isinstance(item["label"], str) or not 0 < len(item["label"].encode()) <= 64
        or not isinstance(item["mimeType"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", item["mimeType"])
        or len(item["mimeType"]) > 96):
        raise DeviceError("invalid_profile")


def file_references(items):
    if not isinstance(items, list) or len(items) > FILE_COUNT:
        raise DeviceError("invalid_response")
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "length", "sha256"}:
            raise DeviceError("invalid_response")
        reference(item)
    if len({item["id"] for item in items}) != len(items):
        raise DeviceError("invalid_response")
    return items


def reference(item):
    if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
        or not re.fullmatch("[A-Za-z0-9_-]{1,24}", item["id"])
        or type(item.get("length")) is not int or not 0 < item["length"] <= FILE_BYTES
        or not hex_value(item.get("sha256"))):
        raise DeviceError("invalid_response")
    return {key: item[key] for key in ("id", "length", "sha256")}


def validate_staged_files(items):
    if not isinstance(items, list) or len(items) > FILE_COUNT:
        raise DeviceError("storage_failed")
    for item in items:
        reference(item)
        declaration({"id": item["id"], "label": item["id"], "mimeType": item.get("mimeType")})
        if not hex_value(item.get("expected_revision")):
            raise DeviceError("storage_failed")
    if len({item["id"] for item in items}) != len(items):
        raise DeviceError("storage_failed")


def hex_value(value):
    return isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value) is not None
