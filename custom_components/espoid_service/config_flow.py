"""UI-only setup, including devices currently unavailable in Zigbee mode."""

from __future__ import annotations

import re
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import DeviceClient, DeviceError, local_url
from .const import DOMAIN
from .discovery import search_network


def settings_schema(defaults: dict, *, include_name: bool = False) -> vol.Schema:
    fields = {}
    if include_name:
        fields[vol.Required("name", default=defaults.get("name", "IO node"))] = str
    fields.update({
        vol.Required("base_url", default=defaults.get("base_url", "")): str,
        vol.Optional("firmware_base_url", default=defaults.get("firmware_base_url", "")): str,
        vol.Optional("mqtt_topic", default=defaults.get("mqtt_topic", "")): str,
        vol.Optional("discovery_cidr", default=defaults.get("discovery_cidr", "")): str,
        vol.Optional("check_connection", default=False): bool,
    })
    return vol.Schema(fields)


async def validate_settings(hass, data: dict, *, exclude_entry: str | None = None) -> dict:
    result = dict(data)
    result["base_url"] = local_url(data["base_url"])
    result["firmware_base_url"] = local_url(data["firmware_base_url"]) if data.get("firmware_base_url") else ""
    topic = data.get("mqtt_topic", "").strip()
    if topic and (len(topic.encode()) > 256 or not topic.endswith("/set")
                  or re.search(r"[+#\x00-\x1f]", topic)):
        raise DeviceError("invalid_topic")
    result["mqtt_topic"] = topic
    cidr = data.get("discovery_cidr", "")
    result["discovery_cidr"] = str(search_network(cidr)) if cidr else ""
    if "name" in result:
        result["name"] = result["name"].strip()
        if not 1 <= len(result["name"]) <= 80:
            raise DeviceError("invalid_name")
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id != exclude_entry and {**entry.data, **entry.options}.get("base_url") == result["base_url"]:
            raise DeviceError("already_configured")
    if result.pop("check_connection", False):
        await DeviceClient(async_get_clientsession(hass), result["base_url"]).status()
    return result


class ServiceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = await validate_settings(self.hass, user_input)
                # The legacy HTTP API does not expose a MAC. Never use the IP as
                # identity or pretend that an unverified MQTT topic proves it.
                await self.async_set_unique_id(uuid.uuid4().hex)
                return self.async_create_entry(title=data["name"], data=data)
            except DeviceError as err:
                errors["base"] = err.code
        return self.async_show_form(step_id="user", data_schema=settings_schema(user_input or {}, include_name=True), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ServiceOptionsFlow(config_entry)


class ServiceOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = await validate_settings(self.hass, user_input, exclude_entry=self._entry.entry_id)
                return self.async_create_entry(title="", data=data)
            except DeviceError as err:
                errors["base"] = err.code
        defaults = user_input or {**self._entry.data, **self._entry.options}
        return self.async_show_form(step_id="init", data_schema=settings_schema(defaults), errors=errors)

