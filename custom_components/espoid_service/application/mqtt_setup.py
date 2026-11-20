"""Initial HTTP configuration followed by the existing MQTT binding owner."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import time

from ..domain.address_policy import validate_local_origin
from ..domain.errors import DeviceError
from ..domain.schema_policy import schema_matches
from ..resource_contract import RESOURCE_DEFINITIONS
from ..const import MAX_NODES
from ..infrastructure.devices.admin_client import AdminClient
from .tracked_task import run_tracked_task

RESOURCE_ID = "service"
BROKER_FIELDS = ("host", "port", "tls", "username", "topic_prefix", "discovery_prefix")


class MqttSetup:
    def __init__(
        self,
        storage,
        connections,
        enrollment,
        registry,
        notify,
        *,
        client_factory=AdminClient,
        create_task=asyncio.create_task,
        pause=asyncio.sleep,
        now=time.monotonic,
    ):
        self.storage, self.connections, self.enrollment, self.registry = (
            storage,
            connections,
            enrollment,
            registry,
        )
        self.notify, self.client_factory, self.create_task = (
            notify,
            client_factory,
            create_task,
        )
        self.pause, self.now = pause, now
        self.saved = {
            "key": secrets.token_hex(32),
            "broker_version": 0,
            "broker": {
                "host": "",
                "port": 1883,
                "tls": False,
                "username": "",
                "topic_prefix": registry.settings.get("announcement_prefix", "espoid"),
                "discovery_prefix": "homeassistant",
                "password": "",
            },
            "jobs": {},
            "version": 0,
        }
        self.tasks, self.lock, self.storage_lock, self.stopped = (
            {},
            asyncio.Lock(),
            asyncio.Lock(),
            False,
        )
        self.admissions = set()

    async def load(self):
        saved = await self.storage.async_load()
        if saved is not None:
            if not isinstance(saved, dict) or set(saved) != set(self.saved):
                raise DeviceError("storage_failed")
            self.saved = saved
        try:
            if not re.fullmatch(r"[a-f0-9]{64}", self.saved["key"]):
                raise ValueError()
            if (
                type(self.saved["version"]) is not int
                or not 0 <= self.saved["version"] < 2**53
            ):
                raise ValueError()
            if (
                type(self.saved["broker_version"]) is not int
                or not 0 <= self.saved["broker_version"] < 2**53
            ):
                raise ValueError()
            if set(self.saved["broker"]) != set(BROKER_FIELDS) | {"password"}:
                raise ValueError()
            if not isinstance(
                self.saved["broker"]["password"], str
            ) or not re.fullmatch(r"[ -~]{0,128}", self.saved["broker"]["password"]):
                raise ValueError()
            self._validate("ServiceMqttSetupData", self.snapshot()["data"])
            for node_id, job in self.saved["jobs"].items():
                job.setdefault("reset", False)
                job.setdefault("binding_pin", None)
                if node_id != job["node_id"] or set(job) != {
                    "node_id",
                    "url",
                    "broker_revision",
                    "request_id",
                    "phase",
                    "state",
                    "error",
                    "updated_at",
                    "mqtt_request_id",
                    "mqtt_confirmed",
                    "mqtt_revision",
                    "reset",
                    "binding_pin",
                }:
                    raise ValueError()
                validate_local_origin(job["url"])
                if job["binding_pin"] is not None and not re.fullmatch(
                    r"[a-f0-9]{64}", job["binding_pin"]
                ):
                    raise ValueError()
                if (
                    not re.fullmatch(r"[a-f0-9]{64}", job["broker_revision"])
                    or type(job["mqtt_confirmed"]) is not bool
                    or type(job["reset"]) is not bool
                ):
                    raise ValueError()
                if not re.fullmatch(r"[a-z0-9:-]{1,160}", job["request_id"]):
                    raise ValueError()
                if job["mqtt_request_id"] is not None and not re.fullmatch(
                    r"[a-f0-9]{32}", job["mqtt_request_id"]
                ):
                    raise ValueError()
                if job["mqtt_revision"] is not None and not re.fullmatch(
                    r"[0-9]{1,10}", job["mqtt_revision"]
                ):
                    raise ValueError()
        except (TypeError, ValueError, KeyError, AttributeError, DeviceError):
            raise DeviceError("storage_failed") from None
        for job in self.saved["jobs"].values():
            if job["state"] == "running":
                job.update(state="interrupted", error="setup_interrupted")
        await self._persist()

    def snapshot(self):
        broker = {key: deepcopy(self.saved["broker"][key]) for key in BROKER_FIELDS}
        broker["password_set"] = bool(self.saved["broker"]["password"])
        jobs = [
            {
                key: job.get(key)
                for key in ("node_id", "url", "phase", "state", "error", "updated_at")
            }
            for job in self.saved["jobs"].values()
        ]
        return {
            "id": RESOURCE_ID,
            "entity": "mqtt_setup",
            "version": self.saved["version"],
            "updated_at": None,
            "state": "idle",
            "error": None,
            "validation": None,
            "data": {"broker": broker, "revision": self._revision(), "jobs": jobs},
        }

    async def save_broker(self, body):
        if self.stopped:
            raise DeviceError("operation_busy")
        return await run_tracked_task(
            self._save_broker(body), self.admissions, create_task=self.create_task
        )

    async def _save_broker(self, body):
        self._validate("ServiceMqttBrokerSave", body)
        async with self.lock:
            if self.stopped or self.tasks:
                raise DeviceError("operation_busy")
            if body["expected_revision"] != self._revision():
                raise DeviceError("revision_conflict")
            data = body["data"]
            if data["topic_prefix"] != self.registry.settings.get(
                "announcement_prefix", "espoid"
            ):
                raise DeviceError("setup_prefix_mismatch")
            password = self.saved["broker"]["password"]
            if data["password_action"] == "set":
                if not data.get("password"):
                    raise DeviceError("invalid_request")
                password = data["password"]
            elif data["password_action"] == "clear":
                password = ""
            self.saved["broker"] = {key: data[key] for key in BROKER_FIELDS} | {
                "password": password
            }
            if self.saved["broker_version"] >= 2**53 - 1:
                raise DeviceError("storage_failed")
            self.saved["broker_version"] += 1
            await self._persist()
        return {"id": RESOURCE_ID}

    async def start(self, body, request_id, owner):
        if self.stopped:
            raise DeviceError("operation_busy")
        return await run_tracked_task(
            self._start(body, request_id, owner),
            self.admissions,
            create_task=self.create_task,
        )

    async def _start(self, body, request_id, owner):
        self._validate("ServiceMqttSetupRequest", body)
        origin = validate_local_origin(body["url"])
        if (
            not owner
            or not isinstance(request_id, str)
            or not re.fullmatch(r"[a-z0-9:-]{1,160}", request_id)
        ):
            raise DeviceError("invalid_request")
        key = body["node_id"]
        async with self.lock:
            if self.stopped:
                raise DeviceError("operation_busy")
            if (
                body["broker_revision"] != self._revision()
                or not self.saved["broker"]["host"]
            ):
                raise DeviceError("revision_conflict")
            if self.saved["broker"]["topic_prefix"] != self.registry.settings.get(
                "announcement_prefix", "espoid"
            ):
                raise DeviceError("setup_prefix_mismatch")
            old = self.saved["jobs"].get(key)
            if old and old["request_id"] == request_id:
                if (
                    old["url"] != origin
                    or old["broker_revision"] != body["broker_revision"]
                    or old["reset"] != body.get("reset", False)
                ):
                    raise DeviceError("revision_conflict")
                return {"id": RESOURCE_ID}
            if key in self.tasks or (
                self.registry.nodes.get(key) and self.registry.active(key)
            ):
                raise DeviceError("operation_busy")
            same_broker = old and old["broker_revision"] == body["broker_revision"]
            if len(self.saved["jobs"]) >= MAX_NODES and old is None:
                raise DeviceError("too_many_nodes")
            # A new explicit request may check an interrupted exchange, never
            # recreate a write whose durable receipt has not been confirmed.
            job = {
                "node_id": key,
                "reset": body.get("reset", False),
                "binding_pin": old.get("binding_pin")
                if old and old["reset"] == body.get("reset", False)
                else None,
                "url": origin,
                "broker_revision": body["broker_revision"],
                "request_id": request_id,
                "phase": "checking",
                "state": "running",
                "error": None,
                "mqtt_request_id": old.get("mqtt_request_id") if same_broker else None,
                "mqtt_confirmed": old.get("mqtt_confirmed", False)
                if same_broker
                else False,
                "mqtt_revision": old.get("mqtt_revision") if same_broker else None,
                "updated_at": None,
            }
            self.saved["jobs"][key] = job
            try:
                await self._persist()
            except Exception:
                job.update(state="interrupted", error="storage_failed")
                self.notify(
                    {
                        "entity": "mqtt_setup",
                        "id": RESOURCE_ID,
                        "version": self.saved["version"],
                    }
                )
                raise DeviceError("storage_failed") from None
            self.tasks[key] = self.create_task(
                self._run(job, body["admin_password"], owner)
            )
        return {"id": RESOURCE_ID}

    async def stop(self):
        self.stopped = True
        await asyncio.gather(*list(self.admissions), return_exceptions=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Cancellation before the coroutine starts does not enter its finally.
        if self.tasks:
            for node_id in self.tasks:
                self.saved["jobs"][node_id].update(
                    state="interrupted", error="setup_interrupted"
                )
            self.tasks.clear()
            await self._persist()

    async def _run(self, job, password, owner):
        client = None
        try:
            client = self.client_factory(job["url"], job["node_id"], password)
            await client.login()
            status = (await client.item("status"))["data"]
            if status["recovery"]["active"] or status["restart_mode"] == "ota":
                raise DeviceError("setup_mode_unavailable")
            mqtt = await self._configure(job, client)
            await self._phase(job, "entering_service")
            if not status["service_mode"] or mqtt["data"]["status"][
                "applied_revision"
            ] != int(mqtt["revision"]):
                action = "restart" if status["service_mode"] else "service_enter"
                previous = await client.command(action)
                await client.wait_boot(previous)
            status = (await client.item("status"))["data"]
            if not status["service_mode"]:
                raise DeviceError("service_mode_required")
            applied = await client.item("mqtt")
            if applied["revision"] != mqtt["revision"] or applied["data"]["status"][
                "applied_revision"
            ] != int(mqtt["revision"]):
                raise DeviceError("setup_mqtt_unconfirmed")
            await self._phase(job, "waiting_mqtt")
            row = await self._connection(job)
            await self._phase(job, "binding")
            binding = row.get("binding") or {}
            reset_pending = (
                job["reset"] and binding.get("certificate_sha256") != job["binding_pin"]
            )
            if reset_pending or binding.get("state") != "active":
                self.enrollment.create(row["id"], owner, reset=job["reset"])
                offer = self.enrollment.snapshot(row["id"], owner)
                if (
                    offer["node_id"] != job["node_id"]
                    or validate_local_origin(offer["origin"]) != job["url"]
                ):
                    raise DeviceError("identity_mismatch")
                proof = await client.authorize(offer)
                if proof.get("node_id") != job["node_id"]:
                    raise DeviceError("identity_mismatch")
                job["binding_pin"] = hashlib.sha256(
                    bytes.fromhex(proof["certificate"])
                ).hexdigest()
                await self._persist()
                await self.enrollment.enroll(
                    row["id"],
                    owner,
                    {
                        "offer_id": offer["offer_id"],
                        "certificate": proof["certificate"],
                    },
                    secrets.token_hex(16),
                )
            else:
                await self.connections.execute(
                    row["id"], "refresh", {}, secrets.token_hex(16)
                )
            await self._phase(job, "leaving_service")
            status = (await client.item("status"))["data"]
            if status["service_mode"]:
                profile = await client.item("profile")
                previous = await client.command("service_exit", profile["revision"])
                await client.wait_boot(previous)
            status = (await client.item("status"))["data"]
            if status["service_mode"] or status["recovery"]["active"]:
                raise DeviceError("setup_restart_unconfirmed")
            await self.connections.execute(
                row["id"], "refresh", {}, secrets.token_hex(16)
            )
            job.update(state="complete", phase="complete", error=None)
        except asyncio.CancelledError:
            job.update(state="interrupted", error="setup_interrupted")
        except DeviceError as error:
            job.update(state="interrupted", error=error.code)
        except Exception:
            job.update(state="interrupted", error="outcome_uncertain")
        finally:
            password = ""
            if client:
                await client.close()
            self.tasks.pop(job["node_id"], None)
            try:
                await self._persist()
            except Exception:
                job.update(state="interrupted", error="storage_failed")
                self.notify(
                    {
                        "entity": "mqtt_setup",
                        "id": RESOURCE_ID,
                        "version": self.saved["version"],
                    }
                )

    async def _configure(self, job, client):
        await self._phase(job, "configuring_mqtt")
        current = await client.item("mqtt")
        broker = self.saved["broker"]
        expected = {key: broker[key] for key in BROKER_FIELDS}
        matches = all(
            current["data"].get(key) == value for key, value in expected.items()
        )
        matches = matches and current["data"].get("password_set") == bool(
            broker["password"]
        )
        # A successful settings write increments the guarded revision once.
        # Its HTTP receipt is boot-local, so durable confirmation also fences
        # a later read by that exact saved revision after the applying reboot.
        confirmed_revision = (
            str(int(job["mqtt_revision"]) + 1)
            if job["mqtt_revision"] is not None
            else None
        )
        if (
            job["mqtt_confirmed"]
            and matches
            and current["revision"] == confirmed_revision
        ):
            return current
        if (
            job["mqtt_request_id"]
            and matches
            and current.get("request_id") == job["mqtt_request_id"]
            and current["revision"] == confirmed_revision
        ):
            job["mqtt_confirmed"] = True
            await self._persist()
            return current
        if job["mqtt_request_id"] and (
            job["mqtt_confirmed"] or current["revision"] != job["mqtt_revision"]
        ):
            raise DeviceError("setup_mqtt_unconfirmed")
        if not job["mqtt_request_id"]:
            job["mqtt_request_id"] = secrets.token_hex(16)
            job["mqtt_revision"] = current["revision"]
            await self._persist()
        data = expected | {"password_action": "set" if broker["password"] else "clear"}
        if broker["password"]:
            data["password"] = broker["password"]
        await client.save_mqtt(job["mqtt_request_id"], job["mqtt_revision"], data)
        confirmed = await client.item("mqtt")
        if (
            confirmed.get("request_id") != job["mqtt_request_id"]
            or any(
                confirmed["data"].get(key) != value for key, value in expected.items()
            )
            or confirmed["data"].get("password_set") != bool(broker["password"])
            or confirmed["revision"] != str(int(job["mqtt_revision"]) + 1)
        ):
            raise DeviceError("setup_mqtt_unconfirmed")
        job["mqtt_confirmed"] = True
        await self._persist()
        return confirmed

    async def _connection(self, job):
        deadline = self.now() + 45
        expected_topic = self.saved["broker"]["topic_prefix"] + "/" + job["node_id"]
        while self.now() < deadline:
            rows = self.connections.snapshot()["connections"]
            for row in rows:
                if row["kind"] == "mqtt" and row.get("node_id") == job["node_id"]:
                    if row.get("topic") != expected_topic:
                        raise DeviceError("binding_identity_mismatch")
                    return row
            await self.pause(1)
        raise DeviceError("setup_mqtt_timeout")

    async def _phase(self, job, phase):
        job["phase"] = phase
        await self._persist()

    async def _persist(self):
        async with self.storage_lock:
            self.saved["version"] += 1
            for job in self.saved["jobs"].values():
                if job["state"] == "running":
                    job["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self.storage.async_save(deepcopy(self.saved))
            self.notify(
                {
                    "entity": "mqtt_setup",
                    "id": RESOURCE_ID,
                    "version": self.saved["version"],
                }
            )

    def _revision(self):
        raw = json.dumps(
            [self.saved["broker_version"], self.saved["broker"]],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hmac.new(
            bytes.fromhex(self.saved["key"]), raw, hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _validate(name, value):
        if not schema_matches(RESOURCE_DEFINITIONS, RESOURCE_DEFINITIONS[name], value):
            raise DeviceError("invalid_request")
