"""Admin-only, fixed-route bridge. No arbitrary proxy or integration updater."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.exceptions import HomeAssistantError

from .client import DeviceError, local_url
from .const import API_PREFIX, APP_MAX_BYTES, DOMAIN, PROFILE_MAX_BYTES
from .discovery import suggested_network, verify_candidate


def require_admin(request):
    user = request.get("hass_user")
    if user is None or not user.is_admin:
        raise web.HTTPForbidden()


def runtime(hass, entry_id):
    device = hass.data[DOMAIN]["devices"].get(entry_id)
    if device is None:
        raise web.HTTPNotFound()
    return device


def error_response(err):
    return web.json_response({"ok": False, "error": err.code, "esp_error": err.esp_error}, status=400)


async def bounded_json(request):
    raw = bytearray()
    async for chunk in request.content.iter_chunked(4096):
        if len(raw) + len(chunk) > PROFILE_MAX_BYTES * 3:
            raise web.HTTPRequestEntityTooLarge(max_size=PROFILE_MAX_BYTES * 3, actual_size=len(raw) + len(chunk))
        raw.extend(chunk)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError) as err:
        raise DeviceError("invalid_request") from err


async def refresh(device):
    device.checked_at = datetime.now(timezone.utc).isoformat()
    try:
        device.status = await device.client.status()
        device.reachable = True
        return device.status
    except DeviceError:
        device.reachable = False
        raise


class DevicesView(HomeAssistantView):
    requires_auth = True
    url = API_PREFIX + "/devices"
    name = DOMAIN + ":devices"

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        require_admin(request)
        return web.json_response({"devices": [
            {"id": key, "name": device.entry.title, "base_url": device.client.origin,
             "mqtt_configured": bool(device.settings.get("mqtt_topic")),
             "firmware_base_url": device.settings.get("firmware_base_url", ""),
             "discovery_cidr": device.settings.get("discovery_cidr") or suggested_network(device.client.origin),
             "reachable": device.reachable, "checked_at": device.checked_at,
             "status": device.status, "last_action": device.last_action}
            for key, device in self.hass.data[DOMAIN]["devices"].items()]})


class DeviceView(HomeAssistantView):
    requires_auth = True
    url = API_PREFIX + "/devices/{entry_id}/{action}"
    name = DOMAIN + ":device"

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request, entry_id, action):
        require_admin(request)
        device = runtime(self.hass, entry_id)
        try:
            search = self.hass.data[DOMAIN].get("discovery")
            if action == "discovery":
                return web.json_response(search.snapshot(entry_id), headers={"Cache-Control": "no-store"})
            async with device.client.lock:
                if search and search.blocks(entry_id):
                    raise DeviceError("search_busy")
                if action == "status":
                    result = await refresh(device)
                elif action == "profile":
                    result = await device.client.profile()
                elif action == "diagnostics":
                    text = await device.client.diagnostics()
                    return web.Response(text=text, content_type="application/x-ndjson", headers={
                        "Content-Disposition": 'attachment; filename="espoid-diagnostics.ndjson"',
                        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
                else:
                    raise web.HTTPNotFound()
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except DeviceError as err:
            return error_response(err)

    async def post(self, request, entry_id, action):
        require_admin(request)
        device = runtime(self.hass, entry_id)
        try:
            body = await bounded_json(request)
            search = self.hass.data[DOMAIN].get("discovery")
            async with device.client.lock:
                if action == "discovery_start":
                    if set(body) != {"cidr"}:
                        raise DeviceError("invalid_request")
                    result = search.start(entry_id, device.client.origin, body["cidr"], self.hass.async_create_task)
                elif action == "discovery_cancel":
                    if set(body) != {"job_id"} or not isinstance(body["job_id"], str):
                        raise DeviceError("invalid_request")
                    result = await search.cancel(entry_id, body["job_id"])
                elif action == "discovery_apply":
                    result = await self._apply_address(device, body)
                elif search and search.blocks(entry_id):
                    raise DeviceError("search_busy")
                elif action == "profile_validate":
                    result = await device.client.validate_profile(body.get("profile"))
                elif action == "profile_store":
                    result = await device.client.store_profile(body.get("profile"))
                elif action in ("hold", "reboot_wifi", "reboot_zigbee", "recovery_retry"):
                    result = await device.client.command(action)
                    if action != "hold":
                        device.reachable = False
                elif action == "mqtt_wifi":
                    topic = device.settings.get("mqtt_topic")
                    if not topic or not self.hass.services.has_service("mqtt", "publish"):
                        raise DeviceError("mqtt_unavailable")
                    try:
                        await self.hass.services.async_call("mqtt", "publish", {
                            "topic": topic, "payload": '{"reload_and_then":"switch_to_wifi"}',
                            "qos": 0, "retain": False}, blocking=True)
                    except HomeAssistantError as err:
                        raise DeviceError("mqtt_unavailable") from err
                    result = {"ok": True, "accepted": True}
                elif action == "ota_install":
                    result = await self._install(device, body.get("firmware_id"))
                else:
                    raise web.HTTPNotFound()
                device.last_action = {"action": action, "at": datetime.now(timezone.utc).isoformat(),
                                      "accepted": True}
            return web.json_response(result)
        except DeviceError as err:
            return error_response(err)

    async def _apply_address(self, device, body):
        if (set(body) != {"job_id", "url", "confirmed"} or body["confirmed"] is not True
                or not isinstance(body["job_id"], str)):
            raise DeviceError("invalid_search_selection")
        entry_id = device.entry.entry_id
        search = self.hass.data[DOMAIN]["discovery"]
        job, candidate = search.candidate(entry_id, body["job_id"], body["url"], device.client.origin)
        await search.cancel(entry_id, job.id)
        current = await verify_candidate(candidate["url"])
        # Results can become stale while another admin edits/reloads an entry.
        search.candidate(entry_id, job.id, candidate["url"], device.client.origin)
        if (runtime(self.hass, entry_id) is not device
                or local_url({**device.entry.data, **device.entry.options}["base_url"]) != job.origin):
            raise DeviceError("search_expired")
        if current is None or current["fingerprint"] != candidate["fingerprint"]:
            raise DeviceError("search_candidate_changed")
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if (entry.entry_id != entry_id
                    and local_url({**entry.data, **entry.options}["base_url"]) == candidate["url"]):
                raise DeviceError("search_address_conflict")
        options = {**device.entry.options, "base_url": candidate["url"], "discovery_cidr": job.cidr}
        # Only HA options change. No ESP command, hold, reboot or OTA is sent.
        self.hass.config_entries.async_update_entry(device.entry, options=options)
        device.settings.update(base_url=candidate["url"], discovery_cidr=job.cidr)
        device.client.origin = candidate["url"]
        device.status, device.checked_at, device.reachable = None, None, False
        await search.clear_entry(entry_id)
        return {"ok": True, "base_url": candidate["url"], "discovery_cidr": job.cidr}

    async def _install(self, device, digest):
        library = self.hass.data[DOMAIN]["library"]
        manifest = await self.hass.async_add_executor_job(library.get, digest)
        base = device.settings.get("firmware_base_url")
        if not base:
            raise DeviceError("firmware_url_required")
        path = f"/local/firmware/{DOMAIN}/{digest}/index.json"
        url = f"{base}{path}"
        # Check actual unauthenticated HA publication before changing the ESP.
        # This tests HA -> HA, not ESP -> HA; device-side download can still fail.
        from .client import DeviceClient

        published = await DeviceClient(device.client.session, base).request(
            "GET", path)
        if published != {key: value for key, value in manifest.items() if key != "id"}:
            raise DeviceError("publication_failed")
        status = await refresh(device)
        ota = status.get("wifi_ota", {})
        if ota.get("running") or ota.get("verification_pending"):
            raise DeviceError("ota_busy")
        await device.client.set_manifest(url)
        result = await device.client.install()
        return {**result, "version": manifest["version"], "sha256": digest}


class FirmwareView(HomeAssistantView):
    requires_auth = True
    url = API_PREFIX + "/firmware"
    name = DOMAIN + ":firmware"

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        require_admin(request)
        try:
            entries = await self.hass.async_add_executor_job(self.hass.data[DOMAIN]["library"].list)
            return web.json_response({"firmware": entries})
        except (DeviceError, OSError):
            return error_response(DeviceError("storage_failed"))

    async def post(self, request):
        require_admin(request)
        try:
            fields = {}
            reader = await request.multipart()
            async for part in reader:
                if part.name not in ("manifest", "image") or part.name in fields:
                    raise DeviceError("invalid_firmware")
                limit = APP_MAX_BYTES if part.name == "image" else 4096
                raw = bytearray()
                while chunk := await part.read_chunk(8192):
                    if len(raw) + len(chunk) > limit:
                        raise DeviceError("invalid_firmware")
                    raw.extend(chunk)
                fields[part.name] = bytes(raw)
            if set(fields) != {"manifest", "image"}:
                raise DeviceError("invalid_firmware")
            manifest = json.loads(fields["manifest"])
            saved = await self.hass.async_add_executor_job(
                self.hass.data[DOMAIN]["library"].import_image, manifest, fields["image"])
            return web.json_response({"ok": True, "firmware": saved})
        except DeviceError as err:
            return error_response(err)
        except (ValueError, UnicodeError, KeyError, RecursionError):
            return error_response(DeviceError("invalid_firmware"))
        except OSError:
            return error_response(DeviceError("storage_failed"))


def register_views(hass):
    for view in (DevicesView, DeviceView, FirmwareView):
        hass.http.register_view(view(hass))
