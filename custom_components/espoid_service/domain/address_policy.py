"""Pure origin and discovery-network rules; no HTTP or Home Assistant imports."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from .errors import DeviceError

PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def validate_local_origin(value: str) -> str:
    """Accept explicit local IPv4 HTTP origins without credentials or subpaths."""
    if (
        not isinstance(value, str)
        or len(value) > 200
        or any(ord(char) < 32 for char in value)
    ):
        raise DeviceError("invalid_url")
    try:
        parsed = urlsplit(
            value.strip() if "://" in value else f"http://{value.strip()}"
        )
        address = ipaddress.IPv4Address(parsed.hostname or "")
        port = parsed.port
    except ValueError as error:
        raise DeviceError("invalid_url") from error
    if (
        parsed.scheme != "http"
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise DeviceError("invalid_url")
    return f"http://{address}" + (f":{port}" if port and port != 80 else "")


def validate_service_origin(value: str) -> str:
    """Accept the existing Service HTTP/HTTPS host policy."""
    if (
        not isinstance(value, str)
        or not value.isascii()
        or len(value) > 192
        or any(ord(char) < 32 for char in value)
    ):
        raise DeviceError("invalid_url")
    try:
        parsed = urlsplit(value.strip())
        host, port = parsed.hostname, parsed.port
        if (
            parsed.scheme not in ("http", "https")
            or not host
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or any(ord(char) < 33 for char in value.strip())
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError()
    except ValueError:
        raise DeviceError("invalid_url") from None
    result = f"{parsed.scheme}://{host}" + (f":{port}" if port else "")
    if len(result) > 192:
        raise DeviceError("invalid_url")
    return result


def validate_search_network(value: str) -> ipaddress.IPv4Network:
    """Accept private IPv4 networks with at most 256 addresses."""
    try:
        if not isinstance(value, str) or len(value) > 32 or "/" not in value:
            raise ValueError()
        network = ipaddress.ip_network(value.strip(), strict=False)
        if (
            network.version != 4
            or network.num_addresses > 256
            or not any(network.subnet_of(private) for private in PRIVATE_NETWORKS)
        ):
            raise ValueError()
        return network
    except (ValueError, TypeError):
        raise DeviceError("invalid_search_network") from None
