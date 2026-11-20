"""Public causes for a failed protected read; never expose exception payloads."""

from .errors import DeviceError


def status_read_error(error):
    if isinstance(error, TimeoutError):
        return "tunnel_timeout"
    if isinstance(error, DeviceError):
        return error.code if error.code in STATUS_READ_ERRORS else "machine_unavailable"
    return "cannot_connect"


STATUS_READ_ERRORS = frozenset((
    "cannot_connect", "mqtt_unavailable", "z2m_device_missing",
    "tunnel_timeout", "tunnel_failed", "tunnel_invalid", "tunnel_rejected",
    "identity_mismatch", "binding_identity_mismatch", "binding_auth",
    "binding_missing", "binding_conflict", "binding_storage", "binding_rebind_pending",
    "machine_auth", "machine_invalid", "machine_storage", "machine_unavailable",
    "invalid_response", "outcome_uncertain", "request_not_delivered", "operation_busy", "operation_unresolved",
    "service_unsupported", "service_legacy", "service_converter_required", "service_capabilities_unknown",
))
