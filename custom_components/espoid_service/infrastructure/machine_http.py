"""Shared HTTP proofs for machine exchange and the existing transfer handler."""

from __future__ import annotations

import hashlib
import hmac
import time

from aiohttp import web

from ..domain.errors import DeviceError
from ..machine_wire import ZERO, context, hex_value, proof


def authenticate_request(request, *, service_id, get_binding, challenges, attempts, stopped, hello=False):
    """Check a request under the caller's node lock using its current session state."""
    if stopped:
        raise DeviceError("machine_unavailable")
    ctx = request.headers.get("X-ESPOID-Context", "")
    fields = context(ctx)
    record = get_binding(fields[2])
    if fields[0] != service_id or fields[1] != record["binding_id"]:
        raise DeviceError("machine_auth")
    key = bytes.fromhex(record["token"])
    size = request.content_length
    if request.method == "GET" and size is None:
        size = 0
    digest = request.headers.get("X-ESPOID-SHA256", "")
    kind = request.headers.get("Content-Type", "")
    signature = proof(key, False, request.method, request.path, ctx, kind, size, digest)
    received = request.headers.get("X-ESPOID-Proof", "")
    if not hex_value(received, 64) or not hmac.compare_digest(signature, received):
        raise DeviceError("machine_auth")
    if hello:
        if fields[5] != ZERO:
            raise DeviceError("machine_auth")
        window, count = attempts.get(fields[2], (0, 0))
        now = time.monotonic()
        if now - window >= 60:
            window, count = now, 0
        # A failed body parse still counts; only time/reload resets this budget.
        if count >= 32:
            raise DeviceError("machine_limited")
        attempts[fields[2]] = (window, count + 1)
    else:
        challenge = challenges.pop(fields[2], None)
        if not challenge or challenge[0] != ctx or time.monotonic() > challenge[1]:
            raise DeviceError("machine_auth")
    return fields, record, ctx, key, digest


def signed_response(request, ctx, key, data, kind="application/json"):
    digest = hashlib.sha256(data).hexdigest()
    headers = {"Content-Type": kind, "Cache-Control": "no-store", "X-ESPOID-SHA256": digest,
               "X-ESPOID-Proof": proof(key, True, request.method, request.path, ctx, kind, len(data), digest)}
    return web.Response(body=data, headers=headers)
