"""Admin-only fleet API. Fixed ESP routes; no arbitrary proxy or updater."""
from __future__ import annotations
import json
import ipaddress
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from .client import DeviceError
from .const import API_PREFIX, APP_MAX_BYTES, DOMAIN
from .model import settings


def require_admin(request):
    user=request.get("hass_user")
    if user is None or not user.is_admin: raise web.HTTPForbidden()

def error_response(err):
    return web.json_response({"ok":False,"error":err.code,"esp_error":err.esp_error},status=400)

async def bounded_json(request):
    raw=bytearray()
    async for chunk in request.content.iter_chunked(4096):
        if len(raw)+len(chunk)>65536:
            raise web.HTTPRequestEntityTooLarge(max_size=65536,actual_size=len(raw)+len(chunk))
        raw.extend(chunk)
    try:
        value=json.loads(raw)
        if not isinstance(value,dict): raise ValueError()
        return value
    except (ValueError,UnicodeError,RecursionError): raise DeviceError("invalid_request") from None

def only(body,allowed,required=()):
    if set(body)-set(allowed) or not set(required)<=set(body): raise DeviceError("invalid_request")

class View(HomeAssistantView):
    requires_auth=True
    def __init__(self,hass): self.hass=hass
    @property
    def site(self):
        site=self.hass.data.get(DOMAIN,{}).get("site")
        if site is None: raise web.HTTPServiceUnavailable()
        return site


class DevicesView(View):
    url=API_PREFIX+"/devices"
    name=DOMAIN+":devices"
    async def get(self,request):
        require_admin(request)
        return web.json_response({"devices":self.site.registry.summaries()},headers={"Cache-Control":"no-store"})
    async def post(self,request):
        require_admin(request)
        try:
            body=await bounded_json(request)
            only(body,("url","name","z2m"),("url",))
            binding=body.get("z2m")
            if binding: self.site.sources.candidate(binding)
            async with self.site.membership_lock:
                node=await self.site.registry.add(body["url"],body.get("name","ESPOID"),binding)
            return web.json_response({"ok":True,"node_id":node.node_id})
        except DeviceError as err: return error_response(err)


class SiteView(View):
    url=API_PREFIX+"/site"
    name=DOMAIN+":site"
    async def get(self,request):
        require_admin(request)
        site=self.site
        return web.json_response({"settings":site.registry.settings,
            "candidates":list(site.sources.catalog.values()),"announcements":list(site.sources.announcements.values()),
            "search":site.discovery.snapshot(site.search_key) if site.search_key else {"job":None},
            "history":site.registry.operations},headers={"Cache-Control":"no-store"})
    async def post(self,request):
        require_admin(request)
        try:
            body=await bounded_json(request)
            only(body,("firmware_base_url","search_networks","z2m_prefixes","announcement_prefix"))
            if self.site.operations.tasks: raise DeviceError("operation_busy")
            data=settings(body)
            entry=self.site.registry.entry
            self.hass.config_entries.async_update_entry(entry,data={**entry.data,**data})
            await self.site.update()
            return web.json_response({"ok":True})
        except DeviceError as err: return error_response(err)


class CatalogView(View):
    url=API_PREFIX+"/catalog/wifi"
    name=DOMAIN+":catalog_wifi"
    async def post(self,request):
        require_admin(request)
        try:
            body=await bounded_json(request)
            only(body,("prefix","ieee"),("prefix","ieee"))
            await self.site.sources.command(body,"switch_to_wifi")
            return web.json_response({"ok":True,"accepted":True})
        except DeviceError as err: return error_response(err)


class SearchView(View):
    url=API_PREFIX+"/search/{action}"
    name=DOMAIN+":search"
    async def post(self,request,action):
        require_admin(request)
        site=self.site
        try:
            body=await bounded_json(request)
            if action=="start":
                only(body,("cidr","node_id"),("cidr",))
                if body["cidr"] not in site.registry.settings["search_networks"]:
                    raise DeviceError("invalid_search_network")
                key=body.get("node_id") or "catalog"
                if key!="catalog":
                    node=site.registry.get(key)
                    if site.registry.active(key): raise DeviceError("operation_unresolved")
                    origin=node.origin
                else: origin=""
                if not origin: origin="http://"+str(next(ipaddress.ip_network(body["cidr"]).hosts()))
                result=site.discovery.start(key,origin,body["cidr"],self.hass.async_create_task)
                site.search_key=key
            elif action=="cancel":
                only(body,("job_id",),("job_id",))
                result=await site.discovery.cancel(site.search_key,body["job_id"])
            else: raise web.HTTPNotFound()
            return web.json_response(result)
        except DeviceError as err: return error_response(err)


