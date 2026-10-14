"""Identity-checked passive maintenance and one-shot streaming app uploads."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
import aiohttp
from .client import DeviceClient, DeviceError
from .service_contract import PATHS


class ServiceClient(DeviceClient):
    async def identity(self):
        from .model import identity
        return identity(await self.request("GET", PATHS["IDENTITY"]))

    async def verify(self, expected):
        value = await self.identity()
        if value["node_id"] != expected:
            raise DeviceError("identity_mismatch")
        return value

    async def status(self):
        value = await self.request("GET", PATHS["STATUS"])
        from .model import node_id
        node_id(value.get("node_id"))
        ota=value.get("wifi_ota")
        if (not re.fullmatch(r"[a-f0-9]{16}",str(value.get("boot_id")))
            or not re.fullmatch(r"0x[a-f0-9]{8}",str(value.get("running_version")))
            or not isinstance(ota,dict) or any(type(ota.get(k)) is not bool for k in ("running","verification_pending"))
            or type(value.get("ota_marker_configured")) is not bool):
            raise DeviceError("invalid_response")
        if value["ota_marker_configured"] and not re.fullmatch(r"[a-f0-9]{64}",str(value.get("ota_marker_sha256"))):
            raise DeviceError("invalid_response")
        return value

    async def confirm(self):
        return await self.request("POST", PATHS["CONFIRM"])

    async def set_manifest(self, url):
        await self.request("POST", "/config/save", form={"ota_url": url}, redirect_ok=True)
        if (await self.status()).get("ota_manifest_url") != url:
            raise DeviceError("readback_failed")

    async def upload(self, path: Path, manifest: dict, progress):
        artifact = manifest["artifact"]
        async def chunks():
            sent = 0
            file = await asyncio.to_thread(path.open, "rb")
            try:
                while block := await asyncio.to_thread(file.read, 16384):
                    sent += len(block)
                    progress(sent, artifact["size"])
                    yield block
            finally:
                await asyncio.to_thread(file.close)
        try:
            async with self.session.post(self.origin + PATHS["UPLOAD"], data=chunks(),
                headers={"Content-Type":"application/octet-stream", "Content-Length":str(artifact["size"]),
                         "X-Firmware-Family":manifest["family"], "X-Firmware-Version":manifest["version"],
                         "X-Firmware-SHA256":artifact["sha256"]}, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=130, connect=3)) as response:
                raw = bytearray()
                async for block in response.content.iter_chunked(1024):
                    if len(raw)+len(block)>4096: raise DeviceError("invalid_response")
                    raw.extend(block)
                if response.status != 200: raise DeviceError("device_rejected")
                value = json.loads(raw)
                if not isinstance(value, dict) or value.get("installed") is not True:
                    raise DeviceError("invalid_response")
                return value
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DeviceError("outcome_uncertain") from err
        except (ValueError, UnicodeError) as err:
            raise DeviceError("invalid_response") from err
