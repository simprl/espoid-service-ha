"""Redacted fleet support snapshot; never export webhook or private locators."""
from .const import DOMAIN,VERSION

async def async_get_config_entry_diagnostics(hass,entry):
    site=hass.data.get(DOMAIN,{}).get("site")
    if not site: return {"integration_version":VERSION,"loaded":False}
    return {"integration_version":VERSION,"loaded":True,"nodes":[{
        "node_id":n.node_id,"http_reachable_at_last_check":n.reachable,
        "running_version":(n.status or {}).get("running_version"),
        "ota":(n.status or {}).get("wifi_ota",{}).get("state")
    } for n in site.registry.nodes.values()],"operations":[{
        k:v for k,v in op.items() if k in ("id","node_id","action","state","created_at","updated_at","artifact")
    } for op in site.registry.operations]}
