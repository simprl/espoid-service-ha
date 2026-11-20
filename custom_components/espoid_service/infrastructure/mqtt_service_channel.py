"""Direct MQTT carrier. Discovery and broker access do not authorize enrollment."""
from __future__ import annotations
import json
import asyncio
import re
from homeassistant.core import callback
from ..domain.errors import DeviceError
from .service_channel import ServiceChannel


class MqttChannel(ServiceChannel):
    def __init__(self,hass,topic):
        super().__init__()
        if not isinstance(topic,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,111}",topic):
            raise DeviceError("invalid_request")
        self.hass=hass
        self.request_topic=topic+"/service/request"
        self.response_topic=topic+"/service/response"

    async def subscribe(self):
        from homeassistant.components import mqtt
        if not mqtt.is_connected(self.hass):
            raise DeviceError("mqtt_unavailable")
        connection_unsubscribe = mqtt.async_subscribe_connection_status(self.hass, self.connection_changed)
        try:
            data_unsubscribe = await mqtt.async_subscribe(self.hass,self.response_topic,self.receive)
            if self.failed:
                data_unsubscribe()
                raise DeviceError("tunnel_failed")
        except BaseException:
            connection_unsubscribe()
            raise
        def unsubscribe():
            data_unsubscribe()
            connection_unsubscribe()
        return unsubscribe

    async def publish(self,kind,data):
        if self.failed: raise DeviceError("tunnel_failed")
        from homeassistant.components import mqtt
        if not mqtt.is_connected(self.hass):
            self.connection_changed(False)
            raise DeviceError("mqtt_unavailable")
        await mqtt.async_publish(self.hass,self.request_topic,json.dumps(
            {"kind":kind,"packet":data.hex()},separators=(",",":")),qos=0,retain=False)

    @callback
    def connection_changed(self, connected):
        if connected:
            return
        self.failed = True
        try:
            self.queue.put_nowait(("closed", b""))
        except asyncio.QueueFull:
            pass

    @callback
    def receive(self,message):
        if getattr(message,"retain",False) or message.topic != self.response_topic: return
        try:
            if len(message.payload)>256: return
            value=json.loads(message.payload)
            if not isinstance(value,dict) or set(value)!={"kind","packet"}: return
            packet=value["packet"]
            if not isinstance(packet,str) or not re.fullmatch(r"(?:[0-9a-f]{2}){1,48}",packet): return
            self.receive_packet(value["kind"],bytes.fromhex(packet))
        except (ValueError,TypeError,AttributeError,RecursionError): return
