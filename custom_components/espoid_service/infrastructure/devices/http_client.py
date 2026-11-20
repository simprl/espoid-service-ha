"""Bounded HTTP transport for public discovery reads."""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from ...const import STATUS_MAX_BYTES
from ...domain.address_policy import validate_local_origin as local_url
from ...domain.errors import DeviceError


class HttpClient:
    def __init__(self, session: aiohttp.ClientSession, origin: str) -> None:
        self.session = session
        self.origin = local_url(origin)

    async def read_json(self, path: str) -> Any:
        try:
            async with self.session.request(
                "GET", self.origin + path,
                timeout=aiohttp.ClientTimeout(total=10, connect=3), allow_redirects=False,
            ) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    if len(raw) + len(chunk) > STATUS_MAX_BYTES:
                        raise DeviceError("response_too_large")
                    raw.extend(chunk)
                if response.status != 200:
                    esp_error = None
                    try:
                        error = json.loads(raw).get("error", "")
                        if isinstance(error, str) and error.startswith("ESP_") and len(error) < 80:
                            esp_error = error
                    except (ValueError, AttributeError):
                        pass
                    raise DeviceError("device_rejected", esp_error)
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("ok") is False:
                    raise DeviceError("device_rejected")
                return data
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DeviceError("cannot_connect") from err
        except (UnicodeError, ValueError, RecursionError) as err:
            raise DeviceError("invalid_response") from err

