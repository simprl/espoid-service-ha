"""Administrator file import. Admission returns the profile entity ID only."""
from aiohttp import web

from ..const import API_PREFIX, DOMAIN
from ..domain.configuration_files_policy import FILE_BYTES, file_upload
from ..domain.errors import DeviceError
from .base import View, require_admin, error_response


class ProfileFileView(View):
    url = API_PREFIX + "/devices/{node_id}/profile/files/{file_id}"
    name = DOMAIN + ":profile_file"

    async def post(self, request, node_id, file_id):
        require_admin(request)
        try:
            if self.site.discovery.blocks(node_id):
                raise DeviceError("search_busy")
            raw = bytearray()
            async for chunk in request.content.iter_chunked(4096):
                if len(raw) + len(chunk) > FILE_BYTES:
                    raise DeviceError("file_too_large")
                raw.extend(chunk)
            content = bytes(raw)
            mime = request.headers.get("Content-Type", "")
            revision = request.headers.get("X-ESPOID-Revision", "")
            candidate, _ = file_upload(file_id, mime, content, revision)
            async def respond():
                try:
                    result = await self.site.profiles.upload(node_id, file_id, mime, content, revision)
                    return web.json_response(result, status=202, headers={"Cache-Control": "no-store"})
                except DeviceError as error:
                    return error_response(error)
            request_id = request.headers.get("X-ESPOID-Request-ID")
            if not request_id:
                raise DeviceError("invalid_request")
            return await self.site.registry.request_guard.execute(request_id,
                f"profiles/{node_id}/files/{file_id}", candidate, respond)
        except DeviceError as error:
            return error_response(error)