class DeviceView(View):
    url=API_PREFIX+"/devices/{node_id}/{action}"
    name=DOMAIN+":device"
    async def get(self,request,node_id,action):
        require_admin(request)
        site=self.site
        try:
            node=site.registry.get(node_id)
            if site.discovery.blocks(node_id): raise DeviceError("search_busy")
            if action=="status": result=await site.registry.refresh(node)
            elif action=="history": result={"operations":[o for o in site.registry.operations if o["node_id"]==node_id]}
            else:
                async with node.lock:
                    async with site.registry.network_slots:
                        client=site.registry.client(node)
                        await client.verify(node_id)
                        if action=="profile": result=await client.profile()
                        elif action=="diagnostics":
                            text=await client.diagnostics()
                            return web.Response(text=text,content_type="application/x-ndjson",headers={
                                "Content-Disposition":"attachment; filename=espoid-diagnostics.ndjson",
                                "Cache-Control":"no-store"})
                        else: raise web.HTTPNotFound()
            return web.json_response(result,headers={"Cache-Control":"no-store"})
        except DeviceError as err: return error_response(err)

    async def post(self,request,node_id,action):
        require_admin(request)
        site=self.site
        try:
            body=await bounded_json(request)
            node=site.registry.get(node_id)
            async with node.lock:
                if action=="resolve":
                    only(body,("operation_id","confirmed"),("operation_id","confirmed"))
                    op=site.registry.active(node_id)
                    if not op or op["id"]!=body["operation_id"] or body["confirmed"] is not True:
                        raise DeviceError("invalid_request")
                    if op["id"] in site.operations.tasks: raise DeviceError("operation_busy")
                    await site.registry.transition(op,"closed_unverified","closed_unverified")
                    return web.json_response({"ok":True})
                if action=="confirm":
                    only(body,())
                    previous=site.registry.active(node_id)
                    status=await site.registry.refresh(node)
                    op=site.registry.active(node_id)
                    if previous and previous.get("state")=="verified":
                        return web.json_response({"ok":True,"already_confirmed":True})
                    if (not op or op["state"]!="verifying" or not status["wifi_ota"].get("verification_pending")
                        or "artifact" not in op or status.get("ota_marker_sha256")!=op["artifact"]["sha256"]):
                        raise DeviceError("artifact_mismatch")
                    await site.registry.client(node).confirm()
                    await site.registry.refresh(node)
                    return web.json_response({"ok":True})
                if action=="address":
                    only(body,("url",),("url",))
                    result=await site.registry.adopt(node_id,body["url"])
                    return web.json_response(result)
                if site.registry.active(node_id): raise DeviceError("operation_unresolved")
                if site.discovery.blocks(node_id): raise DeviceError("search_busy")
                if action=="remove":
                    only(body,("confirmed",),("confirmed",))
                    if body["confirmed"] is not True: raise DeviceError("invalid_request")
                    self.hass.config_entries.async_remove_subentry(site.registry.entry,node.subentry.subentry_id)
                    site.registry.sync()
                    await site.registry.save()
                    result={"ok":True}
                elif action=="rename":
                    only(body,("name",),("name",))
                    from .model import node_settings
                    data=node_settings({**node.subentry.data,"name":body["name"]})
                    self.hass.config_entries.async_update_subentry(site.registry.entry,node.subentry,data=data,title=data["name"])
                    site.registry.sync()
                    result={"ok":True}
                elif action=="wifi":
                    only(body,())
                    if node.identity and not node.identity["transports"]["zigbee"]: raise DeviceError("unsupported_service")
                    op=await site.registry.begin(node_id,"wifi")
                    try:
                        await site.sources.command(node.z2m,"switch_to_wifi")
                        await site.registry.transition(op,"accepted","accept")
                        result={"ok":True,"accepted":True}
                    except DeviceError:
                        await site.registry.transition(op,"uncertain")
                        raise
                elif action=="prepare":
                    only(body,())
                    result=await site.operations.prepare(node)
                elif action=="ota":
                    only(body,("mode","firmware_id"),("mode","firmware_id"))
                    result=await site.operations.start(node,body["mode"],body["firmware_id"])
                else:
                    only(body,("profile",) if action.startswith("profile_") else ())
                    async with site.registry.network_slots:
                        client=site.registry.client(node)
                        await client.verify(node_id)
                        op=None
                        if action=="profile_store":
                            await client.validate_profile(body.get("profile"))
                            op=await site.registry.begin(node_id,action)
                        elif action in ("hold","reboot_wifi","reboot_zigbee","recovery_retry"):
                            op=await site.registry.begin(node_id,action)
                        try:
                            if action=="profile_validate": result=await client.validate_profile(body.get("profile"))
                            elif action=="profile_store": result=await client.store_profile(body.get("profile"),already_validated=True)
                            elif action in ("hold","reboot_wifi","reboot_zigbee","recovery_retry"):
                                result=await client.command(action)
                                if action!="hold": node.reachable=False
                            else: raise web.HTTPNotFound()
                        except DeviceError as err:
                            if op: await site.registry.transition(op,"uncertain",err.code)
                            raise
                        if op: await site.registry.transition(op,"verified" if action=="profile_store" else "accepted","accept")
            return web.json_response(result)
        except DeviceError as err: return error_response(err)


class FirmwareView(View):
    url=API_PREFIX+"/firmware"
    name=DOMAIN+":firmware"
    async def get(self,request):
        require_admin(request)
        try:
            entries=await self.hass.async_add_executor_job(self.site.library.list)
            return web.json_response({"firmware":entries})
        except (DeviceError,OSError): return error_response(DeviceError("storage_failed"))
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
            saved=await self.hass.async_add_executor_job(self.site.library.import_image,manifest,fields["image"])
            return web.json_response({"ok":True,"firmware":saved})
        except DeviceError as err: return error_response(err)
        except (ValueError,UnicodeError,KeyError,RecursionError): return error_response(DeviceError("invalid_firmware"))
        except OSError: return error_response(DeviceError("storage_failed"))


def register_views(hass):
    for view in (DevicesView,SiteView,CatalogView,SearchView,DeviceView,FirmwareView):
        hass.http.register_view(view(hass))
