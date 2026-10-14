"""HA subentries own membership. Store owns locators and operation evidence."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.storage import Store
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .client import DeviceError, local_url
from .const import DOMAIN, MAX_NODES, MAX_HISTORY, STORE_VERSION
from .model import node_settings, settings
from .service_client import ServiceClient

def timestamp(): return datetime.now(timezone.utc).isoformat()

ACTIVE_STATES=("prepared","sending","waiting","verifying","uncertain")

def retained_history(operations):
    active=[op for op in operations if op["state"] in ACTIVE_STATES]
    completed=[op for op in operations if op["state"] not in ACTIVE_STATES]
    remaining=max(0,MAX_HISTORY-len(active))
    keep={op["id"] for op in active+(completed[-remaining:] if remaining else [])}
    return [op for op in operations if op["id"] in keep]

@dataclass
class Node:
    subentry: object
    node_id: str
    name: str
    origin: str
    z2m: dict
    configured_origin: str = ""
    identity: dict | None = None
    status: dict | None = None
    checked_at: str | None = None
    reachable: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Registry:
    def __init__(self,hass,entry):
        self.hass,self.entry = hass,entry
        self.settings = settings(entry.data)
        self.nodes,self.locators,self.operations = {},{},[]
        self.store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.lock = asyncio.Lock()
        self.network_slots = asyncio.Semaphore(4)

    async def load(self):
        saved = await self.store.async_load()
        if saved:
            if not isinstance(saved,dict) or not isinstance(saved.get("locators",{}),dict) or not isinstance(saved.get("operations",[]),list):
                raise DeviceError("storage_failed")
            self.locators=saved.get("locators",{})
            self.operations=saved.get("operations",[])
            if any(not isinstance(op,dict) or not all(isinstance(op.get(k),str) for k in ("id","node_id","action","state","created_at","updated_at")) for op in self.operations):
                raise DeviceError("storage_failed")
            if any(not isinstance(value,dict) for value in self.locators.values()):
                raise DeviceError("storage_failed")
            self.operations=retained_history(self.operations)
            for op in self.operations:
                if op.get("state") in ("prepared","sending","waiting","verifying"):
                    op.update(state="uncertain",message="outcome_uncertain",updated_at=timestamp())
        self.sync()
        await self.save()

    def sync(self):
        self.settings=settings(self.entry.data)
        members={}
        for sub in self.entry.subentries.values():
            if sub.subentry_type != "node": continue
            data=node_settings(sub.data)
            key=data["node_id"]
            if sub.unique_id != key or key in members: raise DeviceError("invalid_identity")
            previous=self.nodes.get(key)
            origin=self.locators.get(key,{}).get("origin") or data["base_url"]
            if origin: origin=local_url(origin)
            if previous:
                if previous.configured_origin!=data["base_url"]:
                    previous.origin=data["base_url"]
                    previous.configured_origin=data["base_url"]
                    self.locators.setdefault(key,{})["origin"]=data["base_url"]
                    previous.status,previous.reachable=None,False
                previous.subentry,previous.name,previous.z2m=sub,data["name"],data.get("z2m",{})
                members[key]=previous
            else: members[key]=Node(sub,key,data["name"],origin,data.get("z2m",{}),configured_origin=data["base_url"])
        self.nodes=members
        self.locators={key:value for key,value in self.locators.items() if key in members}

    async def save(self):
        async with self.lock:
            self.operations=retained_history(self.operations)
            await self.store.async_save({"locators":self.locators,"operations":self.operations})

    def get(self,key):
        if key not in self.nodes: raise DeviceError("unknown_node")
        return self.nodes[key]

    def client(self,node):
        if not node.origin: raise DeviceError("address_unknown")
        return ServiceClient(async_get_clientsession(self.hass),node.origin)

    async def adopt(self,key,url):
        node=self.get(key)
        origin=local_url(url)
        async with self.network_slots:
            found=await ServiceClient(async_get_clientsession(self.hass),origin).verify(key)
        if any(n.node_id!=key and n.origin==origin for n in self.nodes.values()):
            raise DeviceError("search_address_conflict")
        if node.z2m and found["transports"]["zigbee"] and found.get("zigbee_ieee") != node.z2m["ieee"]:
            raise DeviceError("identity_mismatch")
        node.origin,node.identity,node.reachable=origin,found,True
        node.status,node.checked_at=None,None
        self.locators.setdefault(key,{}).update(origin=origin,seen_at=timestamp(),boot_id=found["boot_id"])
        await self.save()
        return found

    async def add(self,url,name="ESPOID",binding=None):
        origin=local_url(url)
        async with self.network_slots:
            found=await ServiceClient(async_get_clientsession(self.hass),origin).identity()
        key=found["node_id"]
        if key in self.nodes: raise DeviceError("already_configured")
        if len(self.nodes)>=MAX_NODES: raise DeviceError("node_limit")
        if any(n.origin==origin for n in self.nodes.values()): raise DeviceError("search_address_conflict")
        if binding and found.get("zigbee_ieee") != binding.get("ieee"):
            raise DeviceError("identity_mismatch")
        data=node_settings({"node_id":key,"name":name,"base_url":origin,"z2m":binding})
        sub=ConfigSubentry(data=data,subentry_type="node",title=data["name"],unique_id=key)
        self.hass.config_entries.async_add_subentry(self.entry,sub)
        self.sync()
        node=self.get(key)
        node.identity,node.reachable=found,True
        self.locators[key]={"origin":origin,"seen_at":timestamp(),"boot_id":found["boot_id"]}
        await self.save()
        return node

    def active(self,key):
        return next((op for op in reversed(self.operations) if op["node_id"]==key and
            op["state"] in ACTIVE_STATES),None)

    async def begin(self,key,action,artifact=None):
        if self.active(key): raise DeviceError("operation_unresolved")
        op={"id":uuid.uuid4().hex,"node_id":key,"action":action,"state":"prepared",
            "created_at":timestamp(),"updated_at":timestamp(),"message":""}
        if artifact: op["artifact"]={"version":artifact["version"],"sha256":artifact["artifact"]["sha256"]}
        self.operations.append(op)
        await self.save()
        return op

    async def transition(self,op,state,message=""):
        op.update(state=state,message=message,updated_at=timestamp())
        await self.save()

    async def refresh(self,node):
        node.checked_at=timestamp()
        try:
            async with self.network_slots:
                client=self.client(node)
                node.identity=await client.verify(node.node_id)
                status=await client.status()
            if status["node_id"]!=node.node_id: raise DeviceError("identity_mismatch")
            node.status,node.reachable=status,True
            evidence={"boot_id":status["boot_id"],"marker_sha256":status.get("ota_marker_sha256",""),
                "marker_partition":status.get("ota_marker_partition","")}
            locator=self.locators.setdefault(node.node_id,{})
            if any(locator.get(k)!=v for k,v in evidence.items()):
                locator.update(evidence)
                await self.save()
            op=self.active(node.node_id)
            if op and "artifact" in op and op["state"] not in ("prepared","sending"):
                ota=status["wifi_ota"]
                match=status.get("ota_marker_configured") is True and status.get("ota_marker_sha256")==op["artifact"]["sha256"]
                rebooted=bool(op.get("before_boot_id")) and status.get("boot_id")!=op["before_boot_id"]
                reinstalled=op.get("before_marker_sha256")!=op["artifact"]["sha256"] or (
                    bool(op.get("before_marker_partition")) and status.get("ota_marker_partition")!=op["before_marker_partition"])
                if ota.get("state")=="failed":
                    await self.transition(op,"failed",str(ota.get("message",""))[:160])
                elif (op["action"] in ("ota_z2m","ota_url") and ota.get("state")=="skipped"
                      and match and ota.get("artifact_sha256")==op["artifact"]["sha256"]
                      and status["running_version"]==op["artifact"]["version"]
                      and not ota.get("verification_pending") and not ota.get("running")):
                    # Firmware's URL path skips a digest that is already running.
                    # This is a terminal no-op, not proof of a new installation.
                    await self.transition(op,"already_current","already_current")
                elif match and rebooted and reinstalled and not ota.get("verification_pending") and not ota.get("running"):
                    await self.transition(op,"verified")
                elif match and rebooted and reinstalled and ota.get("verification_pending"):
                    await self.transition(op,"verifying")
            return status
        except DeviceError:
            node.reachable=False
            raise

    def summaries(self):
        return [{"node_id":n.node_id,"name":n.name,"base_url":n.origin,"z2m":n.z2m,
            "connection":"wifi" if n.reachable else "service_closed" if n.z2m else "unknown",
            "checked_at":n.checked_at,"firmware_version":(n.status or {}).get("running_version") or (n.identity or {}).get("firmware_version"),
            "identity":n.identity,"operation":self.active(n.node_id)} for n in self.nodes.values()]
