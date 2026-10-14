"""Offline-safe site lifecycle. No device requests, scans or commands at startup."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
import secrets
from aiohttp import web
from homeassistant.components import frontend, webhook
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN,PANEL_PATH,STATIC_PREFIX
from .client import DeviceError
from .registry import Registry
from .discovery import DiscoveryManager
from .firmware import FirmwareLibrary
from .sources import Sources
from .operations import Operations

_LOGGER=logging.getLogger(__name__)
CONFIG_SCHEMA=cv.config_entry_only_config_schema(DOMAIN)

class Site:
    def __init__(self,hass,entry):
        self.hass,self.entry=hass,entry
        self.registry=Registry(hass,entry)
        self.sources=Sources(hass,self.registry)
        self.library=FirmwareLibrary(hass.config.config_dir)
        self.operations=Operations(hass,self.registry,self.library,self.sources)
        self.discovery=DiscoveryManager()
        self.search_key=None
        self.membership_lock=asyncio.Lock()
        self.source_settings=None

    async def update(self):
        self.registry.sync()
        await self.registry.save()
        signature=(tuple(self.registry.settings["z2m_prefixes"]),self.registry.settings["announcement_prefix"])
        if signature!=self.source_settings:
            await self.sources.stop()
            self.sources=Sources(self.hass,self.registry)
            self.operations.sources=self.sources
            try:
                async with asyncio.timeout(5): await self.sources.start()
            except Exception as err:
                # A failed optional broker must not prevent service setup.
                _LOGGER.warning("Optional MQTT observations unavailable (%s)",type(err).__name__)
                await self.sources.stop()
            self.source_settings=signature

    async def stop(self,*args):
        await self.discovery.shutdown(None)
        await self.sources.stop()
        await self.operations.stop()

    async def announcement(self,hass,webhook_id,request):
        # Shared local-only bearer webhook. No direct writes to ESP on receipt.
        try:
            if request.content_length is None or request.content_length>4096:
                raise DeviceError("invalid_request")
            value=await request.json()
            if not isinstance(value,dict): raise DeviceError("invalid_request")
            self.sources.announce(value)
            return web.json_response({"ok":True})
        except (DeviceError,ValueError): return web.json_response({"ok":False},status=400)


async def async_setup(hass,config): return True

async def async_setup_entry(hass,entry):
    if entry.version!=2 or entry.minor_version>1: return False
    data=hass.data.setdefault(DOMAIN,{"registered":False,"site":None,"setup_lock":asyncio.Lock()})
    async with data["setup_lock"]:
        if data["site"] is not None and data["site"].entry.entry_id!=entry.entry_id: return False
        site=Site(hass,entry)
        await site.registry.load()
        if not data["registered"]:
            from .api import register_views
            await hass.http.async_register_static_paths([
                StaticPathConfig(STATIC_PREFIX,str(Path(__file__).parent/"frontend"),False)])
            register_views(hass)
            data["registered"]=True
        if not entry.data.get("webhook_id"):
            hass.config_entries.async_update_entry(entry,data={**entry.data,"webhook_id":secrets.token_urlsafe(32)})
        await site.update()
        webhook.async_register(hass,DOMAIN,"ESPOID service announcements",entry.data["webhook_id"],
                               site.announcement,allowed_methods=("POST",),local_only=True)
        data["site"]=site
        if PANEL_PATH not in hass.data.get(frontend.DATA_PANELS,{}):
            frontend.async_register_built_in_panel(hass,"custom",sidebar_title="ESPOID Service",sidebar_icon="mdi:tools",
                frontend_url_path=PANEL_PATH,require_admin=True,config={"_panel_custom":{
                    "name":f"{PANEL_PATH}-panel","module_url":f"{STATIC_PREFIX}/panel.js",
                    "embed_iframe":False,"trust_external":False}})
        entry.async_on_unload(entry.add_update_listener(_async_update_entry))
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP,site.stop))
        entry.runtime_data=site
    return True

async def _async_update_entry(hass,entry):
    site=hass.data[DOMAIN].get("site")
    if site and site.entry.entry_id==entry.entry_id: await site.update()

async def async_unload_entry(hass,entry):
    site=hass.data[DOMAIN].get("site")
    if site and site.entry.entry_id==entry.entry_id:
        await site.stop()
        webhook.async_unregister(hass,entry.data["webhook_id"])
        hass.data[DOMAIN]["site"]=None
        frontend.async_remove_panel(hass,PANEL_PATH)
    return True

async def async_migrate_entry(hass,entry):
    # The pilot's old per-node entries are intentionally not auto-converted.
    if entry.version!=2 or entry.minor_version>1: return False
    if entry.minor_version<1:
        hass.config_entries.async_update_entry(entry,minor_version=1)
    return True
