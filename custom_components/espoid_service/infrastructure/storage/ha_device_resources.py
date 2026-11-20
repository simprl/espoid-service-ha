"""Private persisted status, diagnostic artifact metadata and OTA observations."""
from homeassistant.helpers.storage import Store
from ...const import DOMAIN


class HaDeviceResources:
    def __init__(self, hass, entry):
        self.store = Store(hass, 1, f"{DOMAIN}.resources.{entry.entry_id}", private=True)

    async def load(self):
        return await self.store.async_load()

    async def save(self, records):
        await self.store.async_save(records)
