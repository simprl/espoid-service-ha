"""Saved interruption evidence, separate from confirmed resource data."""
from copy import deepcopy
import re

from .errors import DeviceError

INTERRUPTION_ERRORS = frozenset(("outcome_uncertain", "cannot_connect", "readback_failed",
    "machine_unavailable", "machine_storage", "storage_failed", "request_cancelled"))


def interrupt(record, now, reason="operation_interrupted"):
    pending = record.get("pending")
    if not pending:
        return False
    # Keep the original change while an explicit check itself is interrupted.
    previous = record.get("interruption")
    if not previous:
        record["interruption"] = {"at": now, "pending": deepcopy(pending)}
    elif pending['action']=='check' or pending.get('job_id') or pending.get('operation_id'):
        previous['check_pending']=deepcopy(pending)
    record.update(state="uncertain", error=reason, pending=None)
    return True


def public_interruption(record, *, requires_wifi=False):
    value = record.get("interruption")
    if not value:
        return None
    pending = value["pending"]
    return {"id": pending.get("job_id") or pending.get("operation_id") or pending.get("request_id") or "unconfirmed",
            "action": pending["action"], "at": value["at"], "requires_wifi": requires_wifi}


def require_interruption(record, expected):
    value = public_interruption(record)
    if not value or value["id"] != expected:
        raise DeviceError("operation_changed")
    return record["interruption"]["pending"]


def latest_interrupted_request(record):
    interruption=record['interruption']
    latest=interruption.get('check_pending') or {}
    return latest if latest.get('job_id') or latest.get('operation_id') else interruption['pending']


def validate_interruption(value):
    if value is None:return
    if (not isinstance(value,dict) or set(value)-{'check_pending'}!={'at','pending'} or not isinstance(value['at'],str)
        or not isinstance(value['pending'],dict) or not isinstance(value['pending'].get('action'),str)):
        raise DeviceError('storage_failed')
    for pending in (value['pending'],value.get('check_pending',{})):
        if not isinstance(pending,dict):raise DeviceError('storage_failed')
        for name in ('job_id','operation_id','request_id'):
            identifier=pending.get(name)
            if identifier is not None and (not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier)):
                raise DeviceError('storage_failed')
