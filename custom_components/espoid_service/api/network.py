"""Wi-Fi provisioning and authenticated device probes."""
from __future__ import annotations

from aiohttp import web
from ..domain.errors import DeviceError
from ..const import API_PREFIX, DOMAIN
from .base import View, bounded_json, error_response


class NetworkProbeView(View):
    url=API_PREFIX+"/network/probe"
    name=DOMAIN+":network_probe"
    requires_auth=False
    async def post(self,request):
        try:
            if request.content_length is None or request.content_length>1024:
                raise DeviceError('network_auth')
            body=await bounded_json(request)
            result=await self.site.network.probe(body)
            return web.json_response(result,headers={'Cache-Control':'no-store'})
        except DeviceError: return web.json_response({'ok':False},status=403)
