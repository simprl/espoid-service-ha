"""Private HA storage for maintenance jobs and per-device sequences."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ...const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class HaMaintenanceStorage:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.store = Store(hass, 1, f"{DOMAIN}.maintenance.{entry.entry_id}", private=True)

    async def load(self) -> object:
        return await self.store.async_load()

    async def save(self, records: dict[str, Any]) -> None:
        await self.store.async_save(records)
