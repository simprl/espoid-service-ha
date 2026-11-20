"""Private HA storage adapter for profile snapshots and durable pending intents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ...const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class HaProfileStorage:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.store = Store(hass, 1, f"{DOMAIN}.profiles.{entry.entry_id}", private=True)

    async def load(self) -> object:
        return await self.store.async_load()

    async def save(self, records: dict[str, Any]) -> None:
        # The resource captures a detached snapshot under its persistence lock.
        await self.store.async_save(records)
