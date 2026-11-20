"""Saved discovery observations and commands; no browser-owned scan jobs."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic, time_ns

from ..domain.errors import DeviceError
from ..domain.address_policy import validate_search_network
from .tracked_task import run_tracked_task

RESOURCE_ID = "service"


class SearchResource:
    def __init__(
        self, discovery, registry, sources, enrollment, notify, *,
        create_task=asyncio.create_task,
    ):
        self.discovery, self.registry, self.sources = discovery, registry, sources
        self.enrollment, self.notify, self.create_task = enrollment, notify, create_task
        # Short-lived RAM observations need a restart-distinct version on open pages.
        self.version = time_ns() // 1000
        self.updated_at, self.results, self.enrolling = None, [], False
        self.error = None
        self.last_progress = 0
        self.tasks, self.stopped = set(), False
        discovery.changed = self.changed

    def snapshot(self):
        job = self.discovery.job
        saved = self.discovery.snapshot(job.entry_id) if job else {"job": None}
        value = saved["job"]
        state = "idle"
        if self.error:
            state = "uncertain"
        if self.enrolling:
            state = "saving"
        elif value and value["state"] == "running":
            state = "refreshing"
        return {
            "id": RESOURCE_ID,
            "entity": "search",
            "version": self.version,
            "updated_at": self.updated_at,
            "state": state,
            "error": self.error,
            "validation": None,
            "data": {
                "cidr": (
                    value["cidr"] if value
                    else next(iter(self.registry.settings["search_networks"]), "")
                ),
                "node_id": job.entry_id if value and job.entry_id != "catalog" else "",
                "networks": list(self.registry.settings["search_networks"]),
                "revision": value["id"] if value else None,
                "progress": (
                    {key: value[key] for key in ("state", "checked", "total")}
                    if value else None
                ),
                "candidates": value["candidates"] if value else [],
                "results": deepcopy(self.results),
            },
        }

    def changed(self):
        job = self.discovery.job
        now = monotonic()
        if job and job.state == "running" and now - self.last_progress < 0.25:
            return
        self.last_progress = now
        self.version += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.notify({"entity": "search", "id": RESOURCE_ID, "version": self.version})

    def start(self, cidr, node_id=""):
        if self.stopped or self.enrolling:
            raise DeviceError("operation_busy")
        if not isinstance(cidr, str) or cidr not in self.registry.settings["search_networks"]:
            raise DeviceError("invalid_search_network")
        network = validate_search_network(cidr)
        if not isinstance(node_id, str):
            raise DeviceError("invalid_request")
        key = node_id or "catalog"
        origin = ""
        if node_id:
            node = self.registry.get(node_id)
            if self.registry.active(node_id):
                raise DeviceError("operation_unresolved")
            origin = node.origin
        if not origin:
            origin = "http://" + str(next(iter(network.hosts())))
        # The manager retains the bounded CIDR, concurrency and run timeout policy.
        self.discovery.start(key, origin, cidr, self.create_task)
        self.results = []
        self.error = None
        self.last_progress = 0
        self.changed()
        return {"id": RESOURCE_ID}

    async def cancel(self, revision):
        job = self._job(revision)
        await self.discovery.cancel(job.entry_id, job.id)
        self.changed()
        return {"id": RESOURCE_ID}

    async def add(self, revision, node_ids):
        if self.stopped or self.enrolling:
            raise DeviceError("operation_busy")
        job = self._job(revision)
        if (
            not isinstance(node_ids, list) or not node_ids or len(node_ids) > 256
            or any(not isinstance(key, str) for key in node_ids)
            or len(set(node_ids)) != len(node_ids)
        ):
            raise DeviceError("invalid_search_selection")
        candidates = []
        for key in node_ids:
            matches = [item for item in job.candidates.values() if item["node_id"] == key]
            if len(matches) != 1:
                raise DeviceError("invalid_search_selection")
            candidates.append(deepcopy(matches[0]))
        self.enrolling, self.results, self.error = True, [], None
        self.last_progress = 0
        self.changed()
        return await run_tracked_task(
            self._add(candidates), self.tasks, create_task=self.create_task
        )

    async def stop(self):
        self.stopped = True
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        await self.discovery.shutdown()

    def _job(self, revision):
        if not isinstance(revision, str) or not self.discovery.job:
            raise DeviceError("search_expired")
        return self.discovery.require_job(self.discovery.job.entry_id, revision)

    async def _add(self, candidates):
        try:
            for item in candidates:
                matches = [
                    value for value in self.sources.catalog.values()
                    if value["ieee"] == item.get("zigbee_ieee")
                ]
                value = {
                    "url": item["url"],
                    "node_id": item["node_id"],
                    "name": matches[0]["name"] if len(matches) == 1 else item["node_id"],
                }
                if len(matches) == 1:
                    value["z2m"] = {field: matches[0][field] for field in ("prefix", "ieee")}
                try:
                    result = await self.enrollment.add(value, candidate=True)
                except DeviceError as error:
                    result = {"id": item["node_id"], "error": error.code}
                self.results.append(result)
                self.last_progress = 0
                self.changed()
            return {"id": RESOURCE_ID}
        except Exception as error:
            self.error = "outcome_uncertain"
            raise DeviceError("outcome_uncertain") from error
        finally:
            self.enrolling = False
            self.last_progress = 0
            self.changed()
