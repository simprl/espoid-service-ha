"""Register/adopt identity-checked devices without starting administration."""

from __future__ import annotations

import asyncio

from ..domain.errors import DeviceError
from .tracked_task import run_tracked_task


class DeviceEnrollment:
    def __init__(
        self, registry, membership, sources, profiles, lock, *,
        create_task=asyncio.create_task,
    ):
        self.registry, self.membership, self.sources = registry, membership, sources
        self.profiles, self.lock = profiles, lock
        self.create_task, self.tasks, self.stopped = create_task, set(), False

    async def add(self, value, *, candidate=False):
        if self.stopped:
            raise DeviceError("operation_busy")
        return await run_tracked_task(
            self._add(value, candidate), self.tasks, create_task=self.create_task
        )

    async def stop(self):
        self.stopped = True
        await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def _add(self, value, candidate):
        binding = value.get("z2m")
        if binding:
            self.sources.candidate(binding)
        async with self.lock:
            key = value.get("node_id") if candidate else None
            if key and key in self.registry.nodes:
                node = self.registry.get(key)
                async with node.lock:
                    if self.registry.active(key) or self.profiles.busy(key):
                        raise DeviceError("operation_unresolved")
                    await self.membership.adopt(key, value["url"])
                return {"id": key}
            node = await self.membership.add(
                value["url"], value.get("name", "ESPOID"), binding, expected_id=key
            )
        return {"id": node.node_id}
