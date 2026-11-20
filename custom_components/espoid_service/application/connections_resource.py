"""Public source observations and backend-owned binding/network commands."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from time import time_ns

from ..domain.errors import DeviceError
from ..domain.binding_policy import binding_key
from ..service_support import service_support
from .tracked_task import run_tracked_task


class ConnectionsResource:
    def __init__(self, registry, sources, bindings, network, enrollment, membership, profiles, notify,
                 *, create_task=asyncio.create_task):
        self.registry, self.sources = registry, sources
        self.bindings, self.network = bindings, network
        self.enrollment, self.membership, self.profiles = enrollment, membership, profiles
        self.notify, self.create_task = notify, create_task
        self.version, self.updated_at = time_ns() // 1000, None
        self.pending, self.errors, self.tasks = set(), {}, set()
        self.stopped = False
        self.published = {}
        bindings.changed = network.changed = self.changed
        sources.changed = self.changed

    def snapshot(self, identifier=None):
        rows = self._rows()
        base = {"entity": "connections", "id": "service", "version": self.version,
                "updated_at": self.updated_at}
        if identifier is None:
            return {**base, "connections": rows}
        row = next((row for row in rows if row["id"] == identifier), None)
        if row is None:
            raise DeviceError("z2m_device_missing")
        return {**base, "entity": "connection", "id": identifier, "data": row,
                "state": "saving" if identifier in self.pending else "idle",
                "error": self.errors.get(identifier), "validation": None}

    def changed(self):
        rows = {row["id"]: row for row in self._rows()}
        affected = {key for key in rows.keys() | self.published.keys() if rows.get(key) != self.published.get(key)}
        if not affected:
            return
        self.published = deepcopy(rows)
        self.version += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.notify({"entity": "connections", "id": "service", "version": self.version})
        # Only opened forms have a per-connection subscription.
        for identifier in affected:
            self.notify({"entity": "connection", "id": identifier, "version": self.version})

    async def execute(self, identifier, action, body, request_id):
        if action == "rebind" and body.get("confirmed") is not True:
            raise DeviceError("invalid_request")
        if self.stopped or identifier in self.pending:
            raise DeviceError("operation_busy")
        row = self.snapshot(identifier)["data"]
        readiness = "rebind" if action == "enroll" and body.get("reset") is True else action
        if readiness not in row["actions"] or not row["actions"][readiness]:
            reason = row.get("support", {}).get("reason")
            raise DeviceError(reason or "operation_busy")
        node = self._node(row)
        if node and (node.lock.locked() or self.registry.active(node.node_id) or self.profiles.busy(node.node_id)):
            raise DeviceError("operation_busy")
        self.pending.add(identifier)
        self.errors.pop(identifier, None)
        self.changed()
        return await run_tracked_task(
            self._execute(row, action, body, request_id), self.tasks, create_task=self.create_task
        )

    async def stop(self):
        self.stopped = True
        await asyncio.gather(*list(self.tasks), return_exceptions=True)

    def _rows(self):
        bindings = {binding_key(row): row for row in self.bindings.summaries()}
        jobs = self.network.summaries()
        rows = []
        for key, candidate in self.sources.catalog.items():
            identifier = connection_id(key)
            support = service_support(candidate)
            job = next((job for job in reversed(jobs) if job["key"] == key), None)
            # Other resources' transient node locks are checked at admission,
            # not cached as readiness without a matching lifecycle notification.
            busy = identifier in self.pending
            network_busy = bool(job and job["state"] not in ("done", "failed"))
            rows.append({
                "id": identifier, "kind": "zigbee", "name": candidate["name"],
                "prefix": candidate["prefix"], "ieee": candidate["ieee"],
                "admin_url": str(candidate.get("admin_url") or ""),
                "support": {field: support.get(field) for field in ("binding", "network", "reason")},
                "binding": bindings.get(key), "network": deepcopy(job),
                "service_url": self.registry.settings.get("service_base_url", ""),
                "error": self.errors.get(identifier),
                "actions": {
                    "bind": bool(not busy and support["binding"] and not network_busy and not (bindings.get(key) or {}).get("rebind_state")),
                    "refresh": bool(not busy and support["binding"] and bindings.get(key) and not (bindings.get(key) or {}).get("rebind_state")),
                    "rebind": bool(not busy and support["binding"] and not network_busy),
                    "wake": not busy and not network_busy,
                    "connect": bool(not busy and not network_busy and candidate.get("admin_url")),
                    "configure": bool(not busy and support["network"] and not network_busy),
                    "read": bool(not busy and support["network"]),
                    "start": bool(not busy and support["network"] and job and job["state"] == "ready"),
                },
            })
        for key, announcement in self.sources.announcements.items():
            if announcement.get("service_mqtt") == 1:
                identifier = connection_id("mqtt:" + key)
                binding = bindings.get("mqtt:" + key)
                busy = identifier in self.pending
                job = next((job for job in reversed(jobs) if job['key']=='mqtt:'+key),None)
                ready = bool(binding and binding['state']=='active')
                network_busy=bool(job and job['state'] not in ('done','failed'))
                rows.append({"id": identifier, "kind": "mqtt", "transport": "mqtt", "node_id": key,
                    "topic": announcement["topic"], "name": self.registry.nodes[key].name if key in self.registry.nodes else key,
                    "prefix": "", "ieee": "", "admin_url": str(announcement.get("admin_url") or ""),
                    "support": {"binding": True, "network": ready, "reason": None},
                    "binding": binding, "network": deepcopy(job), "service_url": self.registry.settings.get('service_base_url',''), "error": self.errors.get(identifier),
                    "actions": {"enroll": bool(not busy and (not binding or binding["state"] != "active")),
                                "rebind": bool(not busy and self.bindings.for_node(key)),
                                "refresh": bool(not busy and binding), "connect": False,
                                "configure":bool(not busy and ready and not network_busy),
                                "read":bool(not busy and ready), "start":False}})
                continue
            if key in self.registry.nodes:
                continue
            identifier = connection_id("announcement:" + key)
            rows.append({"id": identifier, "kind": "announcement", "name": key,
                "prefix": "", "ieee": "", "admin_url": str(announcement.get("admin_url") or ""),
                "support": {"binding": False, "network": False, "reason": None},
                "binding": None, "network": None, "service_url": "", "error": self.errors.get(identifier),
                "actions": {"connect": bool(identifier not in self.pending and announcement.get("admin_url"))}})
        return rows

    async def _execute(self, row, action, body, request_id):
        identifier = row["id"]
        try:
            node = self._node(row)
            if node and action != "connect":
                async with node.lock:
                    if self.registry.active(node.node_id) or self.profiles.busy(node.node_id):
                        raise DeviceError("operation_unresolved")
                    await self._perform(row, action, body, request_id)
            else:
                await self._perform(row, action, body, request_id)
            return {"id": identifier}
        except DeviceError as error:
            self.errors[identifier] = error.code
            raise
        except Exception as error:
            self.errors[identifier] = "outcome_uncertain"
            raise DeviceError("outcome_uncertain") from error
        finally:
            self.pending.discard(identifier)
            self.changed()

    async def _perform(self, row, action, body, request_id):
        identifier = row["id"]
        target = {field: row[field] for field in ("prefix", "ieee")}
        if row["kind"] == "mqtt":
            target={'transport':'mqtt','node_id':row['node_id']}
            if action == "enroll":
                result = await self.bindings.enroll_mqtt(row, body["certificate"], body["nonce"], reset=body.get("reset", False))
                await self.membership.add_bound(row, result["binding"])
            elif action == "refresh":
                snapshot = await self.bindings.mqtt_status(row["node_id"])
                if snapshot.get("error"):
                    raise DeviceError(snapshot["error"])
                await self.membership.add_bound(row, row["binding"])
                node = self.registry.nodes.get(row["node_id"])
                if node:
                    node.status, node.reachable, node.checked_at = snapshot["data"], True, datetime.now(timezone.utc).isoformat()
                    await self.registry.save()
            elif action=='configure':
                await self.network.submit(target,body,request_id,self.registry.settings.get('service_base_url',''))
            elif action=='read':
                await self.network.read(target)
            else:
                raise DeviceError("service_unsupported")
            return
        if action == "connect":
            candidate = self.sources.candidate(target) if row["kind"] == "zigbee" else None
            known = self._node(row)
            value = {"url": row["admin_url"], "name": row["name"][:80]}
            if candidate:
                value["z2m"] = target
            if known:
                value["node_id"] = known.node_id
            result = await self.enrollment.add(value, candidate=bool(known))
            if result.get("error"):
                self.errors[identifier] = result["error"]
        elif action in ("bind", "rebind", "refresh"):
            result = await self.bindings.execute(target, "status" if action == "refresh" else action)
            candidate = self.sources.candidate(target)
            if service_support(candidate).get("machine") and result.get("binding", {}).get("state") == "active":
                await self.membership.add_bound(candidate, result["binding"])
        elif action == "wake":
            await self.sources.command(target, "switch_to_wifi")
        elif action == "configure":
            await self.network.submit(target, body, request_id, self.registry.settings.get("service_base_url", ""))
        else:
            expected = body.get("expected_revision") if action == "start" else None
            if action == "start" and expected != (row["network"] or {}).get("job_id"):
                raise DeviceError("network_conflict")
            await self.network.read(target, start=action == "start", expected_job_id=expected)

    def _node(self, row):
        if row["kind"] == "mqtt":
            return self.registry.nodes.get(row["node_id"])
        if row["kind"] != "zigbee":
            return None
        target = {field: row[field] for field in ("prefix", "ieee")}
        return next((node for node in self.registry.nodes.values() if node.z2m == target), None)


def connection_id(key):
    return hashlib.sha256(key.encode()).hexdigest()[:32]
