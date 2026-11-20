"""Host-independent settings save/sync lifecycle and metadata notifications."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol

from ..domain.errors import DeviceError
from .tracked_task import run_tracked_task
from ..domain.settings_policy import (
    ServiceSettings,
    SettingsMetadata,
    normalize_settings,
    settings_revision,
    validate_settings,
    validate_settings_metadata,
)

RESOURCE_ID = "service"


class SettingsResource:
    def __init__(
        self,
        storage: SettingsStorage,
        apply: Callable[[], Awaitable[None]],
        busy: Callable[[], bool],
        notify: Callable[[dict[str, Any]], None],
        *,
        create_task: Callable[
            [Coroutine[Any, Any, dict[str, str]]], asyncio.Task[dict[str, str]]
        ] = asyncio.create_task,
    ) -> None:
        self.storage = storage
        self.apply, self.busy, self.notify = apply, busy, notify
        self.create_task = create_task
        self.value = normalize_settings(storage.read())
        self.meta: SettingsMetadata = {
            "revision": settings_revision(self.value),
            "version": 0,
            "updated_at": None,
        }
        self.write_lock, self.sync_lock = asyncio.Lock(), asyncio.Lock()
        self.tasks: set[asyncio.Task[dict[str, str]]] = set()
        self.stopped = False

    async def load(self) -> None:
        saved = await self.storage.load_metadata()
        if saved is None:
            await self.storage.save_metadata(self.meta)
        else:
            self.meta = validate_settings_metadata(saved)
        await self.sync()

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": RESOURCE_ID,
            "entity": "settings",
            "version": self.meta["version"],
            "data": {"settings": deepcopy(self.value), "revision": self.meta["revision"]},
            "updated_at": self.meta["updated_at"],
            "state": "idle",
            "error": None,
            "validation": None,
        }

    async def sync(self) -> None:
        async with self.sync_lock:
            value = normalize_settings(self.storage.read())
            digest = settings_revision(value)
            if digest == self.meta["revision"]:
                self.value = value
                return
            if self.meta["version"] >= 2**53 - 1:
                raise DeviceError("storage_failed")
            meta: SettingsMetadata = {
                "revision": digest,
                "version": self.meta["version"] + 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.storage.save_metadata(meta)
            self.value, self.meta = value, meta
            self.notify(
                {"entity": "settings", "id": RESOURCE_ID, "version": meta["version"]}
            )

    async def save(self, value: object, expected_revision: str) -> dict[str, str]:
        if self.stopped:
            raise DeviceError("operation_busy")
        return await run_tracked_task(
            self._save(value, expected_revision), self.tasks, create_task=self.create_task
        )

    async def stop(self) -> None:
        self.stopped = True
        await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def _save(self, value: object, expected_revision: str) -> dict[str, str]:
        value = validate_settings(value)
        async with self.write_lock:
            await self.sync()
            if expected_revision != self.meta["revision"]:
                raise DeviceError("settings_conflict")
            if self.busy():
                raise DeviceError("operation_busy")
            if value == self.value:
                return {"id": RESOURCE_ID}
            self.storage.write(value)
            try:
                await self.apply()
                await self.sync()
            except Exception as error:
                raise DeviceError("outcome_uncertain") from error
            return {"id": RESOURCE_ID}


class SettingsStorage(Protocol):
    """Read current values synchronously; persist resource metadata durably."""

    def read(self) -> Mapping[str, Any]: ...

    def write(self, value: ServiceSettings) -> None: ...

    async def load_metadata(self) -> object: ...

    async def save_metadata(self, metadata: SettingsMetadata) -> None: ...
