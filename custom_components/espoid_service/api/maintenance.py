"""Authenticated device exchange and file-transfer endpoints."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time

from aiohttp import web
from ..domain.errors import DeviceError
from ..const import API_PREFIX, DOMAIN
from ..infrastructure.machine_http import authenticate_request, signed_response
from ..machine_wire import ZERO, context, decoded, encoded, hex_value, proof, validate_status
from .base import View


class MachineExchangeView(View):
    url=API_PREFIX+'/device/exchange'
    name=DOMAIN+':machine_exchange'
    requires_auth=False
    async def post(self,request):
        try:return await _exchange(self.site.maintenance,request)
        except DeviceError as err:return web.json_response({'ok':False,'error':err.code},status=429 if err.code=='machine_limited' else 401 if err.code in ('machine_auth','binding_missing') else 400,headers={'Cache-Control':'no-store'})


class MachineTransferView(View):
    url=API_PREFIX+'/device/transfers/{job_id}'
    name=DOMAIN+':machine_transfer'
    requires_auth=False
    async def get(self,request,job_id):
        try:return await _transfer(self.site.maintenance,request,job_id)
        except (DeviceError,OSError) as err:
            return web.json_response({'ok':False,'error':err.code if isinstance(err,DeviceError) else 'machine_storage'},status=400,headers={'Cache-Control':'no-store'})
    async def post(self,request,job_id):return await self.get(request,job_id)


async def _exchange(maintenance, request):
    if request.content_length is None or not 0 < request.content_length <= 4096:
        raise DeviceError("machine_invalid")
    fields = context(request.headers.get("X-ESPOID-Context", ""))
    hello = fields[5] == ZERO
    async with maintenance.node_lock(fields[2]):
        fields, record, ctx, key, digest = authenticate_request(
            request, service_id=maintenance.bindings.service_id, get_binding=maintenance.binding,
            challenges=maintenance.challenges, attempts=maintenance.attempts,
            stopped=maintenance.stopped, hello=hello)
        raw = await request.read()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise DeviceError("machine_auth")
        body = decoded(raw)
        if hello:
            if body != {"phase": "hello"}:
                raise DeviceError("machine_invalid")
            server = secrets.token_hex(32)
            maintenance.challenges[fields[2]] = (":".join(fields[:5] + [server]), time.monotonic() + 30)
            return signed_response(request, ctx, key, encoded({"challenge": server}))
        if isinstance(body, dict) and body.get('phase') == 'resource':
            maintenance.observe_boot(fields[2], fields[3])
            result = maintenance.resource_channel.poll(fields[2], record['binding_id'], body)
            return signed_response(request, ctx, key, encoded(result))
        status, report = _poll_data(body, fields[2], fields[3])
        result = await maintenance.poll(fields[2], record["binding_id"], status, report)
        # The service returns the saved descriptor; hexadecimal framing is HTTP wire work.
        result = {**result, "job": result["job"].encode("ascii").hex()}
        return signed_response(request, ctx, key, encoded(result))


async def _transfer(maintenance, request, identifier):
    if not hex_value(identifier, 32):
        raise DeviceError("machine_invalid")
    fields = context(request.headers.get("X-ESPOID-Context", ""))
    async with maintenance.node_lock(fields[2]):
        fields, record, ctx, key, digest = authenticate_request(
            request, service_id=maintenance.bindings.service_id, get_binding=maintenance.binding,
            challenges=maintenance.challenges, attempts=maintenance.attempts, stopped=maintenance.stopped)
        job = maintenance.transfer_job(fields[2], record["binding_id"], identifier)
        if request.method == "GET":
            if request.content_length not in (0, None) or digest != hashlib.sha256(b"").hexdigest():
                raise DeviceError("machine_invalid")
            return await _download(maintenance, job, request, ctx, key)
        return await _upload(maintenance, job, request, ctx, key, digest)


async def _download(maintenance, job, request, ctx, key):
    path, expected_size, expected_sha = await maintenance.download_source(job)
    # Verify before sending authenticated headers, then stream without buffering OTA.
    size, sha = await maintenance.files.identity(path)
    if (size, sha) != (expected_size, expected_sha):
        raise DeviceError("machine_storage")
    kind = "application/octet-stream"
    response = web.StreamResponse(headers={"Content-Type": kind, "Content-Length": str(size), "Cache-Control": "no-store",
        "X-ESPOID-SHA256": sha, "X-ESPOID-Proof": proof(key, True, "GET", request.path, ctx, kind, size, sha)})
    await response.prepare(request)
    async with maintenance.files.reader(path) as file:
        async with asyncio.timeout(120):
            while chunk := await file.read(8192):
                await response.write(chunk)
                maintenance.progress(job, len(chunk), size)
    await response.write_eof()
    return response


async def _upload(maintenance, job, request, ctx, key, digest):
    limit = maintenance.upload_limit(job)
    if request.content_length is None or not 0 < request.content_length <= limit:
        raise DeviceError("machine_invalid")
    digest_actual = hashlib.sha256()
    received = 0
    async with maintenance.files.receive(job["id"]) as file:
        async with asyncio.timeout(120):
            async for chunk in request.content.iter_chunked(8192):
                received += len(chunk)
                if received > request.content_length:
                    raise DeviceError("machine_invalid")
                digest_actual.update(chunk)
                await file.write(chunk)
                maintenance.progress(job, len(chunk), request.content_length)
        if received != request.content_length or digest_actual.hexdigest() != digest:
            raise DeviceError("machine_auth")
    await maintenance.complete_upload(job, received, digest, boot=context(ctx)[3])
    return signed_response(request, ctx, key, encoded({"ok": True}))


def _poll_data(body, node_id, boot_id):
    if (not isinstance(body, dict) or set(body) != {"phase", "state", "job_id", "seq", "phase_id", "result", "flags"}
            or body["phase"] != "poll"):
        raise DeviceError("machine_invalid")
    try:
        status = decoded(bytes.fromhex(body["state"]))
    except (ValueError, TypeError):
        raise DeviceError("machine_invalid") from None
    validate_status(status, node_id, boot_id)
    if (len(body["state"]) > 3072 or not isinstance(body["job_id"], str)
            or (body["job_id"] and not hex_value(body["job_id"], 32))
            or any(type(body[k]) is not int for k in ("seq", "phase_id", "result", "flags"))):
        raise DeviceError("machine_invalid")
    report = {key: body[key] for key in ("job_id", "seq", "phase_id", "result", "flags")}
    return status, report
