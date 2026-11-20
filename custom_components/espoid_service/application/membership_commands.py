"""Caller-independent membership changes with shared identity and conflict checks."""
import asyncio
from ..domain.errors import DeviceError
from .tracked_task import run_tracked_task


class MembershipCommands:
    def __init__(self, registry, membership, profiles, resources, discovery, lock, *, create_task=asyncio.create_task):
        self.registry, self.membership, self.profiles = registry, membership, profiles
        self.resources, self.discovery, self.lock = resources, discovery, lock
        self.create_task, self.tasks, self.stopped = create_task, set(), False

    async def command(self, node_id, action, body):
        if self.stopped:
            raise DeviceError("operation_busy")
        return await run_tracked_task(self._execute(node_id, action, body), self.tasks, create_task=self.create_task)

    async def stop(self):
        self.stopped = True
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _execute(self, node_id, action, body):
        node = self.registry.get(node_id)
        if self.lock.locked() or node.lock.locked():
            raise DeviceError("operation_busy")
        async with self.lock, node.lock:
            if self.registry.active(node_id) or self.profiles.busy(node_id) or any(
                    records.get(node_id, {}).get("pending") for records in self.resources.records.values()):
                raise DeviceError("operation_unresolved")
            if self.discovery.blocks(node_id):
                raise DeviceError("search_busy")
            if action == "rename":
                self.membership.rename(node, body.get("name"))
                await self.registry.save()
            elif action == "address":
                await self.membership.adopt(node_id, body.get("url"))
            elif action == "remove" and body.get("confirmed") is True:
                await self.membership.remove(node)
            else:
                raise DeviceError("invalid_request")
        return {"id": node_id}
