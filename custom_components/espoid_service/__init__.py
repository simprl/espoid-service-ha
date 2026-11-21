"""Offline-safe site lifecycle. No device requests, scans or commands at startup."""
from __future__ import annotations
import asyncio
import hashlib
import logging
from functools import partial
from pathlib import Path
import secrets
from aiohttp import web
from homeassistant.components import frontend, webhook
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN,PANEL_PATH,STATIC_PREFIX
from .domain.errors import DeviceError
from .registry import Registry, timestamp
from .infrastructure.storage.ha_registry_storage import HaRegistryStorage
from .discovery import DiscoveryManager
from .firmware import FirmwareLibrary
from .sources import Sources
from .bindings import Bindings
from .network import NetworkJobs
from .maintenance import Maintenance
from .application.profile_snapshots import ProfileSnapshots, RESOURCE_EVENT
from .application.device_status import DeviceStatusService
from .application.device_membership import DeviceMembershipService
from .application.device_enrollment import DeviceEnrollment
from .application.search_resource import SearchResource
from .application.connections_resource import ConnectionsResource
from .application.mqtt_enrollment import MqttEnrollment
from .application.mqtt_setup import MqttSetup
from homeassistant.helpers.storage import Store
from .infrastructure.ha_membership import HaMembership
from .infrastructure.devices.identity_client import IdentityClient
from .infrastructure.storage.ha_profile_storage import HaProfileStorage
from .application.settings_resource import SettingsResource
from .infrastructure.storage.ha_settings_storage import HaSettingsStorage
from .infrastructure.storage.ha_maintenance_storage import HaMaintenanceStorage
from .infrastructure.storage.ha_device_resources import HaDeviceResources
from .application.device_resources import DeviceResources
from .application.firmware_resource import FirmwareResource
from .application.membership_commands import MembershipCommands
from .infrastructure.storage.maintenance_files import MaintenanceFiles
from .infrastructure.equipment_channel import EquipmentChannel

_LOGGER=logging.getLogger(__name__)
CONFIG_SCHEMA=cv.config_entry_only_config_schema(DOMAIN)

