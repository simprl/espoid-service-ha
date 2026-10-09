"""HA support download without installation addresses or configuration JSON."""

from .const import DOMAIN, VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    device = hass.data.get(DOMAIN, {}).get("devices", {}).get(entry.entry_id)
    status = device.status if device and device.status else {}
    return {"integration_version": VERSION, "http_reachable_at_last_check": bool(device and device.reachable),
            "running_version": status.get("running_version"), "haier": status.get("haier"),
            "recovery_active": (status.get("recovery") or {}).get("active")}
