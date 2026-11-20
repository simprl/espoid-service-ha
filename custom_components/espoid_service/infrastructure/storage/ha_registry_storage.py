"""HA storage for saved device addresses, operations and request fingerprints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ...const import DOMAIN, STORE_VERSION

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class HaRegistryStorage:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    async def load(self) -> object:
        return await self.store.async_load()

    async def save(self, records: dict[str, Any]) -> None:
        await self.store.async_save(records)
