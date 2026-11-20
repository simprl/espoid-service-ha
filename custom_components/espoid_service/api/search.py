"""Passive search snapshot and explicit backend-owned discovery commands."""

from __future__ import annotations

from aiohttp import web
from ..const import API_PREFIX, DOMAIN
from .base import View, only, require_admin


class SearchView(View):
    url = API_PREFIX + "/search/{action}"
    name = DOMAIN + ":search"

    async def get(self, request, action):
        require_admin(request)
        if action != "snapshot":
            raise web.HTTPNotFound()
        return web.json_response(
            self.site.search_resource.snapshot(), headers={"Cache-Control": "no-store"}
        )

    async def post(self, request, action):
        async def execute(body):
            resource = self.site.search_resource
            if action == "start":
                only(body, ("cidr", "node_id"), ("cidr",))
                return resource.start(body["cidr"], body.get("node_id", ""))
            if action == "cancel":
                only(body, ("expected_revision",), ("expected_revision",))
                return await resource.cancel(body["expected_revision"])
            only(body, ("expected_revision", "node_ids"), ("expected_revision", "node_ids"))
            return await resource.add(body["expected_revision"], body["node_ids"])

        return await self.json_command(
            request, action=action, actions=("start", "cancel", "add"),
            scope="search/" + action, execute=execute,
        )
