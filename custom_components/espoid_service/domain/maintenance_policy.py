"""Terminal maintenance-result decisions; no transport, storage or record mutation."""

from __future__ import annotations

from typing import Literal


def maintenance_result_state(phase_id: int, result: int) -> MaintenanceResultState:
    """Interpret a terminal report already checked by its protocol handler."""
    if phase_id == 4:
        return "uncertain"
    return "verified" if result in (0, 8) else "failed"


def maintenance_result_message(state: MaintenanceResultState, result: int) -> str:
    """Use the final evidence-adjusted state; reboot-required keeps its priority."""
    return "machine_reboot_required" if result == 8 else "machine_" + state


MaintenanceResultState = Literal["verified", "failed", "uncertain"]
