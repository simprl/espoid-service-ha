"""Public device identity verification; never grants administration rights."""
from __future__ import annotations

from .http_client import HttpClient
from ...domain.errors import DeviceError
from ...service_contract import PATHS


class IdentityClient(HttpClient):
    async def identity(self):
        from ...model import identity
        return identity(await self.read_json(PATHS["IDENTITY"]))

    async def verify(self, expected):
        value = await self.identity()
        if value["node_id"] != expected:
            raise DeviceError("identity_mismatch")
        return value

