"""Bounded HTTP client for the shipped temporary Wi-Fi service API."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .const import DIAGNOSTICS_MAX_BYTES, PROFILE_MAX_BYTES, STATUS_MAX_BYTES


class DeviceError(Exception):
    """A stable error code; never expose an upstream URL or exception text."""

    def __init__(self, code: str, esp_error: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.esp_error = esp_error


def local_url(value: str) -> str:
    """Accept explicit local IPv4 origins, without credentials or subpaths."""
    if not isinstance(value, str) or len(value) > 200 or any(ord(char) < 32 for char in value):
        raise DeviceError("invalid_url")
    try:
        parsed = urlsplit(value.strip() if "://" in value else f"http://{value.strip()}")
        address = ipaddress.IPv4Address(parsed.hostname or "")
        port = parsed.port
    except ValueError as err:
        raise DeviceError("invalid_url") from err
    if (parsed.scheme != "http" or not address.is_private or address.is_loopback
            or address.is_link_local or address.is_unspecified or address.is_multicast
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)):
        raise DeviceError("invalid_url")
    return f"http://{address}" + (f":{port}" if port and port != 80 else "")


def profile_json(value: Any) -> bytes:
    if not isinstance(value, dict):
        raise DeviceError("invalid_profile")
    try:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as err:
        raise DeviceError("invalid_profile") from err
    if len(data) > PROFILE_MAX_BYTES:
        raise DeviceError("profile_too_large")
    return data


class DeviceClient:
    def __init__(self, session: aiohttp.ClientSession, origin: str) -> None:
        self.session = session
        self.origin = local_url(origin)
        self.lock = asyncio.Lock()

    async def request(self, method: str, path: str, *, body: bytes | None = None,
                      form: dict[str, str] | None = None, limit: int = STATUS_MAX_BYTES,
                      redirect_ok: bool = False, text: bool = False) -> Any:
        try:
            async with self.session.request(
                method, self.origin + path, data=form if form is not None else body,
                headers={"Content-Type": "application/json"} if body is not None else None,
                timeout=aiohttp.ClientTimeout(total=10, connect=3), allow_redirects=False,
            ) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    if len(raw) + len(chunk) > limit:
                        raise DeviceError("response_too_large")
                    raw.extend(chunk)
                if response.status == 303 and redirect_ok:
                    if response.headers.get("Location") != "/":
                        raise DeviceError("invalid_response")
                    return {"ok": True, "accepted": True}
                if response.status != 200:
                    esp_error = None
                    try:
                        error = json.loads(raw).get("error", "")
                        if isinstance(error, str) and error.startswith("ESP_") and len(error) < 80:
                            esp_error = error
                    except (ValueError, AttributeError):
                        pass
                    raise DeviceError("no_diagnostics" if response.status == 404 and path == "/api/diagnostics"
                                      else "device_rejected", esp_error)
                if text:
                    return raw.decode("utf-8", errors="strict")
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("ok") is False:
                    raise DeviceError("device_rejected")
                return data
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DeviceError("cannot_connect") from err
        except (UnicodeError, ValueError, RecursionError) as err:
            raise DeviceError("invalid_response") from err

    async def status(self) -> dict:
        status = await self.request("GET", "/api/config")
        if not isinstance(status.get("running_version"), str) or "wifi_admin_remaining_ms" not in status:
            raise DeviceError("invalid_response")
        if any(key in status and not isinstance(status[key], dict) for key in ("haier", "wifi_ota", "recovery")):
            raise DeviceError("invalid_response")
        return status

    async def profile(self) -> dict:
        return await self.request("GET", "/api/device-config")

    async def validate_profile(self, profile: dict) -> dict:
        return await self.request("POST", "/api/device-config/validate", body=profile_json(profile))

    async def store_profile(self, profile: dict) -> dict:
        data = profile_json(profile)
        await self.request("POST", "/api/device-config/validate", body=data)
        result = await self.request("POST", "/api/device-config", body=data)
        readback = await self.profile()
        if readback.get("source") != "stored" or readback.get("config") != profile:
            raise DeviceError("readback_failed")
        return {**result, "readback_verified": True}

    async def diagnostics(self) -> str:
        return await self.request("GET", "/api/diagnostics", limit=DIAGNOSTICS_MAX_BYTES, text=True)

    async def command(self, action: str) -> dict:
        paths = {"hold": "/api/admin/hold", "reboot_wifi": "/api/reboot/wifi",
                 "reboot_zigbee": "/api/reboot/zigbee", "recovery_retry": "/api/recovery/retry"}
        if action not in paths:
            raise DeviceError("invalid_action")
        # Reboot routes acknowledge with plain text before resetting, not JSON.
        if action == "hold":
            return await self.request("POST", paths[action])
        await self.request("POST", paths[action], text=True)
        return {"ok": True, "accepted": True}

    async def set_manifest(self, url: str) -> None:
        await self.request("POST", "/config/save", form={"ota_url": url}, redirect_ok=True)
        if (await self.status()).get("ota_manifest_url") != url:
            raise DeviceError("readback_failed")

    async def install(self) -> dict:
        return await self.request("POST", "/ota/install", redirect_ok=True)
