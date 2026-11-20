"""Transient human-authorized HTTP access during initial MQTT setup."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from http.cookies import SimpleCookie

import aiohttp

from ...domain.address_policy import validate_local_origin
from ...domain.errors import DeviceError
from ...model import identity


class AdminClient:
    def __init__(self, origin, node_id, password):
        self.origin, self.node_id = validate_local_origin(origin), node_id
        self.password, self.cookie, self.csrf, self.boot = password, "", "", ""
        self.session = aiohttp.ClientSession(
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
            auto_decompress=False,
            timeout=aiohttp.ClientTimeout(total=10, connect=3),
        )

    async def close(self):
        try:
            if self.cookie and self.csrf:
                await self.send("/api/admin/session", "DELETE")
        except DeviceError:
            pass
        finally:
            self.password, self.cookie, self.csrf = "", "", ""
            await self.session.close()

    async def identify(self):
        value = await self.send("/api/service/identity")
        found = identity(value)
        if found["node_id"] != self.node_id:
            raise DeviceError("identity_mismatch")
        if (
            not value.get("transports", {}).get("mqtt")
            or value.get("service_mqtt") != 1
        ):
            raise DeviceError("service_unsupported")
        if value["boot_id"] != self.boot:
            self.cookie, self.csrf, self.boot = "", "", value["boot_id"]
        return value

    async def login(self):
        await self.identify()
        value = await self.send(
            "/api/admin/session",
            "POST",
            {"username": "espoid", "password": self.password},
        )
        if (
            value.get("authenticated") is not True
            or not self.cookie
            or not value.get("csrf")
        ):
            raise DeviceError("admin_access_unavailable")
        self.csrf = value["csrf"]

    async def item(self, resource):
        if resource not in ("status", "mqtt", "profile"):
            raise DeviceError("invalid_request")
        if not self.csrf:
            await self.login()
        value = await self.send("/api/resources/" + resource)
        if (
            value.get("id") != self.node_id
            or value.get("entity") != resource
            or not isinstance(value.get("data"), dict)
        ):
            raise DeviceError("invalid_response")
        return value

    async def command(self, action, revision=None):
        if action not in ("service_enter", "service_exit", "restart"):
            raise DeviceError("invalid_request")
        status = (await self.item("status"))["data"]
        request = {
            "resource": "system",
            "action": action,
            "request_id": secrets.token_hex(16),
            "boot_id": status["boot_id"],
            "expected_mode": status["restart_mode"],
        }
        if revision is not None:
            request["expected_revision"] = revision
        await self.send("/api/resources/command", "POST", request)
        return status["boot_id"]

    async def wait_boot(self, previous):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                value = await self.identify()
                if value["boot_id"] != previous:
                    await self.login()
                    return
            except DeviceError as error:
                if error.code not in ("cannot_connect", "invalid_response"):
                    raise
            await asyncio.sleep(1)
        raise DeviceError("setup_restart_unconfirmed")

    async def save_mqtt(self, request_id, revision, data):
        return await self.send(
            "/api/resources/mqtt",
            "POST",
            {
                "resource": "mqtt",
                "action": "save",
                "request_id": request_id,
                "expected_revision": revision,
                "data": data,
            },
        )

    async def authorize(self, offer):
        return await self.send(
            "/api/service/enrollment",
            "POST",
            {
                "v": 1,
                "node_id": self.node_id,
                "service_id": offer["service_id"],
                "nonce": offer["nonce"],
                "username": "espoid",
                "password": self.password,
            },
        )

    async def send(self, path, method="GET", body=None):
        headers = {"Origin": self.origin, "Accept": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.csrf and method != "GET":
            headers["X-ESPOID-CSRF"] = self.csrf
        try:
            async with self.session.request(
                method,
                self.origin + path,
                json=body,
                headers=headers,
                allow_redirects=False,
            ) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(4096):
                    if len(raw) + len(chunk) > 16384:
                        raise DeviceError("invalid_response")
                    raw.extend(chunk)
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise DeviceError("invalid_response")
                if response.status == 401:
                    raise DeviceError("sign_in_required")
                if (
                    response.status >= 300
                    or value.get("error")
                    or value.get("ok") is False
                ):
                    code = value.get("error")
                    allowed = {
                        "access_unavailable",
                        "try_later",
                        "revision_conflict",
                        "operation_busy",
                        "binding_identity_mismatch",
                        "service_mode_required",
                        "mqtt_settings_invalid",
                    }
                    raise DeviceError(
                        code if code in allowed else "setup_device_rejected"
                    )
                cookie = SimpleCookie()
                cookie.load(response.headers.get("Set-Cookie", ""))
                if "espoid_session" in cookie:
                    token = cookie["espoid_session"].value
                    if len(token) != 64 or any(
                        c not in "0123456789abcdef" for c in token
                    ):
                        raise DeviceError("invalid_response")
                    self.cookie = "espoid_session=" + token
                return value
        except (aiohttp.ClientError, TimeoutError):
            raise DeviceError("cannot_connect") from None
        except (ValueError, UnicodeError, RecursionError):
            raise DeviceError("invalid_response") from None
