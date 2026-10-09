"""Admin-only, fixed-route bridge. No arbitrary proxy or integration updater."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.exceptions import HomeAssistantError

from .client import DeviceError
from .const import API_PREFIX, APP_MAX_BYTES, DOMAIN, PROFILE_MAX_BYTES


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
            async with device.client.lock:
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
            async with device.client.lock:
                if action == "profile_validate":
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
