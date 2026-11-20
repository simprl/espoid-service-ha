"""Firmware library listing and operator uploads."""
from __future__ import annotations

import json
from aiohttp import web
from ..domain.errors import DeviceError
from ..const import API_PREFIX, APP_MAX_BYTES, DOMAIN
from .base import View, error_response, require_admin


class FirmwareView(View):
    url=API_PREFIX+"/firmware"
    name=DOMAIN+":firmware"
    async def get(self,request):
        require_admin(request)
        try:
            return web.json_response(await self.site.firmware_resource.snapshot(),headers={"Cache-Control":"no-store"})
        except (DeviceError,OSError): return error_response(DeviceError("storage_failed"))

class FirmwareImportView(View):
    url=API_PREFIX+"/firmware/import"
    name=DOMAIN+":firmware_import"

    async def post(self,request):
        require_admin(request)
        try:
            fields={}
            reader=await request.multipart()
            async for part in reader:
                if part.name not in ("manifest","image") or part.name in fields: raise DeviceError("invalid_firmware")
                limit=APP_MAX_BYTES if part.name=="image" else 4096
                raw=bytearray()
                while chunk:=await part.read_chunk(8192):
                    if len(raw)+len(chunk)>limit: raise DeviceError("invalid_firmware")
                    raw.extend(chunk)
                fields[part.name]=bytes(raw)
            if set(fields)!={"manifest","image"}: raise DeviceError("invalid_firmware")
            manifest=json.loads(fields["manifest"])
            result=await self.site.firmware_resource.import_image(manifest,fields["image"])
            return web.json_response(result,status=202,headers={"Cache-Control":"no-store"})
        except DeviceError as err: return error_response(err)
        except (ValueError,UnicodeError,KeyError,RecursionError): return error_response(DeviceError("invalid_firmware"))
        except OSError: return error_response(DeviceError("storage_failed"))
