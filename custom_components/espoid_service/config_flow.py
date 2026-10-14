"""One site entry; physical-node subentries share resources and retain IDs."""
from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, MAX_NODES
from .client import DeviceError
from .model import settings, node_settings
from .service_client import ServiceClient


def site_schema(defaults):
    return vol.Schema({vol.Optional("firmware_base_url", default=defaults.get("firmware_base_url", "")):str,
        vol.Optional("search_networks", default=", ".join(defaults.get("search_networks", []))):str,
        vol.Optional("z2m_prefixes", default=", ".join(defaults.get("z2m_prefixes", []))):str,
        vol.Optional("announcement_prefix", default=defaults.get("announcement_prefix", "espoid")):str})


class ServiceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2
    MINOR_VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id("site")
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            try:
                return self.async_create_entry(title="ESPOID Service", data=settings(user_input))
            except DeviceError as err: errors["base"] = err.code
        return self.async_show_form(step_id="user", data_schema=site_schema({}), errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                return self.async_update_reload_and_abort(entry, data_updates=settings(user_input))
            except DeviceError as err: errors["base"] = err.code
        return self.async_show_form(step_id="reconfigure", data_schema=site_schema(entry.data), errors=errors)

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {"node": NodeSubentryFlow}


class NodeSubentryFlow(config_entries.ConfigSubentryFlow):
    async def async_step_user(self, user_input=None):
        entry = self._get_entry()
        errors = {}
        if len(entry.subentries) >= MAX_NODES: return self.async_abort(reason="node_limit")
        if user_input is not None:
            try:
                client = ServiceClient(async_get_clientsession(self.hass), user_input["base_url"])
                found = await client.identity()
                if any(s.unique_id == found["node_id"] for s in entry.subentries.values()):
                    return self.async_abort(reason="already_configured")
                data = node_settings({**user_input,"node_id":found["node_id"]})
                return self.async_create_entry(title=data["name"], data=data, unique_id=data["node_id"])
            except DeviceError as err: errors["base"] = err.code
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("base_url"):str,vol.Optional("name",default="ESPOID"):str}), errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        entry, sub = self._get_entry(), self._get_reconfigure_subentry()
        errors = {}
        if user_input is not None:
            try:
                data = node_settings({**sub.data, **user_input})
                if data["base_url"]:
                    await ServiceClient(async_get_clientsession(self.hass),data["base_url"]).verify(sub.unique_id)
                return self.async_update_and_abort(entry,sub,data=data,title=data["name"])
            except DeviceError as err: errors["base"] = err.code
        return self.async_show_form(step_id="reconfigure",data_schema=vol.Schema({
            vol.Required("name",default=sub.title):str,
            vol.Optional("base_url",default=sub.data.get("base_url","")):str}),errors=errors)
