"""Durable profile resources. Browsers read snapshots and submit intents only."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Protocol

from ..domain.errors import DeviceError
from ..domain.configuration_files_policy import file_upload, selected_files, verify_file_receipt, same_selection, verify_file_boot, FILE_COUNT
from ..const import DOMAIN, MAX_NODES
from ..domain.profile_policy import confirmed_profile, profile_json, validate_profile_records
from ..domain.interruption_policy import interrupt, public_interruption, require_interruption, latest_interrupted_request, INTERRUPTION_ERRORS
from ..registry import timestamp
from .tracked_task import run_tracked_task

RESOURCE_EVENT = f"{DOMAIN}_resource_changed"
UNCERTAIN = {"cannot_connect", "readback_failed", "invalid_response", "machine_storage", "storage_failed"}


class ProfileSnapshots:
    def __init__(self, storage: ProfileStorage, registry, maintenance, notify, *, create_task=asyncio.create_task):
        self.storage, self.registry, self.maintenance, self.notify = storage, registry, maintenance, notify
        self.create_task = create_task
        self.records = {}
        self.tasks = {}
        self.admissions = set()
        self.lock = asyncio.Lock()
        self.persist_lock = asyncio.Lock()
        self.stopped = False

    def empty(self, node_id):
        return {"id": node_id, "entity": "profile", "version": 0, "data": None,
                "desired": None, "updated_at": None, "state": "idle", "error": None,
                "validation": None, "pending": None, "staged_files": []}

    def snapshot(self, node_id):
        self.registry.get(node_id)
        record = self.records.get(node_id, self.empty(node_id))
        result=deepcopy({key: record.get(key, default) for key, default in self.empty(node_id).items() if key != "pending"})
        result['interruption']=public_interruption(record,requires_wifi=self.maintenance.supports(self.registry.get(node_id)))
        return result

    def busy(self, node_id):
        return bool(self.records.get(node_id, {}).get("pending"))

    async def prune(self):
        removed = [node_id for node_id in self.records if node_id not in self.registry.nodes]
        for node_id in removed:
            task = self.tasks.get(node_id)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.records.pop(node_id, None)
        if removed:
            await self.persist()

    async def load(self):
        saved = await self.storage.load()
        if saved is not None:
            self.records = validate_profile_records(saved)
        changed=False
        for record in self.records.values():
            if interrupt(record,timestamp()):record['version']+=1;changed=True
        if changed:await self.persist()

    async def persist(self):
        async with self.persist_lock:
            await self.storage.save(deepcopy(self.records))

    async def changed(self, record):
        record["version"] += 1
        await self.persist()
        self.notify({"entity": "profile", "id": record["id"], "version": record["version"]})

    async def reconcile(self,node):
        if self.stopped:return
        record=self.records.get(node.node_id)
        if record and record.get("staged_files") and record.get("staged_boot") and (node.status or {}).get("boot_id") and node.status["boot_id"] != record["staged_boot"]:
            record.update(staged_files=[],staged_boot=None)
            await self.changed(record)
        if not record or not record.get('interruption') or record['pending']:return
        original=record['interruption']['pending']
        pending=latest_interrupted_request(record)
        job=self.maintenance.jobs.get(node.node_id)
        if not job or job['id']!=pending.get('job_id') or job['state'] not in ('verified','failed'):return
        if job['state']=='failed':record.update(state='error',error='machine_failed',interruption=None)
        elif pending['action']=='validate':record.update(state='idle',error=None,validation={'ok':True},interruption=None)
        elif pending['action']=='upload':
            version=record['version']
            result=await self.maintenance.result(node,job['id'])
            if self.stopped or record['pending'] or record['version']!=version:return
            self.accept_file(record,result,pending)
            record.update(state='idle',error=None,interruption=None)
        elif pending['action'] in ('refresh','check') or pending.get('stage')=='readback':
            version=record['version']
            result=await self.maintenance.result(node,job['id'])
            if self.stopped or record['pending'] or record['version']!=version:return
            profile=confirmed_profile(result['profile'])
            expected=original if pending['action']=='check' else pending
            if expected['action']=='save' and not same_selection(profile,expected):
                record.update(data=profile,updated_at=timestamp(),error='result_differs')
                await self.changed(record)
                return
            record.update(data=profile,updated_at=timestamp(),state='idle',error=None,desired=None,interruption=None,staged_files=[])
        else:return # A write acknowledgement alone is not profile readback.
        await self.changed(record)

    def launch(self, node_id):
        task = self.create_task(self.run(node_id))
        self.tasks[node_id] = task
        task.add_done_callback(lambda done: self.tasks.pop(node_id, None) if self.tasks.get(node_id) is done else None)

    async def upload(self, node_id, identifier, mime_type, content, expected_revision):
        candidate, payload = file_upload(identifier, mime_type, content, expected_revision)
        return await run_tracked_task(
            self.admit(node_id, "upload", None, expected_revision, candidate, payload),
            self.admissions, create_task=self.create_task)

    async def command(self, node_id, action, profile=None, expected_revision=None, expected_version=None):
        # Browser cancellation must not interrupt a durably admitted intent.
        return await run_tracked_task(
            self.admit(node_id, action, profile, expected_revision, expected_version=expected_version),
            self.admissions,
            create_task=self.create_task,
        )

    async def admit(self, node_id, action, profile, expected_revision, candidate=None, payload=None, expected_version=None):
        if self.stopped or action not in ("refresh", "save", "validate", "check", "upload"):
            raise DeviceError("invalid_request")
        node = self.registry.get(node_id)
        if not self.maintenance.supports(node):
            raise DeviceError("service_unsupported")
        if action in ('save','validate'):
            profile_json(profile)
        async with node.lock:
            async with self.lock:
                record = self.records.get(node_id)
                if record and record.get("pending"):
                    raise DeviceError("operation_unresolved")
                interrupted=record.get('interruption') if record else None
                if interrupted and action in ('save','validate','upload'):raise DeviceError('operation_unresolved')
                original=None
                if action=='check':
                    original=deepcopy(require_interruption(record or {},expected_revision))
                elif action=='refresh' and interrupted:
                    original=deepcopy(interrupted['pending'])
                    if original['action']=='save':action='check'
                active = self.registry.active(node_id)
                if active:
                    # Explicit refresh can reconcile this resource's own uncertain
                    # operation. Retain its unverified history; never replay its write.
                    check_pending=(interrupted or {}).get('check_pending',{})
                    allowed_ids={(original or {}).get('job_id'),(original or {}).get('operation_id'),
                        check_pending.get('job_id'),check_pending.get('operation_id'),(record or {}).get('unresolved_id')}
                    if action not in ('refresh','check') or active['id'] not in allowed_ids:
                        raise DeviceError("operation_unresolved")
                    if self.maintenance.supports(node):
                        await self.maintenance.prepare_read(node,active['id'])
                    else:await self.registry.transition(active, "closed_unverified", "snapshot_refresh")
                    record.pop("unresolved_id", None)
                if record is None and len(self.records) >= MAX_NODES:
                    raise DeviceError("node_limit")
                record = self.records.setdefault(node_id, self.empty(node_id))
                if action in ("save", "upload"):
                    if record["data"] is None:
                        raise DeviceError("machine_profile_read_required")
                    if expected_revision != record["data"]["revision"]:
                        raise DeviceError("profile_conflict")
                if action == "upload" and record["data"].get("requiresReboot"):
                    raise DeviceError("restart_required")
                if action == "save" and profile.get("files") and (type(expected_version) is not int or expected_version != record["version"]):
                    raise DeviceError("profile_conflict")
                references = selected_files(profile, record["data"], record.get("staged_files", [])) if action in ("save", "validate") else None
                if action == "upload" and len(record.get("staged_files", [])) >= FILE_COUNT and not any(
                    item["id"] == candidate["id"] for item in record["staged_files"]):
                    raise DeviceError("storage_full")
                record.update(state={"refresh": "refreshing", "check":"refreshing", "save": "saving", "validate": "validating", "upload":"uploading"}[action],
                              error=None, validation=None,
                              pending={"action": action, "profile": deepcopy(profile), "expected_revision": expected_revision})
                if references is not None: record["pending"]["files"] = references
                if candidate is not None: record["pending"]["file"] = deepcopy(candidate)
                if original:record['pending']['original']=original
                if action == "save":
                    record["desired"] = deepcopy(profile)
                await self.changed(record)
                try:
                    if self.maintenance.supports(node):
                        operation = {"refresh": "profile_read", "check":"profile_read", "save": "profile_store", "validate": "profile_validate", "upload": "profile_file"}[action]
                        transfer = {"config": profile, "files": references} if references is not None else payload
                        result = await self.maintenance.enqueue(node, operation, transfer,
                            expected_revision=expected_revision if action in ("save", "upload") else None)
                        record["pending"].update(job_id=result["job_id"], stage="apply")
                    await self.persist()
                except Exception as error:
                    await self.fail(record, error)
                    raise
                self.launch(node_id)
        return {"id": node_id}

    async def fail(self, record, error):
        pending = record.get("pending") or {}
        code = error.code if isinstance(error, DeviceError) else "storage_failed"
        if code in INTERRUPTION_ERRORS or pending.get('action')=='check' or record.get('interruption'):
            interrupt(record,timestamp(),code if pending.get('action')=='check' else 'operation_interrupted')
            await self.changed(record)
            return True
        uncertain = pending.get("action") == "save" and (
            code in UNCERTAIN or code == "outcome_uncertain" or pending.get("stage") in ("readback", "readback_pending"))
        if uncertain:
            record["unresolved_id"] = pending.get("job_id") or pending.get("operation_id")
        record.update(state="uncertain" if uncertain else "error",
                      error="outcome_uncertain" if uncertain else code, pending=None)
        await self.changed(record)
        return uncertain

    def accept_file(self, record, result, pending):
        boot=result.get("file_boot")
        current=(self.registry.get(record["id"]).status or {}).get("boot_id")
        verify_file_boot(boot,current)
        candidate = verify_file_receipt(result["file_receipt"], pending["file"], pending["job_id"])
        record["staged_files"] = [item for item in record.get("staged_files", []) if item["id"] != candidate["id"]] + [candidate]
        record["staged_boot"] = boot

    async def wait_job(self, node, identifier):
        while not self.stopped:
            result = await self.maintenance.result(node, identifier)
            if result["state"] == "verified":
                return result
            if result["state"] in ("failed", "uncertain", "closed_unverified"):
                raise DeviceError("outcome_uncertain" if result["state"] != "failed" else "machine_failed")
            await asyncio.sleep(1)
        raise asyncio.CancelledError

    async def run(self, node_id):
        record = self.records[node_id]
        pending = record["pending"]
        action = pending["action"]
        try:
            node = self.registry.get(node_id)
            if "job_id" in pending:
                result = await self.wait_job(node, pending["job_id"])
                if action == "save" and pending.get("stage") != "readback":
                    # Persist the readback stage before admitting another read-only job.
                    pending["stage"] = "readback_pending"
                    await self.persist()
                    async with node.lock:
                        read = await self.maintenance.enqueue(node, "profile_read")
                        pending.update(job_id=read["job_id"], stage="readback")
                        await self.persist()
                    result = await self.wait_job(node, pending["job_id"])
                if action in ("refresh", "save", "check"):
                    profile = confirmed_profile(result["profile"])
                elif action == "upload":
                    self.accept_file(record, result, pending)
                else:
                    record["validation"] = {"ok": True}
            else:
                raise DeviceError("machine_unavailable")
            if action in ("refresh", "save", "check"):
                if action == "save" and not same_selection(profile,pending):
                    raise DeviceError("readback_failed")
                if action=='check':
                    record.update(data=profile,updated_at=timestamp())
                    original=pending.get('original') or {}
                    if original.get('action')=='save' and not same_selection(profile,original):
                        raise DeviceError('result_differs')
                    identifier=original.get('job_id') or original.get('operation_id')
                    op=next((op for op in self.registry.operations if op['id']==identifier),None)
                    if op:await self.registry.transition(op,'verified','result_checked')
                record.update(data=profile, updated_at=timestamp(), desired=None,
                    staged_files=[] if action in ("save", "check") else [item for item in record.get("staged_files", []) if item["expected_revision"] == profile["revision"]])
            record.update(state="idle", error=None, pending=None,interruption=None)
            await self.changed(record)
        except asyncio.CancelledError:
            # load() exposes the interrupted result; it never replays this work.
            raise
        except Exception as error:
            operation_id = pending.get("operation_id")
            operation = next((op for op in self.registry.operations if op["id"] == operation_id), None)
            uncertain = await self.fail(record, error)
            if operation:
                await self.registry.transition(operation, "uncertain" if uncertain else "failed", record["error"])

    async def stop(self):
        self.stopped = True
        tasks = [*self.admissions, *self.tasks.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class ProfileStorage(Protocol):
    """Load raw records; save the resource's detached persistence snapshot."""

    async def load(self) -> object: ...

    async def save(self, records: dict[str, Any]) -> None: ...
