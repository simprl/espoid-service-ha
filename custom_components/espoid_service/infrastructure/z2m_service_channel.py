"""Z2M packet adapter for the common protected Service channel."""
from __future__ import annotations
import json
import re
from homeassistant.core import callback
from ..domain.errors import DeviceError
from .service_channel import ServiceChannel


class Z2MChannel(ServiceChannel):
    def __init__(self,hass,candidate):
        super().__init__()
        self.hass=hass
        self.topic=candidate["prefix"]+"/"+candidate["name"]

    async def subscribe(self):
        from homeassistant.components import mqtt
        return await mqtt.async_subscribe(self.hass,self.topic,self.receive)

    async def publish(self,kind,data):
        if self.failed: raise DeviceError("tunnel_failed")
        from homeassistant.components import mqtt
        await mqtt.async_publish(self.hass,self.topic+"/set",json.dumps({
            "service_tunnel":{"kind":kind,"packet":data.hex()}},separators=(",",":")),qos=0,retain=False)

    @callback
    def receive(self,message):
        if getattr(message,"retain",False): return
        try:
            if len(message.payload)>4096: return
            value=json.loads(message.payload).get("service_tunnel")
            if not isinstance(value,dict) or set(value)!={"kind","packet"}: return
            packet=value["packet"]
            if not isinstance(packet,str) or not re.fullmatch(r"(?:[0-9a-f]{2}){1,48}",packet): return
            self.receive_packet(value["kind"],bytes.fromhex(packet))
        except (ValueError,TypeError,AttributeError,RecursionError): return
