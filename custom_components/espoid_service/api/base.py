"""HA HTTP helpers and shared admin JSON-command handling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
import json
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from ..domain.errors import DeviceError

JsonCommand = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class View(HomeAssistantView):
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def json_command(
        self,
        request: web.Request,
        *,
        action: str,
        actions: Collection[str],
        scope: str,
        execute: JsonCommand,
        status: int = 202,
    ) -> web.Response:
        require_admin(request)
        if action not in actions:
            raise web.HTTPNotFound()
        try:
            body = await bounded_json(request)

            async def respond():
                return await _command_response(body, execute, status)

            request_id = getattr(request, "headers", {}).get("X-ESPOID-Request-ID")
            if request_id:
                return await self.site.registry.request_guard.execute(
                    request_id, scope, body, respond
                )
            return await respond()
        except DeviceError as error:
            return error_response(error)

    async def command(self, request, body, scope, callback):
        """Existing admission path for endpoints outside the JSON-command pilot."""
        request_id = getattr(request, "headers", {}).get("X-ESPOID-Request-ID")
        if not request_id or request.get("espoid_command_admitted"):
            return None

        async def admitted():
            request["espoid_command_admitted"] = True
            return await callback()

        return await self.site.registry.request_guard.execute(
            request_id, scope, body, admitted
        )

    @property
    def site(self):
        site = self.hass.data.get(DOMAIN, {}).get("site")
        if site is None:
            raise web.HTTPServiceUnavailable()
        return site


def require_admin(request):
    user = request.get("hass_user")
    if user is None or not user.is_admin:
        raise web.HTTPForbidden()


def error_response(error: DeviceError) -> web.Response:
    return web.json_response(
        {"ok": False, "error": error.code, "esp_error": error.esp_error}, status=400
    )


async def bounded_json(request):
    if "espoid_parsed_body" in request:
        return request["espoid_parsed_body"]
    raw = bytearray()
    async for chunk in request.content.iter_chunked(4096):
        if len(raw) + len(chunk) > 65536:
            raise web.HTTPRequestEntityTooLarge(
                max_size=65536, actual_size=len(raw) + len(chunk)
            )
        raw.extend(chunk)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        request["espoid_parsed_body"] = value
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise DeviceError("invalid_request") from None


def only(body, allowed, required=()):
    if set(body) - set(allowed) or not set(required) <= set(body):
        raise DeviceError("invalid_request")


async def _command_response(
    body: dict[str, Any], execute: JsonCommand, status: int
) -> web.Response:
    # Coded command errors are completed HTTP outcomes, cached by RequestGuard
    # just like successes. Parsing/admission failures remain outside this callback.
    try:
        result = await execute(body)
        return web.json_response(
            result, status=status, headers={"Cache-Control": "no-store"}
        )
    except DeviceError as error:
        return error_response(error)
