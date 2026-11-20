"""HA subentries own membership. Store owns locators and operation evidence."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
import uuid
import time
from copy import deepcopy
from .domain.errors import DeviceError
from .domain.address_policy import validate_local_origin as local_url
from .domain.registry_policy import ACTIVE_STATES, retained_history, validate_registry_records
from .model import node_settings, settings

def timestamp(): return datetime.now(timezone.utc).isoformat()

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
    def __init__(self,hass,entry,storage: RegistryStorage):
        self.hass,self.entry = hass,entry
        self.settings = settings(entry.data)
        self.nodes,self.locators,self.operations = {},{},[]
        self.request_records = []
        from .request_guard import RequestGuard
        self.request_guard = RequestGuard(self)
        self.storage = storage
        self.lock = asyncio.Lock()
        self.network_slots = asyncio.Semaphore(4)
        self.version = time.time_ns() // 1000
        self.changed = lambda event: None
        self._published = None

    async def load(self):
        saved = await self.storage.load()
        if saved:
            saved = validate_registry_records(saved)
            self.locators=saved.get("locators",{})
            self.operations=saved.get("operations",[])
            records=saved.get("requests",[])
            self.request_records=[{**item,"state":"uncertain" if item["state"]=="running" else item["state"]} for item in records]
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
            await self.storage.save({"locators":self.locators,"operations":self.operations,"requests":self.request_records})
            saved = {"devices": self.summaries(), "history": self.operations}
            if saved != self._published:
                self.version = max(self.version + 1, time.time_ns() // 1000)
                self._published = deepcopy(saved)
                for entity in ("devices", "history"):
                    self.changed({"entity": entity, "id": "service", "version": self.version})

    def get(self,key):
        if key not in self.nodes: raise DeviceError("unknown_node")
        return self.nodes[key]

    def active(self,key):
        return next((op for op in reversed(self.operations) if op["node_id"]==key and
            op["state"] in ACTIVE_STATES),None)

    async def begin(self,key,action,artifact=None):
        if self.active(key): raise DeviceError("operation_unresolved")
        op={"id":uuid.uuid4().hex,"node_id":key,"action":action,"state":"prepared",
            "created_at":timestamp(),"updated_at":timestamp(),"message":""}
        if artifact: op["artifact"]={"version":artifact["version"],"sha256":artifact["artifact"]["sha256"],"variant":artifact.get("variant")}
        self.operations.append(op)
        await self.save()
        return op

    async def transition(self,op,state,message=""):
        op.update(state=state,message=message,updated_at=timestamp())
        await self.save()

    def summaries(self):
        return [{"node_id":n.node_id,"name":n.name,"base_url":n.origin,"z2m":n.z2m,
            "connection":"wifi" if n.reachable and (not getattr(self,'maintenance',None) or not self.maintenance.supports(n) or self.maintenance.wifi_observed(n)) else "service_closed" if n.z2m else "unknown",
            "checked_at":n.checked_at,"firmware_version":(n.status or {}).get("running_version") or (n.identity or {}).get("firmware_version"),
            "identity":n.identity,"operation":self.active(n.node_id),
            "machine":bool(getattr(self,'maintenance',None) and self.maintenance.supports(n))} for n in self.nodes.values()]


class RegistryStorage(Protocol):
    """Read raw records and persist the registry's existing combined payload."""

    async def load(self) -> object: ...

    async def save(self, records: dict[str, Any]) -> None: ...