class Site:
    def __init__(self,hass,entry):
        self.hass,self.entry=hass,entry
        # Operator work may outlive an HTTP request and must not block HA startup.
        # The resource owners still cancel/retain their work in stop().
        create_resource_task=partial(entry.async_create_background_task,hass,
            name="ESPOID resource",eager_start=False)
        self.registry=Registry(hass,entry,HaRegistryStorage(hass,entry))
        self.registry.changed=self.registry_changed
        self.membership=DeviceMembershipService(self.registry,HaMembership(hass,entry),
            client_factory=lambda origin: IdentityClient(async_get_clientsession(hass),origin),now=timestamp)
        self.sources=Sources(hass,self.registry,self.membership)
        self.bindings=Bindings(hass,entry,self.sources)
        self.network=NetworkJobs(hass,entry,self.bindings)
        self.library=FirmwareLibrary(hass.config.config_dir)
        self.firmware_resource=FirmwareResource(self.library,hass.async_add_executor_job,
            lambda event:hass.bus.async_fire(RESOURCE_EVENT,event),create_task=hass.async_create_task)
        self.maintenance=Maintenance(hass,HaMaintenanceStorage(hass,entry),self.registry,self.bindings,self.library,
            MaintenanceFiles(hass.config.config_dir,run_io=hass.async_add_executor_job))
        self.registry.maintenance=self.maintenance
        self.bindings.maintenance=self.maintenance
        self.device_status=DeviceStatusService(self.registry,self.maintenance,now=timestamp)
        self.profiles=ProfileSnapshots(HaProfileStorage(hass,entry),self.registry,self.maintenance,
            lambda event: hass.bus.async_fire(RESOURCE_EVENT,event),create_task=create_resource_task)
        self.settings_resource=SettingsResource(HaSettingsStorage(hass,entry),self.update,
            lambda: bool(self.maintenance.tasks),
            lambda event: hass.bus.async_fire(RESOURCE_EVENT,event),create_task=hass.async_create_task)
        self.update_lock=asyncio.Lock()
        self.discovery=DiscoveryManager()
        self.membership_lock=asyncio.Lock()
        self.enrollment=DeviceEnrollment(self.registry,self.membership,self.sources,self.profiles,
            self.membership_lock,create_task=hass.async_create_task)
        self.search_resource=SearchResource(self.discovery,self.registry,self.sources,self.enrollment,
            lambda event: hass.bus.async_fire(RESOURCE_EVENT,event),create_task=hass.async_create_task)
        self.connections=ConnectionsResource(self.registry,self.sources,self.bindings,self.network,self.enrollment,
            self.membership,self.profiles,lambda event:hass.bus.async_fire(RESOURCE_EVENT,event),create_task=hass.async_create_task)
        self.mqtt_enrollment=MqttEnrollment(self.connections,self.bindings)
        self.mqtt_setup=MqttSetup(Store(hass,1,f"{DOMAIN}.mqtt_setup.{entry.entry_id}",private=True),
            self.connections,self.mqtt_enrollment,self.registry,
            lambda event:hass.bus.async_fire(RESOURCE_EVENT,event),create_task=create_resource_task)
        self.resources=DeviceResources(HaDeviceResources(hass,entry),self.registry,self.maintenance,
            self.library,self.device_status,self.profiles,self.maintenance.files,hass.async_add_executor_job,
            self.device_resource_changed,equipment=EquipmentChannel(hass,self.bindings),create_task=create_resource_task)
        self.bindings.transition_busy=lambda node_id:bool(self.registry.active(node_id) or self.profiles.busy(node_id)
            or any(records.get(node_id,{}).get('pending') for records in self.resources.records.values()))
        self.connections.control=self.resources.command
        self.connections.control_busy=lambda node_id: any(
            self.resources.records[entity].get(node_id, {}).get('pending') for entity in ('status', 'control'))
        self.device_status.observed=self.observe_device_status
        self.maintenance.observed=self.observe_machine
        self.resources.sources, self.resources.discovery = self.sources, self.discovery
        self.membership_commands=MembershipCommands(self.registry,self.membership,self.profiles,self.resources,
            self.discovery,self.membership_lock,create_task=hass.async_create_task)
        self.source_settings=None

    def registry_changed(self, event):
        self.hass.bus.async_fire(RESOURCE_EVENT, event)
        self.connections.changed()

    def device_resource_changed(self, event):
        self.hass.bus.async_fire(RESOURCE_EVENT, event)
        if event['entity'] in ('status', 'control'):
            self.connections.changed()

    async def observe_device_status(self,node):
        await self.resources.observe(node)
        self.connections.changed()

    async def observe_machine(self,node):
        await self.observe_device_status(node)
        await self.profiles.reconcile(node)
        await self.resources.reconcile(node)

    async def update(self):
        async with self.update_lock:
            self.registry.sync()
            await self.profiles.prune()
            await self.resources.prune()
            await self.registry.save()
            signature=(tuple(self.registry.settings["z2m_prefixes"]),self.registry.settings["announcement_prefix"])
            if signature!=self.source_settings:
                await self.sources.stop()
                self.sources=Sources(self.hass,self.registry,self.membership)
                self.bindings.sources=self.sources
                self.enrollment.sources=self.sources
                self.search_resource.sources=self.sources
                self.connections.sources=self.sources
                self.resources.sources=self.sources
                self.sources.changed=self.connections.changed
                try:
                    async with asyncio.timeout(5): await self.sources.start()
                except Exception as err:
                    # A failed optional broker must not prevent service setup.
                    _LOGGER.warning("Optional MQTT observations unavailable (%s)",type(err).__name__)
                    await self.sources.stop()
                self.source_settings=signature
            await self.settings_resource.sync()
            self.search_resource.changed()
            self.connections.changed()

    async def stop(self,*args):
        await self.mqtt_setup.stop()
        await self.membership_commands.stop()
        await self.resources.stop()
        await self.firmware_resource.stop()
        await self.connections.stop()
        await self.search_resource.stop()
        await self.enrollment.stop()
        await self.settings_resource.stop()
        await self.profiles.stop()
        await self.maintenance.stop()
        await self.network.stop()
        await self.bindings.stop()
        await self.sources.stop()

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
        await site.bindings.load()
        await site.network.load()
        await site.maintenance.load()
        await site.profiles.load()
        await site.resources.load()
        await site.settings_resource.load()
        await site.mqtt_setup.load()
        # Development candidates can share a version. A content-specific path
        # prevents browsers/proxies from reusing a previous candidate's module.
        asset_path=Path(__file__).parent/"frontend"
        asset_digest=await hass.async_add_executor_job(
            lambda: hashlib.sha256((asset_path/"panel.js").read_bytes()).hexdigest()[:16])
        static_prefix=f"{STATIC_PREFIX}/{asset_digest}"
        if not data["registered"]:
            from .api import register_views
            await hass.http.async_register_static_paths([
                StaticPathConfig(static_prefix,str(asset_path),False)])
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
                    "name":f"{PANEL_PATH}-panel","module_url":f"{static_prefix}/panel.js",
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
