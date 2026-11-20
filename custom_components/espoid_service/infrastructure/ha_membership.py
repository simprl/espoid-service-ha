"""Home Assistant ConfigSubentry access for device membership changes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class HaMembership:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry

    def data(self, member: ConfigSubentry) -> Mapping[str, Any]:
        return member.data

    def add(self, data: dict[str, Any]) -> None:
        member = ConfigSubentry(data=data, subentry_type="node", title=data["name"], unique_id=data["node_id"])
        self.hass.config_entries.async_add_subentry(self.entry, member)

    def update(self, member: ConfigSubentry, data: dict[str, Any]) -> None:
        self.hass.config_entries.async_update_subentry(self.entry, member, data=data, title=data["name"])

    def remove(self, member: ConfigSubentry) -> None:
        self.hass.config_entries.async_remove_subentry(self.entry, member.subentry_id)
