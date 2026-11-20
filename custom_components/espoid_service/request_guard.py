"""Bounded request-ID admission. Persist fingerprints, never command payloads/secrets."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
from aiohttp import web
from .domain.errors import DeviceError

MAX_REQUESTS = 200


class RequestGuard:
    def __init__(self, registry):
        self.registry = registry
        self.lock = asyncio.Lock()
        self.responses = {}

    async def execute(self, request_id, scope, body, callback):
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-z0-9:-]{1,160}", request_id):
            raise DeviceError("invalid_request")
        try:
            fingerprint = hashlib.sha256(json.dumps([scope, body], sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        except (ValueError, TypeError, RecursionError):
            raise DeviceError("invalid_request") from None
        async with self.lock:
            records = self.registry.request_records
            found = next((item for item in records if item["id"] == request_id), None)
            if found:
                if found["fingerprint"] != fingerprint:
                    raise DeviceError("request_conflict")
                if found["state"] == "running":
                    raise DeviceError("request_busy")
                cached = self.responses.get(request_id)
                if cached:
                    return web.Response(body=cached[0], status=cached[1], content_type="application/json",
                        headers={"Cache-Control": "no-store", "X-ESPOID-Replayed": "true"})
                # After a restart, do not reconstruct or replay even completed commands.
                raise DeviceError("request_uncertain")
            while len(records) >= MAX_REQUESTS:
                completed = next((item for item in records if item["state"] != "running"), None)
                if completed is None:
                    raise DeviceError("operation_busy")
                records.remove(completed)
                self.responses.pop(completed["id"], None)
            record = {"id": request_id, "fingerprint": fingerprint, "state": "running"}
            records.append(record)
            # Durable admission precedes any ESP/MQTT write.
            await self.registry.save()
        try:
            response = await callback()
        except BaseException:
            record["state"] = "uncertain"
            await self.registry.save()
            raise
        record["state"] = "done"
        # Only volatile response bytes; no URLs, status snapshots or bodies in Store.
        self.responses[request_id] = (response.body, response.status)
        await self.registry.save()
        return response
