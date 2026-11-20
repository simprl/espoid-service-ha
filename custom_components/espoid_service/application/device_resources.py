"""Server-owned status reads, diagnostic artifacts and OTA execution/readback."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import secrets
from zipfile import ZipFile, ZIP_DEFLATED

from ..diagnostic_bundle import project, STATUS
from ..domain.errors import DeviceError
from ..domain.resource_policy import ENTITIES, CONTROL_ACTIONS, ota_can_confirm, validate_resource_records
from ..domain.interruption_policy import interrupt, public_interruption, require_interruption, latest_interrupted_request, INTERRUPTION_ERRORS
from ..domain.ota_policy import evaluate_ota_status
from ..domain.device_resource_policy import resource_request
from ..domain.mqtt_service_policy import control_supported
from ..domain.firmware_variant_policy import require_variant
from ..domain.equipment_policy import prepare_action, ACTIONS
from ..maintenance import diagnostic_parts, TERMINAL
from ..registry import timestamp
from .tracked_task import run_tracked_task


class DeviceResources:
    def __init__(self, storage, registry, maintenance, library, device_status, profiles,
                 files, run_io, notify, *, sources=None, discovery=None, equipment=None, create_task=asyncio.create_task):
        self.storage, self.registry, self.maintenance = storage, registry, maintenance
        self.library, self.device_status, self.profiles = library, device_status, profiles
        self.files, self.run_io, self.notify, self.create_task = files, run_io, notify, create_task
        self.records = {entity: {} for entity in ENTITIES}
        self.tasks, self.admissions = {}, set()
        self.persist_lock = asyncio.Lock()
        self.stopped = False
        self.sources, self.discovery = sources, discovery
        self.equipment = equipment
        self.settings_inputs = {}  # Write-only credentials never enter Store/snapshots.

    async def load(self):
        saved = await self.storage.load()
        if saved is not None:
            self.records = validate_resource_records(saved)
        changed=False
        for records in self.records.values():
            for record in records.values():
                if interrupt(record,timestamp()):
                    record['version']+=1;changed=True
        if changed:await self._persist()

    def snapshot(self, entity, node_id):
        node = self.registry.get(node_id)
        record = self._record(entity, node_id)
        snapshot = deepcopy({key: value for key, value in record.items() if key != "pending"})
        snapshot['interruption']=public_interruption(record,requires_wifi=entity=='diagnostics' and self.maintenance.supports(node))
        if entity == "ota":
            # 0.2.2 persisted OTA history before resource snapshots existed.
            # Expose that evidence even when the device is not yet bound.
            operation = self._operation(node_id)
            if operation is not None:
                snapshot["data"]["operation"] = deepcopy(operation)
            snapshot["data"]["modes"] = self._modes(node)
            snapshot["data"]["variant_id"] = (node.status or {}).get("variant_id", "")
            # UI readiness uses the same durable observation as the Status form.
            # Confirm admission still obtains fresh authenticated device evidence.
            status = self.records["status"].get(node_id, {}).get("data", {}).get("status")
            snapshot["data"]["can_confirm"] = ota_can_confirm(snapshot["data"].get("operation"), status)
        if entity == "control":
            saved = snapshot["data"].get("operation")
            current = self._operation(node_id, saved["id"]) if saved else None
            snapshot["data"]["operation"] = deepcopy(self.registry.active(node_id) or current or saved)
        return snapshot

    async def command(self, entity, node_id, action, body):
        return await run_tracked_task(self._admit(entity, node_id, action, body),
                                      self.admissions, create_task=self.create_task)

    async def observe(self, node):
        if self.stopped or not node.status:
            return
        record = self._record("status", node.node_id)
        status, _ = project(node.status, STATUS)
        if record["data"].get("status") == status and record["updated_at"] == node.checked_at:
            return
        record.update(data={"status": status}, updated_at=node.checked_at or timestamp())
        if record.get('interruption') and not record['pending']:
            record.update(state='idle',error=None,interruption=None)
        await self._changed(record)
        ota = self.records["ota"].get(node.node_id)
        if ota:
            before = deepcopy(ota["data"])
            self._ota_data(node, ota, self._operation(node.node_id))
            if ota["data"] != before:
                await self._changed(ota)

    async def reconcile(self,node):
        """Consume late authenticated evidence without issuing a device request."""
        if self.stopped:return
        for entity,records in self.records.items():
            record=records.get(node.node_id)
            if not record or not record.get('interruption') or record['pending']:continue
            pending=latest_interrupted_request(record)
            identifier=pending.get('job_id')
            job=self.maintenance.jobs.get(node.node_id)
            if not identifier or not job or job['id']!=identifier or job['state'] not in ('verified','failed'):continue
            if job['state']=='failed':
                record.update(state='error',error='machine_failed',interruption=None)
            else:
                if entity=='diagnostics':
                    # A checkpoint/transition result cannot finish the remaining
                    # collection steps after a restart. Only reconcile exports.
                    if pending.get('action') == 'save' and pending.get('stage') == 'save':
                        version = record['version']
                        result = await self.maintenance.result(node, identifier)
                        if self.stopped or record['pending'] or record['version'] != version:continue
                        record['data']['snapshot_generation'] = saved_generation(result)
                        record['updated_at'] = timestamp()
                    else:
                        if pending.get('stage') not in (None, 'export'):continue
                        if await self._collect(node,record,pending,only_version=record['version']) is False:continue
                elif entity=='control':self._control_data(node,record,pending)
                elif entity=='ota':
                    self._ota_data(node,record,self._operation(node.node_id,identifier))
                record.update(state='idle',error=None,interruption=None)
            await self._changed(record)

    async def prune(self):
        for entity, records in self.records.items():
            for node_id in list(records):
                if node_id not in self.registry.nodes:
                    task = self.tasks.get((entity, node_id))
                    if task:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    records.pop(node_id)
        await self._persist()

    async def stop(self):
        self.stopped = True
        tasks = [*self.admissions, *self.tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.settings_inputs.clear()

    async def artifact(self, node_id, identifier, trace=False):
        data = self.snapshot("diagnostics", node_id)["data"].get("artifact")
        if not data or data["id"] != identifier:
            raise DeviceError("machine_unavailable")
        suffix = "input" if trace else "output"
        expected = data["trace"] if trace else data["bundle"]
        try:
            raw = await self.files.read(identifier, suffix)
        except OSError:
            raise DeviceError("storage_failed") from None
        if await self.run_io(file_metadata, raw) != expected:
            raise DeviceError("storage_failed")
        return raw, data["completeness"]

    def _record(self, entity, node_id):
        if entity not in ENTITIES:
            raise DeviceError("invalid_request")
        return self.records[entity].setdefault(node_id, {
            "entity": entity, "id": node_id, "version": 0, "updated_at": None,
            "state": "idle", "error": None, "validation": None,
            "data": {"operation": None, "can_confirm": False, "modes": []} if entity == "ota" else {},
            "pending": None,
        })

    async def _persist(self):
        async with self.persist_lock:
            await self.storage.save(deepcopy(self.records))

    async def _changed(self, record):
        record["version"] += 1
        await self._persist()
        self.notify({key: record[key] for key in ("entity", "id", "version")})

    async def _admit(self, entity, node_id, action, body):
        if self.stopped:
            raise DeviceError("operation_busy")
        node = self.registry.get(node_id)
        bindings = getattr(self.maintenance, "bindings", None)
        mqtt_status = entity == "status" and bindings and hasattr(bindings, "mqtt_candidate") and bindings.mqtt_candidate(node_id)
        if (entity == 'control' and bindings and hasattr(bindings, 'mqtt_candidate')
            and bindings.mqtt_candidate(node_id) and not control_supported(action)):
            raise DeviceError('service_unsupported')
        equipment_target = None
        if entity == "equipment" and action != "resolve":
            if not self.equipment: raise DeviceError("service_unsupported")
            equipment_target = self.equipment.target(node)
        if entity != "equipment" and action != "resolve" and not mqtt_status and not self.maintenance.supports(node):
            raise DeviceError("service_unsupported")
        if self._record(entity, node_id)["pending"]:
            raise DeviceError("operation_unresolved")
        if node.lock.locked():
            raise DeviceError("operation_busy")
        async with node.lock:
            record = self._record(entity, node_id)
            if record["pending"]:
                raise DeviceError("operation_unresolved")
            if entity != "status" and any(records.get(node_id, {}).get("pending")
                    for name, records in self.records.items() if name not in (entity, "status")):
                raise DeviceError("operation_unresolved")
            if entity != "status" and self.profiles.busy(node_id):
                raise DeviceError("operation_unresolved")
            pending = {"action": action}
            if entity == "equipment":
                if self.registry.active(node_id): raise DeviceError("operation_unresolved")
                pending["target"] = equipment_target
                pending["request_id"] = secrets.token_hex(16)
                if action == "resolve":
                    require_interruption(record, body.get("expected_revision"))
                    if body.get("confirmed") is not True: raise DeviceError("invalid_request")
                    pending["interruption_id"] = body["expected_revision"]
                elif action != "refresh":
                    if action not in ACTIONS: raise DeviceError("invalid_request")
                    if type(body.get("expected_version")) is not int:
                        raise DeviceError("invalid_request")
                    if body.get("expected_version") != record["version"]:
                        raise DeviceError("revision_conflict")
                    if record.get("interruption"): raise DeviceError("operation_unresolved")
                    pending["request"] = prepare_action(record["data"].get("observation"), action, body)
            if entity=='mqtt':
                if not bindings or not bindings.mqtt_candidate(node_id) or action not in ('refresh','save','check'):
                    raise DeviceError('service_unsupported')
                if self.registry.active(node_id):raise DeviceError('operation_unresolved')
                if action=='save':
                    if record.get('interruption'):raise DeviceError('operation_unresolved')
                    pending.update(request_id=secrets.token_hex(16),expected_revision=body.get('expected_revision'))
                    resource_request({'resource':'mqtt','action':'save','request_id':pending['request_id'],
                        'expected_revision':pending['expected_revision'],'data':body.get('data')})
                elif action=='refresh' and record.get('interruption'):
                    previous=latest_interrupted_request(record)
                    if previous.get('action')=='save':
                        pending.update(action='check',interruption_id=public_interruption(record)['id'])
            interrupted=record.get('interruption')
            if interrupted and entity in ('control','ota') and action not in ('check','refresh','resolve','confirm'):
                raise DeviceError('operation_unresolved')
            if interrupted and entity=='ota' and action=='refresh':
                action='check';pending['action']='check'
                body={**body,'expected_revision':public_interruption(record)['id'],'confirmed':True}
            if action=='check':
                require_interruption(record,body.get('expected_revision'))
                if body.get('confirmed') is not True:raise DeviceError('invalid_request')
                pending['interruption_id']=body['expected_revision']
            if entity == "status":
                if action != "refresh":
                    raise DeviceError("invalid_request")
            elif entity == "diagnostics":
                if action not in ("refresh", "save") or (self.registry.active(node_id) and not interrupted):
                    raise DeviceError("operation_unresolved")
                if action == "save" and interrupted:
                    raise DeviceError("operation_unresolved")
                try:
                    await self.device_status.refresh(node)
                except OSError:
                    raise DeviceError("storage_failed") from None
                status = node.status or {}
                if action == "save" and status.get("service_mode") is True:
                    raise DeviceError("service_mode_active")
                capture = action == "save" or (status.get("service_mode") is False
                    and not status.get("recovery", {}).get("active") and status.get("restart_mode") != "ota")
                pending["stage"] = "save" if capture else "export"
                if interrupted and not capture:
                    previous = latest_interrupted_request(record)
                    if previous.get("snapshot_generation"):
                        pending["snapshot_generation"] = previous["snapshot_generation"]
            elif entity == "control":
                pending['request_id'] = secrets.token_hex(16)
                if action not in CONTROL_ACTIONS:
                    raise DeviceError("invalid_request")
                if action in ('service_enter', 'service_exit'):
                    if body.get('confirmed') is not True: raise DeviceError('invalid_request')
                    await self.device_status.refresh(node)
                    status = node.status or {}
                    if type(status.get('service_mode')) is not bool or status['service_mode'] == (action == 'service_enter'):
                        raise DeviceError('revision_conflict')
                    if status.get('recovery', {}).get('active') or status.get('restart_mode') == 'ota':
                        raise DeviceError('operation_busy')
                if self.discovery and self.discovery.blocks(node_id):
                    raise DeviceError("search_busy")
                op = self.registry.active(node_id)
                if action == 'check':
                    pass
                elif action == "resolve":
                    if body.get("confirmed") is not True:
                        raise DeviceError("invalid_request")
                    if op:
                        if body.get("expected_revision") != op["id"]:
                            raise DeviceError("invalid_request")
                        pending["operation_id"] = op["id"]
                    else:
                        require_interruption(record, body.get('expected_revision'))
                        previous = latest_interrupted_request(record)
                        if previous.get('job_id') or previous.get('operation_id'):
                            raise DeviceError('operation_unresolved')
                elif op:
                    raise DeviceError("operation_unresolved")
                if not self.maintenance.supports(node):
                    if action == "retry_transport":
                        raise DeviceError("unsupported_service")
                    if action == "wifi" and (not node.z2m or (node.identity or {}).get("transports", {}).get("zigbee") is False):
                        raise DeviceError("unsupported_service")
            elif entity == "ota":
                if action not in ("install", "refresh", "check", "confirm", "resolve"):
                    raise DeviceError("invalid_request")
                if action in ("install", "resolve") and body.get("confirmed") is not True:
                    raise DeviceError("invalid_request")
                if action == "install":
                    if self.registry.active(node_id):
                        raise DeviceError("operation_unresolved")
                    if body.get("mode") not in self._modes(node):
                        raise DeviceError("invalid_request")
                    # Library validation precedes durable device admission.
                    image = await self.run_io(self.library.get, body.get("firmware_id"))
                    await self.device_status.refresh(node)
                    require_variant((node.status or {}).get('variant_id'), image.get('variant'),
                        body.get('allow_variant_change', False))
                    pending.update(firmware_id=body["firmware_id"], mode=body["mode"],
                        allow_variant_change=body.get('allow_variant_change', False))
                elif action == "resolve":
                    op = self.registry.active(node_id)
                    if not op or body.get("expected_revision") != op["id"]:
                        raise DeviceError("invalid_request")
                    pending["operation_id"] = op["id"]
            previous_record = deepcopy(record)
            record.update(state="refreshing" if action == "refresh" else "saving", error=None, pending=pending)
            try:
                await self._changed(record)
            except Exception:
                record.clear()
                record.update(previous_record)
                raise DeviceError("storage_failed") from None
            try:
                if action=='check':
                    pass
                elif entity == "control":
                    await self._send_control(node, record, pending)
                elif entity == "diagnostics":
                    if interrupted:
                        previous=latest_interrupted_request(record)
                        if previous.get('job_id'):await self.maintenance.prepare_read(node,previous['job_id'])
                        else:
                            op=self.registry.active(node_id)
                            if op and op['id']==previous.get('operation_id'):
                                await self.registry.transition(op,'closed_unverified','read_retried')
                    if self.maintenance.supports(node):
                        result = await self.maintenance.enqueue(node,
                            "diagnostics_save" if pending["stage"] == "save" else "diagnostics")
                        pending["job_id"] = result["job_id"]
                elif entity == "ota" and action == "install":
                    if self.maintenance.supports(node):
                        result = await self.maintenance.enqueue(node, "ota", firmware_id=pending["firmware_id"], allow_variant_change=pending.get("allow_variant_change", False))
                        pending["job_id"] = result["job_id"]
                await self._persist()
            except Exception as error:
                if entity == "ota":
                    self._ota_data(node, record, self._operation(node_id))
                if (isinstance(error, DeviceError) and error.code == 'machine_profile_read_required'
                        and not pending.get('job_id') and not pending.get('operation_id')
                        and not self.registry.active(node_id)):
                    record.update(state='error', error=error.code, pending=None)
                else:
                    interrupt(record,timestamp())
                await self._changed(record)
                raise error
            if entity=='mqtt' and action=='save':self.settings_inputs[node_id]=deepcopy(body['data'])
            self._launch(entity, node_id)
        return {"id": node_id}

    def _launch(self, entity, node_id):
        key = (entity, node_id)
        task = self.create_task(self._run(entity, node_id))
        self.tasks[key] = task
        task.add_done_callback(lambda done: self.tasks.pop(key, None) if self.tasks.get(key) is done else None)

    async def _run(self, entity, node_id):
        record = self.records[entity][node_id]
        pending = record["pending"]
        try:
            node = self.registry.get(node_id)
            if pending['action']=='check':
                await self._check(entity,node,record,pending)
            elif entity == "status":
                await self._refresh_status(node)
            elif entity == "control":
                if pending.get("job_id"):
                    await self._wait_job(node, pending["job_id"])
                elif not pending.get("completed"):
                    raise DeviceError("outcome_uncertain")
                self._control_data(node, record, pending)
            elif entity == "diagnostics":
                await self._diagnostics(node, record, pending)
            elif entity == 'mqtt':
                await self._mqtt(node,record,pending)
            elif entity == 'equipment':
                await self._equipment(node, record, pending)
            else:
                await self._ota(node, record, pending)
            record.update(state="idle", error=None, pending=None,interruption=None)
            if entity == 'equipment' and pending.get('unconfirmed'):
                record.update(state="uncertain", error="equipment_unconfirmed", interruption=pending['unconfirmed'])
            await self._changed(record)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = error.code if isinstance(error, DeviceError) else "operation_failed"
            operation = self._operation(node_id, pending["operation_id"]) if pending.get("operation_id") else None
            if operation and operation["state"] not in TERMINAL:
                await self.registry.transition(operation, "uncertain" if entity in ("ota", "control") else "failed", code)
            if entity == "ota":
                self._ota_data(node, record, self._operation(node_id))
            if entity == "control":
                self._control_data(node, record, pending)
            if code in INTERRUPTION_ERRORS or code == 'equipment_unconfirmed' or pending['action']=='check' or record.get('interruption'):
                interrupt(record,timestamp(),code if pending['action']=='check' or entity=='status' else 'operation_interrupted')
            else:record.update(state="error", error=code, pending=None)
            await self._changed(record)

    async def _equipment(self, node, record, pending):
        if pending['action'] == 'resolve':
            previous = require_interruption(record, pending['interruption_id'])
            record['data']['closed_command'] = {"action": previous['action'], "request": previous.get('request'),
                "at": record['interruption']['at'], "closed_at": timestamp()}
            return
        await self._refresh_status(node)
        if (node.status or {}).get('service_mode') is True:
            raise DeviceError('service_mode_active')
        target = self.equipment.target(node)
        if target != pending['target']:
            same_binding = all(target.get(key) == pending['target'].get(key)
                for key in ('transport', 'binding_id', 'binding_revision'))
            if pending['action'] != 'refresh' or target.get('transport') != 'mqtt' or not same_binding:
                raise DeviceError('equipment_context_changed')
        result = await self.equipment.exchange({**target, 'boot_id': (node.status or {}).get('boot_id', '')}, pending.get('request'))
        record.update(data={**record['data'], **result}, updated_at=timestamp())
        if pending['action'] == 'refresh' and record.get('interruption') and record['interruption']['pending']['action'] != 'refresh':
            pending['unconfirmed'] = deepcopy(record['interruption'])
        status = result.get('result', {}).get('status')
        if status == 'uncertain': raise DeviceError('outcome_uncertain')
        if status == 'rejected': raise DeviceError('equipment_rejected')

    async def _mqtt(self,node,record,pending):
        bindings=self.maintenance.bindings
        data=self.settings_inputs.pop(node.node_id,None)
        save_accepted = False
        try:
            async with bindings.lock:
                async with asyncio.timeout(90):
                    candidate=bindings.mqtt_candidate(node.node_id)
                    if pending['action']=='save':
                        if data is None:raise DeviceError('outcome_uncertain')
                        reply=await bindings.resource_rpc(candidate,{'resource':'mqtt','action':'save',
                            'request_id':pending['request_id'],'expected_revision':pending['expected_revision'],'data':data})
                        if reply.get('error'):
                            record['validation']=reply.get('field_errors')
                            raise DeviceError(reply['error'])
                        save_accepted = True
                    snapshot=await bindings.resource_rpc(candidate,{'resource':'mqtt','action':'item'})
                    if snapshot.get('error') not in (None,'mqtt_settings_invalid'):raise DeviceError(snapshot['error'])
                    record.update(data={'settings':snapshot['data'],'revision':snapshot['revision']},
                        updated_at=timestamp(),validation=None)
                    if pending['action']=='check':
                        previous=require_interruption(record,pending['interruption_id'])
                        if snapshot.get('request_id')!=previous.get('request_id') or snapshot.get('error'):
                            raise DeviceError('result_unconfirmed')
        except (DeviceError,TimeoutError) as error:
            code=error.code if isinstance(error,DeviceError) else 'tunnel_timeout'
            definite = ('validation_failed','revision_conflict','operation_busy','invalid_request','forbidden','unsupported')
            if pending['action']=='save' and code not in definite and not (code == 'request_not_delivered' and not save_accepted):
                raise DeviceError('outcome_uncertain') from None
            raise
        finally:
            if data is not None:data.clear()

    async def _check(self,entity,node,record,pending):
        if entity=='mqtt':return await self._mqtt(node,record,pending)
        previous=require_interruption(record,pending['interruption_id'])
        await self._refresh_status(node)
        identifier=previous.get('job_id') or previous.get('operation_id')
        operation=next((op for op in self.registry.operations if op['id']==identifier),None)
        if not operation:raise DeviceError('result_unconfirmed')
        if entity=='ota':
            status=node.status or {};artifact=operation.get('artifact',{})
            if operation['action']=='ota_confirm':
                job=self.maintenance.jobs.get(node.node_id)
                if (not job or job['id']!=identifier or job['state']!='verified' or
                    status.get('wifi_ota',{}).get('verification_pending') is not False):
                    raise DeviceError('result_unconfirmed')
                await self.registry.transition(operation,'verified','result_checked')
            else:
                if (status.get('ota_marker_sha256')!=artifact.get('sha256') or
                    status.get('running_version')!=artifact.get('version') or
                    status.get('boot_id')==operation.get('before_boot_id') or not operation.get('before_boot_id')):
                    raise DeviceError('result_differs')
                if status.get('ota_marker_configured') is not True or status.get('wifi_ota',{}).get('running'):
                    raise DeviceError('result_unconfirmed')
                if operation['action']=='ota':
                    state='verifying' if status.get('wifi_ota',{}).get('verification_pending') else 'verified'
                    await self.registry.transition(operation,state,'result_checked')
                else:
                    decision=evaluate_ota_status(operation,node.status)
                    if decision is None:raise DeviceError('result_unconfirmed')
                    await self.registry.transition(operation,decision['state'],decision['message'])
            self._ota_data(node,record,operation)
        elif entity=='control':
            job=self.maintenance.jobs.get(node.node_id)
            if (not job or job['id']!=identifier or job['state']!='verified') and operation['state']!='verified':
                raise DeviceError('result_unconfirmed')
            self._control_data(node,record,previous)
        else:raise DeviceError('invalid_request')

    async def _send_control(self, node, record, pending):
        action = pending["action"]
        if action == "resolve":
            op = self.registry.active(node.node_id)
            if op:
                if self.maintenance.supports(node):
                    await self.maintenance.resolve(node, op["id"])
                await self.registry.transition(op, "closed_unverified", "closed_unverified")
        elif self.maintenance.supports(node):
            result = await self.maintenance.enqueue(node, "status" if action == "wifi" else action)
            pending["job_id"] = result["job_id"]
        else:
            raise DeviceError("service_unsupported")
        pending["completed"] = True
        self._control_data(node, record, pending)

    def _control_data(self, node, record, pending):
        identifier = pending.get("job_id") or pending.get("operation_id")
        op = next((op for op in reversed(self.registry.operations)
                   if op["node_id"] == node.node_id and op["id"] == identifier), None)
        record.update(data={"action": pending["action"], "operation": deepcopy(op)}, updated_at=timestamp())

    async def _refresh_status(self, node):
        async with node.lock:
            await self.device_status.refresh(node)
            await self.observe(node)

    async def _wait_job(self, node, identifier, record=None):
        while not self.stopped:
            result = await self.maintenance.result(node, identifier)
            await self.observe(node)
            if record is not None:
                before = deepcopy(record["data"])
                self._ota_data(node, record, self._operation(node.node_id, identifier))
                if before != record["data"]:
                    await self._changed(record)
            if result["state"] in TERMINAL:
                if result["state"] != "verified":
                    raise DeviceError("outcome_uncertain" if result["state"] != "failed" else "machine_failed")
                return result
            await asyncio.sleep(1)
        raise asyncio.CancelledError

    async def _collect(self, node, record, pending, *, only_version=None):
        if pending.get("job_id"):
            await self._wait_job(node, pending["job_id"])
            job = self.maintenance.jobs[node.node_id]
            raw = await self.files.read(job["id"], "output")
            if (await self.run_io(file_metadata, raw))["sha256"] != job["export_sha"]:
                raise DeviceError("machine_storage")
            status, trace = await self.run_io(diagnostic_parts, raw, node.node_id)
            expected_generation = pending.get("snapshot_generation")
            if expected_generation is not None:
                rows = (json.loads(line) for line in trace.splitlines() if line)
                sessions = [row for row in rows if row.get("type") == "session"]
                if len(sessions) != 1 or sessions[0].get("source") != "saved" or sessions[0].get("generation") != expected_generation:
                    raise DeviceError("diagnostics_snapshot_changed")
            equipment = self.snapshot("equipment", node.node_id)
            profile = self.profiles.snapshot(node.node_id)
            configuration = {"updated_at": profile["updated_at"], "state": profile["state"],
                "data": {key: value for key, value in (profile.get("data") or {}).items()
                         if key in ("revision", "files", "requiresReboot", "source")}}
            bundle, completeness = await self.run_io(package_machine_diagnostics, status, trace, node.node_id, equipment, configuration)
        else:
            raise DeviceError("machine_unavailable")
        identifier = secrets.token_hex(16)
        await self.files.write(identifier, "input", trace)
        await self.files.write(identifier, "partial", bundle)
        await self.files.publish(identifier)
        previous_data = deepcopy(record["data"])
        previous = previous_data.get("artifact")
        bundle_info = await self.run_io(file_metadata, bundle)
        trace_info = await self.run_io(file_metadata, trace)
        if only_version is not None and (self.stopped or record['pending'] or record['version']!=only_version):
            for suffix in ('input','output','partial'):await self.files.remove(identifier,suffix)
            return False
        record.update(data={**record["data"], "artifact": {"id": identifier, "captured_at": timestamp(), "completeness": completeness,
            "bundle": bundle_info, "trace": trace_info}}, updated_at=timestamp())
        try:
            await self._changed(record)
        except Exception:
            record["data"] = previous_data
            raise
        if previous:
            for suffix in ("input", "output"):
                await self.files.remove(previous["id"], suffix)

    async def _diagnostics(self, node, record, pending):
        if pending.get("stage") == "save":
            result = await self._wait_job(node, pending["job_id"])
            generation = saved_generation(result)
            pending["snapshot_generation"] = generation
            record["data"]["snapshot_generation"] = generation
            record["updated_at"] = timestamp()
            await self._changed(record)
            if pending["action"] == "save":return
            async with node.lock:
                await self.device_status.refresh(node)
                result = await self.maintenance.enqueue(node, "service_enter")
                pending.update(stage="enter", job_id=result["job_id"])
                await self._persist()
        if pending.get("stage") == "enter":
            await self._wait_job(node, pending["job_id"])
            async with node.lock:
                await self.device_status.refresh(node)
                if (node.status or {}).get("service_mode") is not True:
                    raise DeviceError("service_mode_required")
                result = await self.maintenance.enqueue(node, "diagnostics")
                pending.update(stage="export", job_id=result["job_id"])
                await self._persist()
        await self._collect(node, record, pending)

    def _operation(self, node_id, identifier=None):
        return next((op for op in reversed(self.registry.operations)
                     if op["node_id"] == node_id and (op["id"] == identifier if identifier else op["action"] in
                         ("ota", "ota_url", "ota_z2m", "ota_upload", "ota_confirm"))), None)

    async def _ota(self, node, record, pending):
        action = pending["action"]
        if action == "resolve":
            op = self.registry.active(node.node_id)
            if not op or op["id"] != pending["operation_id"]:
                raise DeviceError("operation_busy")
            if self.maintenance.supports(node):
                await self.maintenance.resolve(node, op["id"])
            await self.registry.transition(op, "closed_unverified", "closed_unverified")
        elif action == "confirm":
            async with node.lock:
                await self.device_status.refresh(node)
                op = self._operation(node.node_id)
                if not ota_can_confirm(op, node.status):
                    raise DeviceError("artifact_mismatch")
                if self.maintenance.supports(node):
                    result = await self.maintenance.enqueue(node, "ota_confirm")
                    pending.update(action="observe", job_id=result["job_id"])
                    await self._persist()
                else:
                    raise DeviceError("service_unsupported")
        if pending.get("job_id"):
            await self._wait_job(node, pending["job_id"], record)
        elif action == "refresh":
            await self._refresh_status(node)
            job = self.maintenance.jobs.get(node.node_id)
            if job:
                await self.maintenance.result(node, job["id"])
        self._ota_data(node, record, self._operation(node.node_id))

    def _ota_data(self, node, record, operation):
        record.update(data={"operation": deepcopy(operation), "can_confirm": ota_can_confirm(operation, node.status),
            "modes": self._modes(node)}, updated_at=timestamp())

    def _modes(self, node):
        if self.maintenance.supports(node):
            return ["url"]
        return []



def file_metadata(raw):
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def saved_generation(result):
    generation = result.get("snapshot_generation")
    if type(generation) is not int or not 1 <= generation <= 0xffffffff:
        raise DeviceError("invalid_response")
    return generation


def package_machine_diagnostics(status, trace, node_id, equipment=None, configuration=None):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("status.json", json.dumps(status))
        archive.writestr("uart.ndjson", trace)
        if equipment and equipment.get("data"):
            archive.writestr("equipment.json", json.dumps(equipment))
        if configuration:
            archive.writestr("configuration-files.json", json.dumps(configuration))
        archive.writestr("metadata.json", json.dumps({"node_id": node_id, "captured_at": timestamp(), "complete": bool(trace)}))
    return output.getvalue(), "complete" if trace else "partial"
