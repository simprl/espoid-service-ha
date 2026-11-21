"""Connection observations and explicit commands; network probes stay separate."""

from __future__ import annotations

from aiohttp import web
from ..const import API_PREFIX, DOMAIN
from ..domain.errors import DeviceError
from .base import View, bounded_json, error_response, only, require_admin


class ConnectionsView(View):
    url = API_PREFIX + "/connections"
    name = DOMAIN + ":connections"

    async def get(self, request):
        require_admin(request)
        return web.json_response(self.site.connections.snapshot(), headers={"Cache-Control": "no-store"})


class ConnectionView(View):
    url = API_PREFIX + "/connections/{connection_id}/{action}"
    name = DOMAIN + ":connection"

    async def get(self, request, connection_id, action):
        require_admin(request)
        if action not in ("snapshot", "offer"):
            raise web.HTTPNotFound()
        try:
            snapshot = self.site.mqtt_enrollment.snapshot(connection_id, request["hass_user"].id) if action == "offer" else self.site.connections.snapshot(connection_id)
            return web.json_response(snapshot, headers={"Cache-Control": "no-store"})
        except DeviceError as error:
            return error_response(error)

    async def post(self, request, connection_id, action):
        async def execute(body):
            if action == "offer":
                only(body, ("reset",), ())
                return self.site.mqtt_enrollment.create(connection_id, request["hass_user"].id, reset=body.get("reset", False))
            fields = ("expected_revision",) if action == "start" else (
                ("confirmed",) if action in ("rebind", "service_enter", "service_exit") else ())
            only(body, fields, fields)
            return await self.site.connections.execute(connection_id, action, body, request.headers.get("X-ESPOID-Request-ID"))

        if action == "enroll":
            # The owner-bound one-use offer controls replay. Reject unexpected
            # input before any general command body hash could be persisted.
            require_admin(request)
            try:
                body = await bounded_json(request)
                result = await self.site.mqtt_enrollment.enroll(
                    connection_id, request["hass_user"].id, body,
                    request.headers.get("X-ESPOID-Request-ID"))
                return web.json_response(result, status=202, headers={"Cache-Control": "no-store"})
            except DeviceError as error:
                return error_response(error)
        if action == "configure":
            # Passwords use NetworkJobs' private keyed fingerprint, never the
            # general command ledger's unkeyed body hash.
            require_admin(request)
            try:
                body = await bounded_json(request)
                only(body, ("ssid", "password"), ("ssid", "password"))
                result = await self.site.connections.execute(connection_id, action, body, request.headers.get("X-ESPOID-Request-ID"))
                return web.json_response(result, status=202, headers={"Cache-Control": "no-store"})
            except DeviceError as error:
                return error_response(error)
        return await self.json_command(request, action=action,
            actions=("bind", "rebind", "refresh", "wake", "connect", "read", "start", "offer",
                     "service_mode_read", "service_enter", "service_exit"),
            scope="connections/" + connection_id + "/" + action, execute=execute)
