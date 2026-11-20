"""Device profile snapshots and resource commands."""
from __future__ import annotations

from aiohttp import web
from ..domain.errors import DeviceError
from ..const import API_PREFIX, DOMAIN
from .base import View, error_response, only, require_admin


class ProfileView(View):
    url = API_PREFIX + "/devices/{node_id}/profile/{action}"
    name = DOMAIN + ":profile_snapshot"

    async def get(self, request, node_id, action):
        require_admin(request)
        if action != "snapshot":
            raise web.HTTPNotFound()
        try:
            return web.json_response(
                self.site.profiles.snapshot(node_id), headers={"Cache-Control": "no-store"}
            )
        except DeviceError as error:
            return error_response(error)

    async def post(self, request, node_id, action):
        return await self.json_command(
            request,
            action=action,
            actions=("refresh", "save", "validate", "check"),
            scope=f"profiles/{node_id}/{action}",
            execute=lambda body: self._command(node_id, action, body),
        )

    async def _command(self, node_id, action, body):
        if action == "refresh":
            only(body, ())
        elif action=='check':
            only(body,('expected_revision','confirmed'),('expected_revision','confirmed'))
            if body['confirmed'] is not True:raise DeviceError('invalid_request')
        elif action == "save":
            only(body, ("profile", "expected_revision", "expected_version"), ("profile", "expected_revision"))
        else:
            only(body, ("profile", "expected_revision"), ("profile",))
        if self.site.discovery.blocks(node_id):
            raise DeviceError("search_busy")
        return await self.site.profiles.command(
            node_id, action, body.get("profile"), body.get("expected_revision"), body.get("expected_version")
        )
