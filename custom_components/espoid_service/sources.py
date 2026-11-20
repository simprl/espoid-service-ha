"""Optional MQTT observations. No commands, scans or Wi-Fi holds on receipt."""
from __future__ import annotations
import asyncio
import json
from homeassistant.core import callback
from .domain.errors import DeviceError
from .model import ieee, node_id, topic_prefix
from .const import Z2M_CATALOG_MAX_BYTES
from .service_support import MODELS, service_support, require_service_feature


class Sources:
    def __init__(self,hass,registry,membership):
        self.hass,self.registry=hass,registry
        self.membership=membership
        self.catalog={}
        self.announcements={}
        self.unsubscribers=[]
        self.pending={}
        self.worker=None
        self.stopped=False
        self.changed=lambda:None

    async def start(self):
        if not self.hass.services.has_service("mqtt","publish"): return
        from homeassistant.components import mqtt
        for prefix in self.registry.settings["z2m_prefixes"]:
            self.unsubscribers.append(await mqtt.async_subscribe(self.hass,prefix+"/bridge/devices",self.receive_catalog))
            self.unsubscribers.append(await mqtt.async_subscribe(self.hass,prefix+"/#",self.receive_state))
        prefix=self.registry.settings["announcement_prefix"]
        self.unsubscribers.append(await mqtt.async_subscribe(self.hass,prefix+"/+/service",self.receive_announcement))

    def decode(self,message,limit=65536):
        if len(message.payload)>limit or (isinstance(message.payload,str) and len(message.payload.encode('utf-8'))>limit):
            raise DeviceError("invalid_response")
        try: return json.loads(message.payload)
        except (ValueError,TypeError,RecursionError): raise DeviceError("invalid_response") from None

    @callback
    def receive_catalog(self,message):
        try:
            values=self.decode(message,Z2M_CATALOG_MAX_BYTES)
            if not isinstance(values,list) or len(values)>4096: return
            prefix=message.topic.removesuffix("/bridge/devices")
            found={}
            for value in values:
                if not isinstance(value,dict): continue
                definition=value.get("definition") or {}
                if not isinstance(definition,dict): continue
                if not any(isinstance(model,str) and model in MODELS
                           for model in (value.get('model_id'),definition.get('model'))): continue
                address=ieee(value.get("ieee_address"))
                name=value.get("friendly_name")
                if not isinstance(name,str) or not 1<=len(name)<=256 or any(c in name for c in "+#\x00"): continue
                previous=self.catalog.get(prefix+":"+address,{})
                version=value.get('software_build_id')
                version=version if isinstance(version,str) and len(version)<=32 else None
                exposes=definition.get('exposes',[])
                converter=isinstance(exposes,list) and any(isinstance(e,dict) and
                    e.get('property')=='service_capabilities' and type(e.get('access')) is int and
                    e['access'] & 5 == 5 for e in exposes[:256])
                candidate={"prefix":prefix,"ieee":address,"name":name,
                    "admin_url":previous.get("admin_url",""), 'firmware_version':version,
                    'service_converter':converter, 'service_capabilities':previous.get('service_capabilities')
                    if previous.get('firmware_version')==version else None}
                candidate['service_support']=service_support(candidate)
                found[prefix+":"+address]=candidate
            self.catalog={k:v for k,v in self.catalog.items() if v["prefix"]!=prefix}|found
            self.changed()
        except DeviceError: return

    @callback
    def receive_state(self,message):
        try:
            value=self.decode(message)
            if not isinstance(value,dict): return
            changed=False
            for candidate in self.catalog.values():
                before=(candidate.get('firmware_version'),candidate.get('service_capabilities'),candidate.get('admin_url'))
                if message.topic==candidate["prefix"]+"/"+candidate["name"]:
                    version=value.get('firmware_id')
                    if isinstance(version,str) and len(version)<=32 and version!=candidate.get('firmware_version'):
                        candidate.update(firmware_version=version,service_capabilities=None)
                    bits=value.get('service_capabilities')
                    if type(bits) is int and 0<=bits<=255: candidate['service_capabilities']=bits
                    candidate['service_support']=service_support(candidate)
                    if before[:2]!=(candidate.get('firmware_version'),candidate.get('service_capabilities')):changed=True
                if message.topic==candidate["prefix"]+"/"+candidate["name"] and value.get("admin_url"):
                    previous=candidate["admin_url"]
                    candidate["admin_url"]=value["admin_url"]
                    if previous!=candidate['admin_url']:changed=True
                    # Z2M caches both fields in full-state publications. Learn
                    # the first cached URL passively; fragments must not probe
                    # repeatedly, but a later changed URL must still be adopted.
                    if "service_tunnel" in value and (not previous or previous==candidate["admin_url"]): continue
                    for node in self.registry.nodes.values():
                        if not getattr(message,"retain",False) and node.z2m=={"prefix":candidate["prefix"],"ieee":candidate["ieee"]}:
                            self.queue(node.node_id,candidate["admin_url"])
            if changed:self.changed()
        except DeviceError: return

    @callback
    def receive_announcement(self,message):
        try:
            value=self.decode(message)
            if not isinstance(value,dict): return
            key=node_id(value.get("node_id"))
            prefix=self.registry.settings["announcement_prefix"]
            if message.topic != prefix+"/"+key+"/service": return
            observation={"node_id":key,"admin_url":value.get("admin_url","")}
            version=value.get('firmware_id')
            if isinstance(version,str) and len(version)<=32:
                observation['firmware_id']=version
            if type(value.get("service_mqtt")) is int and value["service_mqtt"] == 1:
                observation.update(transport="mqtt",topic=prefix+"/"+key,service_mqtt=1)
            self.announcements[key]=observation
            if len(self.announcements)>200: self.announcements.pop(next(iter(self.announcements)))
            self.changed()
            if key in self.registry.nodes and not getattr(message,"retain",False): self.queue(key,value.get("admin_url"))
        except DeviceError: return

    def announce(self,value):
        key=node_id(value.get("node_id"))
        self.announcements[key]={**self.announcements.get(key,{}),"node_id":key,"admin_url":value.get("admin_url","")}
        version=value.get('firmware_id')
        if isinstance(version,str) and len(version)<=32:
            self.announcements[key]['firmware_id']=version
        if len(self.announcements)>200: self.announcements.pop(next(iter(self.announcements)))
        self.changed()
        if key in self.registry.nodes: self.queue(key,value.get("admin_url"))

    def queue(self,key,url):
        if self.stopped or not isinstance(url,str): return
        if len(self.pending)>=200 and key not in self.pending: return
        self.pending[key]=url
        if self.worker is None or self.worker.done(): self.worker=self.hass.async_create_task(self.drain())

    async def drain(self):
        while self.pending and not self.stopped:
            key,url=self.pending.popitem()
            try:
                node=self.registry.get(key)
                async with node.lock:
                    await self.membership.adopt(key,url)
            except DeviceError: pass

    def candidate(self,binding):
        if not isinstance(binding,dict): raise DeviceError("z2m_device_missing")
        prefix=topic_prefix(binding.get("prefix"))
        address=ieee(binding.get("ieee"))
        value=self.catalog.get(prefix+":"+address)
        if not value: raise DeviceError("z2m_device_missing")
        return value

    async def service_candidate(self,binding,feature):
        """Relearn volatile capability hints only for an explicit service RPC."""
        candidate=self.candidate(binding)
        if self.stopped:raise DeviceError('mqtt_unavailable')
        if service_support(candidate)['reason']=='service_capabilities_unknown':
            from homeassistant.components import mqtt
            await mqtt.async_publish(self.hass,candidate['prefix']+'/'+candidate['name']+'/get',
                json.dumps({'service_capabilities':''}),qos=0,retain=False)
            for _ in range(50):
                candidate=self.candidate(binding)
                if self.stopped:raise DeviceError('mqtt_unavailable')
                if service_support(candidate)['reason']!='service_capabilities_unknown':break
                await asyncio.sleep(.1)
        require_service_feature(candidate,feature)
        return candidate

    async def command(self,binding,action):
        candidate=self.candidate(binding)
        if not self.hass.services.has_service("mqtt","publish"): raise DeviceError("mqtt_unavailable")
        try:
            await self.hass.services.async_call("mqtt","publish",{
                "topic":candidate["prefix"]+"/"+candidate["name"]+"/set",
                "payload":json.dumps({"reload_and_then":action}),"qos":0,"retain":False},blocking=True)
        except Exception as err:
            from homeassistant.exceptions import HomeAssistantError
            if isinstance(err,HomeAssistantError): raise DeviceError("outcome_uncertain") from err
            raise

    async def stop(self):
        self.stopped=True
        for unsubscribe in self.unsubscribers: unsubscribe()
        self.unsubscribers=[]
        if self.worker and not self.worker.done():
            self.worker.cancel()
            await asyncio.gather(self.worker,return_exceptions=True)
        self.pending.clear()
