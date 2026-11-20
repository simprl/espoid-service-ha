"""Bounded broker exchanges on the configured MQTT or Z2M equipment transport."""
import asyncio
import json
import secrets

from ..domain.equipment_policy import observation, check_context, matching_result
from ..domain.errors import DeviceError
from ..equipment_contract import DOCUMENT_BYTES


class EquipmentChannel:
    def __init__(self, hass, bindings):
        self.hass, self.bindings = hass, bindings

    def target(self, node):
        candidate = self.bindings.mqtt_candidate(node.node_id)
        if candidate:
            if candidate["state"] != "active":
                raise DeviceError("binding_missing")
            return {"transport": "mqtt", "topic": candidate["topic"],
                    "binding_id": candidate["binding_id"], "binding_revision": candidate["revision"]}
        candidate = self.bindings.sources.candidate(node.z2m)
        record = self.bindings.records.get(candidate["prefix"] + ":" + candidate["ieee"])
        if not record or record["state"] != "active" or record["node_id"] != node.node_id:
            raise DeviceError("binding_missing")
        return {"transport": "zigbee", "topic": candidate["prefix"] + "/" + candidate["name"],
                "binding_id": record["binding_id"], "binding_revision": record["revision"]}

    async def exchange(self, target, request=None):
        from homeassistant.components import mqtt
        changed, latest, subscriptions = asyncio.Event(), {}, []
        identifier = request["request_id"] if request else secrets.token_hex(6)
        base = target["topic"]
        direct = target["transport"] == "mqtt"
        sent = False
        counters = {"state": 0, "commissioning": 0}

        def receive(message):
            try:
                if direct and message.topic == base + "/availability":
                    latest["online"] = message.payload == "online"
                else:
                    value = decode(message.payload)
                    if not direct:
                        # Z2M full-state publications can contain cached replies.
                        if getattr(message, "retain", False): return
                        value = decode(value.get("equipment_snapshot", ""))
                        if value.get("id") != identifier: return
                        latest["reply"] = value
                    elif message.topic == base + "/capabilities":
                        latest["catalog"] = value
                    elif message.topic == base + "/commissioning":
                        latest["commissioning"] = value
                        counters["commissioning"] += 1
                    elif message.topic.startswith(base + "/devices/") and message.topic.endswith("/state"):
                        if message.topic != base + "/devices/" + str(value.get("device_id")) + "/state": return
                        # The current equipment page contract selects one logical provider.
                        latest["state"] = value
                        counters["state"] += 1
                    elif request and not getattr(message, "retain", False) and matching_result(value, request):
                        latest["result"] = value
                        if value["status"] in ("completed", "verified", "rejected", "uncertain") and "result_counters" not in latest:
                            latest["result_counters"] = dict(counters)
                changed.set()
            except (DeviceError, ValueError, TypeError, UnicodeError, RecursionError):
                return

        try:
            async with asyncio.timeout(55):
                topics = [base + suffix for suffix in ("/capabilities", "/commissioning", "/devices/+/state", "/result", "/availability")] if direct else [base]
                for topic in topics:
                    subscriptions.append(await mqtt.async_subscribe(self.hass, topic, receive, qos=0))
                if not direct:
                    payload = {"id": identifier}
                    if request: payload["command"] = request
                    sent = True
                    await mqtt.async_publish(self.hass, base + "/set",
                        json.dumps({"equipment_request": json.dumps(payload, separators=(",", ":"))}), qos=0, retain=False)
                while True:
                    await changed.wait()
                    changed.clear()
                    if not direct:
                        reply = latest.get("reply")
                        if not reply: continue
                        if reply.get("error"): raise DeviceError("equipment_unconfirmed")
                        result = reply.get("result")
                        if request and not matching_result(result, request):
                            raise DeviceError("equipment_unconfirmed")
                        value = observation(reply.get("observation"))
                        if value["catalog"]["boot_id"] != target.get("boot_id", value["catalog"]["boot_id"]):
                            raise DeviceError("equipment_context_changed")
                        if request: check_context(value, request)
                        return {"observation": value, **({"result": result} if request else {})}
                    if latest.get("online") is False:
                        raise DeviceError("equipment_offline")
                    if not all(key in latest for key in ("catalog", "state", "commissioning")): continue
                    try:
                        value = observation({key: latest[key] for key in ("catalog", "state", "commissioning")})
                    except DeviceError:
                        continue
                    if value["catalog"]["boot_id"] != target.get("boot_id", value["catalog"]["boot_id"]):
                        raise DeviceError("equipment_context_changed")
                    if not request:
                        return {"observation": value}
                    if not sent:
                        check_context(value, request)
                        if latest.get("online") is not True: continue
                        sent = True
                        await mqtt.async_publish(self.hass, base + "/command", json.dumps(request, separators=(",", ":")), qos=0, retain=False)
                    result = latest.get("result")
                    if result and result["status"] in ("completed", "verified", "rejected", "uncertain"):
                        after = latest["result_counters"]
                        if all(counters[key] > after[key] for key in counters):
                            check_context(value, request)
                            return {"observation": value, "result": result}
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if isinstance(error, DeviceError) and not sent:
                raise
            raise DeviceError("equipment_unconfirmed" if sent else "equipment_unavailable") from None
        finally:
            for unsubscribe in subscriptions: unsubscribe()


def decode(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 3 * DOCUMENT_BYTES + 4096:
        raise DeviceError("invalid_response")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise DeviceError("invalid_response")
            result[key] = value
        return result
    def invalid_constant(_value):
        raise DeviceError("invalid_response")
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    if not isinstance(value, dict): raise DeviceError("invalid_response")
    return value
