"""Saved operation history; reading never contacts devices."""
from copy import deepcopy
from aiohttp import web
from ..const import API_PREFIX, DOMAIN
from .base import View, require_admin


class HistoryView(View):
    url = API_PREFIX + "/history"
    name = DOMAIN + ":history"

    async def get(self, request):
        require_admin(request)
        return web.json_response({"entity": "history", "id": "service", "version": self.site.registry.version,
            "operations": deepcopy(list(reversed(self.site.registry.operations)))}, headers={"Cache-Control": "no-store"})
