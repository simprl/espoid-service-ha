"""HA-admin-only initial setup. Passwords bypass the general request ledger."""

from aiohttp import web

from .base import View, bounded_json, error_response, require_admin
from ..const import API_PREFIX, DOMAIN
from ..domain.errors import DeviceError


class MqttSetupView(View):
    url = API_PREFIX + "/mqtt-setup/{action}"
    name = DOMAIN + ":mqtt_setup"

    async def get(self, request, action):
        require_admin(request)
        if action != "snapshot":
            raise web.HTTPNotFound()
        return web.json_response(
            self.site.mqtt_setup.snapshot(), headers={"Cache-Control": "no-store"}
        )

    async def post(self, request, action):
        require_admin(request)
        try:
            body = await bounded_json(request)
            if action == "broker":
                result = await self.site.mqtt_setup.save_broker(body)
            elif action == "start":
                result = await self.site.mqtt_setup.start(
                    body,
                    request.headers.get("X-ESPOID-Request-ID"),
                    request["hass_user"].id,
                )
            else:
                raise web.HTTPNotFound()
            return web.json_response(
                result, status=202, headers={"Cache-Control": "no-store"}
            )
        except DeviceError as error:
            return error_response(error)
