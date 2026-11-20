"""Bounded, passive context export. Never use the legacy confirming status route."""
from __future__ import annotations

import hashlib
import json
import math
import re
MAX_TRACE_LINES = 4096
MAX_TRACE_LINE_BYTES = 8192


def fields(names):
    return dict.fromkeys(names.split(), None)


IDENTITY = {
    **fields("api_version node_id family boot_id firmware_version zigbee_ieee diagnostics"),
    "transports": fields("zigbee mqtt"),
    "ota": fields("url upload confirm passive_status"),
}
STATUS = {
    **fields("ok node_id boot_id running_version runtime_transport wifi_permanent wifi_configured "
             "ha_webhook_configured init_wifi_window_ms init_zigbee_window_ms wifi_admin_remaining_ms "
             "wifi_admin_hold_extension_ms wifi_admin_hold_max_ms zigbee_factory_new_min_join_lqi "
             "zigbee_rejoin_min_join_lqi service_mode_started ap_enabled sta_enabled sta_connecting "
             "sta_connected variant_id ota_marker_configured ota_marker_sha256 ota_marker_partition ota_marker_version"),
    **fields("service_mode service_mode_saved configuration_revision restart_mode"),
    "module_selection": fields("compiled requested enabled"),
    "modules": [None],
    "wifi_ota": fields("state stage error running verification_pending verification_remaining_ms update_available "
                       "downloaded_bytes total_bytes artifact_sha256 artifact_version"),
    "recovery": fields("active reason module error"),
    "haier": fields("state phase configured uart_open waiting protocol endpoint tx_bytes rx_bytes "
                    "loops requests ok bad timeouts status_frames communication_resets "
                    "last_valid_status_age_ms last_req last_ans last_tx last_rx last_status climate_valid power_on "
                    "mode current_temperature target_temperature control_pending control_requests last_error"),
}
PROFILE = {
    **fields("ok source requiresReboot zigbeeAction requiresZigbeeReconfigure requiresZigbeeReinterview"),
    "config": {
        **fields("schema revision"),
        "serviceButtons": fields("factoryResetPin"),
        "buses": [fields("id type enabled tx rx baud dataBits parity stopBits")],
        "ioProviders": [fields("id type enabled")],
        "devices": [{
            **fields("id type enabled name"),
            "zigbee": fields("endpoint role property"),
            "hardware": {
                **fields("driver busId protocol diagnostic display sendWifiSignal answerTimeoutMs statusPollMs "
                         "activeLevel inverted debounceMs address inPin outPin"),
                "pin": fields("providerId pin"),
            },
            "control": fields("defaultChEnabled defaultDhwEnabled chMinC chMaxC defaultChSetpointC "
                              "dhwMinC dhwMaxC defaultDhwSetpointC"),
        }],
    },
}


def project(value, schema):
    """Copy known structures only; never recursively admit arbitrary module/config keys."""
    if value is None:
        return None, 0
    if schema is None:
        if type(value) in (bool, int, str) or (type(value) is float and math.isfinite(value)):
            return value, 0
        return None, 1
    if isinstance(schema, list):
        if not isinstance(value, list):
            return None, 1
        items = [project(item, schema[0]) for item in value]
        return [item[0] for item in items], sum(item[1] for item in items)
    if not isinstance(value, dict):
        return None, 1
    output, omitted = {}, len(value.keys() - schema.keys())
    for key in value.keys() & schema.keys():
        output[key], count = project(value[key], schema[key])
        omitted += count
    return output, omitted


def reject_constant(value):
    raise ValueError("nonfinite_json")


def trace_summary(raw):
    """Inspect without rewriting raw records, decoding binary or conflating boot namespaces."""
    sessions, warnings = [], set()
    current = None
    seen_sessions = {}
    inspected = 0
    for index, line in enumerate(raw.splitlines()):
        if index >= MAX_TRACE_LINES:
            warnings.add("trace_inspection_limit")
            break
        inspected += 1
        try:
            if not line or len(line) > MAX_TRACE_LINE_BYTES:
                raise ValueError()
            item = json.loads(line, parse_constant=reject_constant)
            if not isinstance(item, dict):
                raise ValueError()
            if item.get("type") == "session":
                current = None
                if (item.get("source") not in ("saved", "current")
                    or any(type(item.get(key)) is not int or not 0 <= item[key] <= 0xffffffff
                           for key in ("boot_id", "generation", "count", "overwritten"))
                    or not re.fullmatch(r"0x[0-9a-fA-F]{8}", str(item.get("firmware_id")))):
                    raise ValueError()
                key = (item["source"], item["boot_id"], item["generation"])
                current = seen_sessions.get(key)
                if current is None:
                    current = {**{key: item[key] for key in ("source", "boot_id", "generation", "firmware_id", "count", "overwritten")},
                               "sequences": set(), "duplicate_records": 0}
                    seen_sessions[key] = current
                    sessions.append(current)
                else:
                    warnings.add("duplicate_session_header")
                    if any(current[key] != item[key] for key in ("count", "overwritten", "firmware_id")):
                        warnings.add("session_header_changed")
                if item["overwritten"]:
                    warnings.add("trace_overwritten")
            else:
                sequence = item.get("sequence")
                if (current is None or item.get("source") != current["source"]
                    or type(sequence) is not int or not 0 <= sequence <= 0xffffffff
                    or type(item.get("uptime_ms")) is not int or not 0 <= item["uptime_ms"] <= 0xffffffff
                    or type(item.get("kind")) is not int or item["kind"] not in (1, 2, 3)
                    or not isinstance(item.get("hex"), str) or len(item["hex"]) > 256
                    or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", item["hex"])
                    or any(not isinstance(item.get(key), str) for key in ("driver", "device_id"))):
                    raise ValueError()
                if sequence in current["sequences"]:
                    current["duplicate_records"] += 1
                    warnings.add("duplicate_trace_records")
                current["sequences"].add(sequence)
        except (ValueError, UnicodeError, RecursionError):
            warnings.add("malformed_ndjson")
    if raw and not raw.endswith(b"\n"):
        warnings.add("trace_missing_final_newline")
    if not sessions:
        warnings.add("trace_sessions_missing")
    for session in sessions:
        sequences = sorted(session.pop("sequences"))
        session["unique_records"] = len(sequences)
        # Avoid expanding a potentially corrupt uint32 count into a Python range/set.
        start, count = session["overwritten"], session["count"]
        session["sequence_gaps"] = (len(sequences) != count or
            any(sequence != (start + offset) % 0x100000000 for offset, sequence in enumerate(sequences)))
        if session["sequence_gaps"]:
            warnings.add("trace_sequence_gaps")
    return {"sessions": sessions, "inspected_lines": inspected, "warnings": sorted(warnings),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "boot_id_namespace": "diagnostics_uint32_not_service_boot_id",
            "loss_detection_complete": False, "frame_boundaries_available": False}
