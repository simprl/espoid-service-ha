"""Device registration, verified address adoption, renaming and removal."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..const import MAX_NODES
from ..domain.address_policy import validate_local_origin as local_url
from ..domain.errors import DeviceError
from ..model import node_settings


class DeviceMembershipService:
    def __init__(self, registry, members: MembershipAdapter, *, client_factory, now):
        self.registry, self.members = registry, members
        self.client_factory, self.now = client_factory, now

    async def add(self, url, name="ESPOID", binding=None, *, expected_id=None):
        registry = self.registry
        origin = local_url(url)
        async with registry.network_slots:
            found = await self.client_factory(origin).identity()
        key = found["node_id"]
        if expected_id is not None and key != expected_id:
            raise DeviceError("identity_mismatch")
        if key in registry.nodes:
            raise DeviceError("already_configured")
        if len(registry.nodes) >= MAX_NODES:
            raise DeviceError("node_limit")
        if any(node.origin == origin for node in registry.nodes.values()):
            raise DeviceError("search_address_conflict")
        if binding and found.get("zigbee_ieee") != binding.get("ieee"):
            raise DeviceError("identity_mismatch")
        data = node_settings({"node_id": key, "name": name, "base_url": origin, "z2m": binding})
        self.members.add(data)
        registry.sync()
        node = registry.get(key)
        node.identity, node.reachable = found, True
        registry.locators[key] = {"origin": origin, "seen_at": self.now(), "boot_id": found["boot_id"]}
        await registry.save()
        return node

    async def adopt(self, key, url):
        registry = self.registry
        node = registry.get(key)
        origin = local_url(url)
        async with registry.network_slots:
            found = await self.client_factory(origin).verify(key)
        if any(other.node_id != key and other.origin == origin for other in registry.nodes.values()):
            raise DeviceError("search_address_conflict")
        if node.z2m and found["transports"]["zigbee"] and found.get("zigbee_ieee") != node.z2m["ieee"]:
            raise DeviceError("identity_mismatch")
        node.origin, node.identity, node.reachable = origin, found, True
        node.status, node.checked_at = None, None
        registry.locators.setdefault(key, {}).update(origin=origin, seen_at=self.now(), boot_id=found["boot_id"])
        await registry.save()
        return found

    async def add_bound(self, candidate, binding):
        """An active binding provides identity without an inbound HTTP request."""
        registry = self.registry
        key = binding["node_id"]
        target = None if binding.get("transport") == "mqtt" else {field: candidate[field] for field in ("prefix", "ieee")}
        if key in registry.nodes:
            if (registry.nodes[key].z2m or None) != target:
                if bool(registry.nodes[key].z2m) == bool(target):
                    raise DeviceError('identity_mismatch')
                node = registry.nodes[key]
                data = node_settings({**self.members.data(node.subentry), "z2m": target,
                    "base_url": candidate.get("admin_url") if target is None else ""})
                self.members.update(node.subentry, data)
                registry.sync()
                node = registry.get(key)
                node.status, node.identity = None, None
                node.reachable, node.checked_at = False, None
        else:
            if len(registry.nodes) >= MAX_NODES:
                raise DeviceError("node_limit")
            data = node_settings({"node_id": key, "name": candidate.get("name") or key,
                                  "z2m": target, "base_url": candidate.get("admin_url") if target is None else ""})
            self.members.add(data)
            registry.sync()
        locator = registry.locators.setdefault(key, {})
        locator.pop('machine_transport', None)
        locator.pop('machine', None)
        locator["machine_transport" if target is None else "machine"] = "mqtt" if target is None else True
        if target is None and candidate.get('admin_url'):
            locator['origin'] = local_url(candidate['admin_url'])
        await registry.save()
        return registry.get(key)

    def rename(self, node, name):
        data = node_settings({**self.members.data(node.subentry), "name": name})
        self.members.update(node.subentry, data)
        self.registry.sync()

    async def remove(self, node):
        self.members.remove(node.subentry)
        self.registry.sync()
        await self.registry.save()


class MembershipAdapter(Protocol):
    """Synchronous member-record updates; the registry owns runtime synchronization."""

    def data(self, member: object) -> Mapping[str, Any]: ...

    def add(self, data: dict[str, Any]) -> None: ...

    def update(self, member: object, data: dict[str, Any]) -> None: ...

    def remove(self, member: object) -> None: ...
