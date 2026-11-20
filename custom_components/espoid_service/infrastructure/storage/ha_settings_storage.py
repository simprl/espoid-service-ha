"""HA config-entry settings and private resource metadata storage."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ...const import DOMAIN
from ...domain.settings_policy import ServiceSettings, SettingsMetadata

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class HaSettingsStorage:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.store = Store(hass, 1, f"{DOMAIN}.settings.{entry.entry_id}", private=True)

    def read(self) -> Mapping[str, Any]:
        return self.entry.data

    def write(self, value: ServiceSettings) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, **deepcopy(value)}
        )

    async def load_metadata(self) -> object:
        return await self.store.async_load()

    async def save_metadata(self, metadata: SettingsMetadata) -> None:
        await self.store.async_save(deepcopy(metadata))
