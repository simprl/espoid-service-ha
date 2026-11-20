"""OTA observation policy: decide the next state from existing device status."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypedDict


def evaluate_ota_status(
    operation: Mapping[str, Any] | None, status: Mapping[str, Any]
) -> OtaDecision | None:
    """Return a state/message decision without changing records or confirming OTA."""
    if not operation or "artifact" not in operation or operation["state"] in ("prepared", "sending"):
        return None

    ota = status["wifi_ota"]
    artifact = operation["artifact"]
    matches_artifact = (
        status.get("ota_marker_configured") is True
        and status.get("ota_marker_sha256") == artifact["sha256"]
        and bool(artifact.get("version"))
        and status.get("running_version") == artifact["version"]
    )
    has_rebooted = bool(operation.get("before_boot_id")) and status.get("boot_id") != operation["before_boot_id"]
    was_reinstalled = operation.get("before_marker_sha256") != artifact["sha256"] or (
        bool(operation.get("before_marker_partition"))
        and status.get("ota_marker_partition") != operation["before_marker_partition"]
    )

    if ota.get("state") == "failed":
        return {"state": "failed", "message": str(ota.get("message", ""))[:160]}
    if (
        operation["action"] in ("ota_z2m", "ota_url")
        and ota.get("state") == "skipped"
        and matches_artifact
        and ota.get("artifact_sha256") == artifact["sha256"]
        and status["running_version"] == artifact["version"]
        and not ota.get("verification_pending")
        and not ota.get("running")
    ):
        # An already-running digest is a terminal no-op, not a new installation.
        return {"state": "already_current", "message": "already_current"}
    if matches_artifact and has_rebooted and was_reinstalled:
        if not ota.get("verification_pending") and not ota.get("running"):
            return {"state": "verified", "message": ""}
        if ota.get("verification_pending"):
            return {"state": "verifying", "message": ""}
    return None


class OtaDecision(TypedDict):
    state: Literal["failed", "already_current", "verified", "verifying"]
    message: str
