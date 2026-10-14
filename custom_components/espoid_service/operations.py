"""Persistent OTA intents, bounded tasks, explicit confirmation and no replay."""
from __future__ import annotations
import asyncio
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .client import DeviceError
from .const import DOMAIN
from .service_client import ServiceClient


class Operations:
    def __init__(self,hass,registry,library,sources):
        self.hass,self.registry,self.library,self.sources=hass,registry,library,sources
        self.tasks={}
        self.admission_lock=asyncio.Lock()

    def manifest_url(self,node):
        base=self.registry.settings["firmware_base_url"]
        if not base: raise DeviceError("firmware_url_required")
        return base+f"/local/firmware/{DOMAIN}/nodes/{node.node_id}/index.json"

    async def publish(self,node,digest):
        base=self.registry.settings["firmware_base_url"]
        if not base: raise DeviceError("firmware_url_required")
        manifest=await self.hass.async_add_executor_job(self.library.publish_node,node.node_id,digest,base)
        published=await ServiceClient(async_get_clientsession(self.hass),base).request(
            "GET",f"/local/firmware/{DOMAIN}/nodes/{node.node_id}/index.json")
        if published!=manifest: raise DeviceError("publication_failed")
        return manifest

    async def prepare(self,node):
        await self.registry.refresh(node)
        if self.registry.active(node.node_id): raise DeviceError("operation_unresolved")
        if node.status["wifi_ota"].get("running") or node.status["wifi_ota"].get("verification_pending"):
            raise DeviceError("ota_busy")
        client=self.registry.client(node)
        url=self.manifest_url(node)
        webhook_url=self.registry.settings["firmware_base_url"]+"/api/webhook/"+self.registry.entry.data["webhook_id"]
        op=await self.registry.begin(node.node_id,"prepare")
        try:
            await client.request("POST","/config/save",form={"ota_url":url,"ha_webhook":webhook_url},redirect_ok=True)
            if (await client.status()).get("ota_manifest_url")!=url: raise DeviceError("readback_failed")
            self.registry.locators.setdefault(node.node_id,{})["ota_url"]=url
            await self.registry.transition(op,"verified")
        except DeviceError as err:
            await self.registry.transition(op,"uncertain",err.code)
            raise
        return {"ok":True,"prepared":True}

    async def start(self,node,mode,digest):
        async with self.admission_lock:
            return await self._start(node,mode,digest)

    async def _start(self,node,mode,digest):
        if len(self.tasks)>=2: raise DeviceError("operation_busy")
        if mode not in ("z2m","url","upload"): raise DeviceError("invalid_action")
        manifest=await self.hass.async_add_executor_job(self.library.get,digest)
        if mode=="z2m":
            if node.identity and (not node.identity["transports"]["zigbee"] or node.identity.get("zigbee_ieee")!=node.z2m.get("ieee")):
                raise DeviceError("unsupported_service")
            self.sources.candidate(node.z2m)
            if self.registry.locators.get(node.node_id,{}).get("ota_url")!=self.manifest_url(node):
                raise DeviceError("ota_not_prepared")
        else:
            await self.registry.refresh(node)
            ota=node.status["wifi_ota"]
            if ota.get("running") or ota.get("verification_pending"): raise DeviceError("ota_busy")
            if not node.identity["ota"].get("upload" if mode=="upload" else "url"):
                raise DeviceError("unsupported_service")
        op=await self.registry.begin(node.node_id,"ota_"+mode,manifest)
        last=self.registry.locators.get(node.node_id,{})
        op["before_boot_id"]=(node.status or node.identity or {}).get("boot_id") or last.get("boot_id")
        op["before_marker_sha256"]=(node.status or {}).get("ota_marker_sha256",last.get("marker_sha256"))
        op["before_marker_partition"]=(node.status or {}).get("ota_marker_partition",last.get("marker_partition"))
        await self.registry.save()
        self.tasks[op["id"]]=self.hass.async_create_task(self.run(node,mode,digest,manifest,op))
        return op

    async def run(self,node,mode,digest,manifest,op):
        command_started=False
        try:
            if mode!="upload":
                await self.publish(node,digest)
            if mode=="z2m":
                await self.registry.transition(op,"sending")
                command_started=True
                await self.sources.command(node.z2m,"update_firmware_by_wifi")
            else:
                client=self.registry.client(node)
                await client.verify(node.node_id)
                if mode=="url": await client.set_manifest(self.manifest_url(node))
                await self.registry.transition(op,"sending")
                command_started=True
                if mode=="url": await client.install()
                else:
                    def progress(sent,total): op.update(sent_bytes=sent,total_bytes=total)
                    await client.upload(self.library.root/digest/"firmware.bin",manifest,progress)
            node.reachable=False
            await self.registry.transition(op,"waiting","waiting")
        except DeviceError as err:
            await self.registry.transition(op,"uncertain" if command_started else "failed",err.code)
        except asyncio.CancelledError:
            await self.registry.transition(op,"uncertain","outcome_uncertain")
            raise
        except Exception:
            await self.registry.transition(op,"uncertain" if command_started else "failed","operation_failed")
        finally:
            self.tasks.pop(op["id"],None)

    async def stop(self):
        tasks=list(self.tasks.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
