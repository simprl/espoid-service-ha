"""Passive resource snapshots, ID-only commands and saved diagnostic downloads."""
from aiohttp import web
from ..const import API_PREFIX, DOMAIN
from ..domain.errors import DeviceError
from ..domain.resource_policy import ENTITIES, CONTROL_ACTIONS
from .base import View, require_admin, only, error_response


class DeviceResourceView(View):
    url = API_PREFIX + "/devices/{node_id}/{entity}/{action}"
    name = DOMAIN + ":device_resource"

    async def get(self, request, node_id, entity, action):
        require_admin(request)
        try:
            if entity not in ENTITIES:
                raise web.HTTPNotFound()
            if action == "snapshot":
                return web.json_response(self.site.resources.snapshot(entity, node_id), headers={"Cache-Control": "no-store"})
            if entity != "diagnostics" or action != "file":
                raise web.HTTPNotFound()
            format = request.query.get("format", "bundle")
            if format not in ("bundle", "trace"):
                raise DeviceError("invalid_request")
            raw, completeness = await self.site.resources.artifact(node_id, request.query.get("artifact_id"), format == "trace")
            return web.Response(body=raw, content_type="application/zip" if format == "bundle" else "application/x-ndjson",
                headers={"Cache-Control": "no-store", "X-ESPOID-Completeness": completeness,
                         "X-Content-Type-Options": "nosniff"})
        except DeviceError as error:
            return error_response(error)

    async def post(self, request, node_id, entity, action):
        actions = command_actions(entity)
        if actions is None:
            raise web.HTTPNotFound()
        async def execute(body):
            fields = command_fields(action)
            if entity == 'equipment' and action not in ('refresh', 'resolve'):
                fields = ('expected_version', 'peer') if action in ('pair', 'connect') else ('expected_version',)
            if entity=='mqtt' and action=='save':fields=('data','expected_revision')
            only(body, fields, tuple(field for field in fields if field != "allow_variant_change"))
            if entity == "membership":
                return await self.site.membership_commands.command(node_id, action, body)
            return await self.site.resources.command(entity, node_id, action, body)
        return await self.json_command(request, action=action,
            actions=actions,
            scope=f"resources/{node_id}/{entity}/{action}", execute=execute)


def command_actions(entity):
    return {
        "membership": ("rename", "address", "remove"),
        "control": CONTROL_ACTIONS,
        "ota": ("refresh", "install", "check", "confirm", "resolve"),
        "status": ("refresh",),
        "diagnostics": ("refresh", "save"),
        "mqtt": ("refresh", "save", "check"),
        "equipment": ("refresh", "scan", "pair", "connect", "diagnostics_start", "diagnostics_cancel", "resolve"),
    }.get(entity)


def command_fields(action):
    return {
        "rename": ("name",),
        "address": ("url",),
        "remove": ("confirmed",),
        "install": ("mode", "firmware_id", "confirmed", "allow_variant_change"),
        "resolve": ("expected_revision", "confirmed"),
        "check": ("expected_revision", "confirmed"),
        "service_enter": ("confirmed",),
        "service_exit": ("confirmed",),
    }.get(action, ())
