"""Saved device catalog and enrollment HTTP boundary."""
from __future__ import annotations

from aiohttp import web
from ..const import API_PREFIX, DOMAIN
from .base import View, only, require_admin


class DevicesView(View):
    url=API_PREFIX+"/devices"
    name=DOMAIN+":devices"
    async def get(self,request):
        require_admin(request)
        return web.json_response({"devices":self.site.registry.summaries(), "version":self.site.registry.version},headers={"Cache-Control":"no-store"})
    async def post(self,request):
        async def execute(body):
            only(body,("url","name","z2m"),("url",))
            return await self.site.enrollment.add(body)
        return await self.json_command(request, action="add", actions=("add",), scope="devices/add", execute=execute)
