"""Saved firmware catalog and server-owned content-addressed imports."""
import asyncio
from time import time_ns
from .tracked_task import run_tracked_task
from ..domain.errors import DeviceError


class FirmwareResource:
    def __init__(self, library, run_io, notify, *, create_task=asyncio.create_task):
        self.library, self.run_io, self.notify, self.create_task = library, run_io, notify, create_task
        self.version, self.tasks = time_ns() // 1000, set()
        self.stopped = False

    async def snapshot(self):
        return {"entity": "firmware", "id": "service", "version": self.version,
                "firmware": await self.run_io(self.library.list)}

    async def import_image(self, manifest, image):
        if self.stopped:
            raise DeviceError("operation_busy")
        return await run_tracked_task(self._import(manifest, image), self.tasks, create_task=self.create_task)

    async def _import(self, manifest, image):
        saved = await self.run_io(self.library.import_image, manifest, image)
        self.version += 1
        self.notify({"entity": "firmware", "id": "service", "version": self.version})
        return {"id": saved["id"]}

    async def stop(self):
        self.stopped = True
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
