"""Private maintenance payload files; filesystem work uses an injected executor."""

from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path

from ...domain.errors import DeviceError
from ...machine_wire import hex_value


class MaintenanceFiles:
    def __init__(self, config_dir, *, run_io):
        self.root = Path(config_dir) / ".storage" / "espoid-maintenance"
        self.run_io = run_io

    def path(self, identifier, suffix):
        if not hex_value(identifier, 32) or suffix not in ("input", "output", "partial"):
            raise DeviceError("machine_invalid")
        return self.root / (identifier + "." + suffix)

    async def write(self, identifier, suffix, data):
        def write():
            self._checked_path(identifier, suffix).write_bytes(data)
        await self.run_io(write)

    async def read(self, identifier, suffix):
        def read():
            return self._checked_path(identifier, suffix).read_bytes()
        return await self.run_io(read)

    async def remove(self, identifier, suffix):
        def remove():
            self._checked_path(identifier, suffix).unlink(missing_ok=True)
        await self.run_io(remove)

    async def publish(self, identifier):
        # Only publish a complete, authenticated upload. The caller decides when.
        await self.run_io(os.replace, self.path(identifier, "partial"), self.path(identifier, "output"))

    async def identity(self, path):
        # Also used for immutable artifacts owned by FirmwareLibrary.
        return await self.run_io(_file_identity, path)

    @asynccontextmanager
    async def reader(self, path):
        file = await self.run_io(path.open, "rb")
        try:
            yield _FileStream(file, self.run_io)
        finally:
            await self.run_io(file.close)

    @asynccontextmanager
    async def receive(self, identifier):
        def open_partial():
            return self._checked_path(identifier, "partial").open("wb")
        file = await self.run_io(open_partial)
        try:
            try:
                yield _FileStream(file, self.run_io)
            finally:
                await self.run_io(file.close)
        except BaseException:
            # Includes cancellation/disconnect: close before removing on Windows.
            await self.remove(identifier, "partial")
            raise

    def _checked_path(self, identifier, suffix):
        # Nothing is served through HA's public www/static routes.
        for parent in (self.root, self.root.parent):
            if parent.is_symlink():
                raise DeviceError("machine_storage")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path(identifier, suffix)
        if target.is_symlink():
            raise DeviceError("machine_storage")
        return target


class _FileStream:
    def __init__(self, file, run_io):
        self.file, self.run_io = file, run_io

    async def read(self, size):
        return await self.run_io(self.file.read, size)

    async def write(self, data):
        await self.run_io(self.file.write, data)


def _file_identity(path):
    if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
        raise DeviceError("machine_storage")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as file:
        while block := file.read(8192):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()
