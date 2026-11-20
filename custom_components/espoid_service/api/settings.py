"""Saved Service settings snapshot and save endpoints."""
from __future__ import annotations

from aiohttp import web
from ..domain.errors import DeviceError
from ..const import API_PREFIX, DOMAIN
from .base import View, only, require_admin


class SettingsView(View):
    url = API_PREFIX + "/settings/{action}"
    name = DOMAIN + ":settings"

    async def get(self, request, action):
        require_admin(request)
        if action != "snapshot":
            raise web.HTTPNotFound()
        return web.json_response(
            self.site.settings_resource.snapshot(), headers={"Cache-Control": "no-store"}
        )

    async def post(self, request, action):
        return await self.json_command(
            request,
            action=action,
            actions=("save",),
            scope="settings/save",
            execute=self._save,
        )

    async def _save(self, body):
        only(body, ("settings", "expected_revision"), ("settings", "expected_revision"))
        if not isinstance(body["expected_revision"], str):
            raise DeviceError("invalid_request")
        return await self.site.settings_resource.save(
            body["settings"], body["expected_revision"]
        )
