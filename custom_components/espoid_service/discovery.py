"""Explicit, bounded legacy HTTP discovery; profiles are not device identity."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
from time import monotonic
from urllib.parse import urlsplit
import uuid

import aiohttp

from .client import DeviceError, local_url

CONCURRENCY = 12
REQUEST_SECONDS = 1.5
SCAN_SECONDS = 40
RESULT_SECONDS = 120
RESPONSE_BYTES = 8192
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def search_network(value: str) -> ipaddress.IPv4Network:
    try:
        if not isinstance(value, str) or len(value) > 32 or "/" not in value:
            raise ValueError()
        network = ipaddress.ip_network(value.strip(), strict=False)
        if (network.version != 4 or network.num_addresses > 256
                or not any(network.subnet_of(private) for private in PRIVATE_NETWORKS)):
            raise ValueError()
        return network
    except (ValueError, TypeError):
        raise DeviceError("invalid_search_network") from None


def suggested_network(origin: str) -> str:
    address = ipaddress.IPv4Address(urlsplit(local_url(origin)).hostname)
    # A UI suggestion only: a last IP does not prove the actual network mask.
    return str(ipaddress.ip_network(f"{address}/24", strict=False))


def ordered_hosts(network: ipaddress.IPv4Network, origin: str) -> list[str]:
    previous = int(ipaddress.IPv4Address(urlsplit(local_url(origin)).hostname))
    return [str(address) for address in sorted(network.hosts(), key=lambda address: (
        abs(int(address) - previous), int(address) < previous))]


def reject_constant(value):
    raise ValueError("Non-finite JSON")


def profile_candidate(data: object, url: str) -> dict | None:
    if (not isinstance(data, dict) or data.get("ok") is not True
            or data.get("source") not in ("stored", "default")
            or type(data.get("requiresReboot")) is not bool
            or "config" not in data
            or data.get("zigbeeAction") not in ("none", "reconfigure", "reinterview")):
        return None
    profile = data.get("config")
    if data["source"] == "default":
        if profile is not None:
            return None
        devices, buses = [], []
    else:
        if (not isinstance(profile, dict) or type(profile.get("schema")) is not int
                or profile["schema"] != 1 or not isinstance(profile.get("devices"), list)
                or len(profile["devices"]) > 64):
            return None
        devices, buses = profile["devices"], profile.get("buses", [])
        if not isinstance(buses, list) or len(buses) > 16:
            return None
        if not all(isinstance(item, dict) for item in (*devices, *buses)):
            return None

    def label(value):
        if not isinstance(value, str):
            return ""
        return "".join(character for character in value[:80] if character.isprintable())

    uart = []
    for bus in buses:
        if (bus.get("type") == "uart" and type(bus.get("tx")) is int
                and type(bus.get("rx")) is int and 0 <= bus["tx"] <= 30
                and 0 <= bus["rx"] <= 30):
            uart.append({"tx": bus["tx"], "rx": bus["rx"]})
    fingerprint = hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=True,
                                           separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"url": url, "source": data["source"],
            "devices": [{key: label(item.get(key)) for key in ("id", "name", "type")}
                        for item in devices], "uart": uart, "fingerprint": fingerprint}


def search_session():
    # Isolate cookies, auth and proxy configuration from HA's other HTTP clients.
    return aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar(), trust_env=False, auto_decompress=False,
                                 connector=aiohttp.TCPConnector(limit=CONCURRENCY),
                                 timeout=aiohttp.ClientTimeout(total=REQUEST_SECONDS))


async def probe(session, url: str) -> dict | None:
    try:
        async with session.get(url + "/api/device-config", allow_redirects=False) as response:
            if response.status != 200:
                return None
            raw = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                if len(raw) + len(chunk) > RESPONSE_BYTES:
                    return None
                raw.extend(chunk)
            return profile_candidate(json.loads(raw, parse_constant=reject_constant), url)
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, RecursionError):
        return None


async def verify_candidate(url: str) -> dict | None:
    async with search_session() as session:
        return await probe(session, url)


@dataclass
class SearchJob:
    entry_id: str
    origin: str
    cidr: str
    total: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "running"
    checked: int = 0
    candidates: dict = field(default_factory=dict)
    expires_at: float = 0
    task: asyncio.Task | None = None


class DiscoveryManager:
    """One job for all entries; short-lived RAM results and no startup scans."""

    def __init__(self):
        self.job: SearchJob | None = None

    @property
    def active(self):
        return self.job is not None and self.job.state == "running"

    def blocks(self, entry_id):
        return self.active and self.job.entry_id == entry_id

    def _valid(self, entry_id, job_id=None):
        job = self.job
        if (job is None or job.entry_id != entry_id or (job_id is not None and job.id != job_id)
                or (job.state != "running" and monotonic() >= job.expires_at)):
            raise DeviceError("search_expired")
        return job

    def snapshot(self, entry_id):
        try:
            job = self._valid(entry_id)
        except DeviceError:
            return {"job": None, "busy": self.active}
        return {"busy": self.active, "job": {
            "id": job.id, "cidr": job.cidr, "state": job.state,
            "checked": job.checked, "total": job.total,
            "candidates": [{key: value for key, value in candidate.items() if key != "fingerprint"}
                           for candidate in job.candidates.values()]}}

    def start(self, entry_id, origin, cidr, create_task):
        network = search_network(cidr)
        if self.active:
            raise DeviceError("search_busy")
        hosts = ordered_hosts(network, origin)
        job = SearchJob(entry_id, origin, str(network), len(hosts))
        self.job = job
        coroutine = self._run(job, hosts)
        try:
            job.task = create_task(coroutine)
        except Exception:
            coroutine.close()
            self.job = None
            raise DeviceError("search_failed") from None
        return self.snapshot(entry_id)

    async def _run(self, job, hosts):
        async def scan():
            async with search_session() as session:
                pending = iter(hosts)

                async def check(address):
                    candidate = await probe(session, f"http://{address}")
                    job.checked += 1
                    if candidate is not None:
                        job.candidates[candidate["url"]] = candidate

                # Complete the former IP first. Remaining workers consume the
                # nearest-first queue; results stream without awaiting a batch.
                if hosts and f"http://{hosts[0]}" == job.origin:
                    await check(next(pending))

                async def worker():
                    for address in pending:
                        await check(address)

                tasks = [asyncio.create_task(worker()) for _ in range(CONCURRENCY)]
                try:
                    await asyncio.gather(*tasks)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

        try:
            await asyncio.wait_for(scan(), timeout=SCAN_SECONDS)
            job.state = "complete"
        except TimeoutError:
            job.state = "timeout"
        except asyncio.CancelledError:
            job.state = "cancelled"
        except Exception:
            job.state = "failed"
        finally:
            job.expires_at = monotonic() + RESULT_SECONDS

    def candidate(self, entry_id, job_id, url, origin):
        job = self._valid(entry_id, job_id)
        if job.origin != origin or not isinstance(url, str) or url not in job.candidates:
            raise DeviceError("invalid_search_selection")
        return job, job.candidates[url]

    async def cancel(self, entry_id, job_id=None):
        job = self._valid(entry_id, job_id)
        if job.task is not None and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            # Cancellation before the task's first instruction still expires.
            if job.state == "running":
                job.state = "cancelled"
                job.expires_at = monotonic() + RESULT_SECONDS
        return self.snapshot(entry_id)

    async def clear_entry(self, entry_id):
        if self.job is not None and self.job.entry_id == entry_id:
            if self.active:
                await self.cancel(entry_id)
            self.job = None

    async def shutdown(self, event=None):
        if self.active:
            await self.cancel(self.job.entry_id)
        self.job = None
