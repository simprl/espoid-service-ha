"""Server-side device maintenance, with no automatic Wi-Fi hold or writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import DeviceClient
from .const import DOMAIN, PANEL_PATH, VERSION
from .firmware import FirmwareLibrary


@dataclass
class DeviceRuntime:
    entry: object
    client: DeviceClient
    settings: dict
    status: dict | None = None
    checked_at: str | None = None
    reachable: bool = False
    last_action: dict = field(default_factory=dict)


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, entry):
    data = hass.data.setdefault(DOMAIN, {
        "devices": {}, "library": FirmwareLibrary(hass.config.config_dir),
        "setup_lock": asyncio.Lock(), "registered": False,
    })
    async with data["setup_lock"]:
        if not data["registered"]:
            from .api import register_views

            await hass.http.async_register_static_paths([
                StaticPathConfig(f"/{DOMAIN}-static", str(Path(__file__).parent / "frontend"), False),
            ])
            register_views(hass)
            data["registered"] = True
    settings = {**entry.data, **entry.options}
    data["devices"][entry.entry_id] = DeviceRuntime(
        entry, DeviceClient(async_get_clientsession(hass), settings["base_url"]), settings)
    if PANEL_PATH not in hass.data.get(frontend.DATA_PANELS, {}):
        frontend.async_register_built_in_panel(
            hass, "custom", sidebar_title="ESPOID Service", sidebar_icon="mdi:tools",
            frontend_url_path=PANEL_PATH, require_admin=True,
            config={"_panel_custom": {"name": f"{PANEL_PATH}-panel",
                    "module_url": f"/{DOMAIN}-static/panel.js?v={VERSION}",
                    "embed_iframe": False, "trust_external": False}},
        )
    entry.async_on_unload(entry.add_update_listener(_async_update_entry))
    return True


async def _async_update_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    hass.data[DOMAIN]["devices"].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]["devices"]:
        frontend.async_remove_panel(hass, PANEL_PATH)
    # Keep views/static registration once per HA process; reloading is safe.
    return True
