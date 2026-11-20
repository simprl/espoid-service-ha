"""Outgoing-device maintenance jobs. Private durable metadata, bounded proofs/streams."""
from __future__ import annotations
import asyncio
import hashlib
import logging
import math
import time
from typing import Any, Protocol
from aiohttp import web
from .domain.errors import DeviceError
from .domain.maintenance_policy import maintenance_result_message, maintenance_result_state
from .domain.configuration_files_policy import profile_transfer, FILE_TRANSFER_BYTES
from .domain.mqtt_service_policy import OPERATIONS
from .domain.firmware_variant_policy import require_variant
from .domain.device_resource_policy import validate_resource_data
from .application.device_resource_channel import DeviceResourceChannel
from .const import MAX_NODES
from .machine_wire import encoded, decoded, descriptor, hex_value, validate_status

TERMINAL = ('verified','failed','uncertain','closed_unverified')
_LOGGER = logging.getLogger(__name__)

class Maintenance:
    def __init__(self, hass, storage: MaintenanceStorage, registry, bindings, library, files):
        self.hass, self.registry, self.bindings, self.library = hass, registry, bindings, library
        self.storage = storage
        self.files = files
        self.jobs, self.sequences, self.challenges, self.attempts = {}, {}, {}, {}
        self.lock = asyncio.Lock()
        self.node_locks = {}
        self.persist_lock = asyncio.Lock()
        self.tasks = set()
        self.last_seen = {}
        self.boots = {}
        self.resource_channel = DeviceResourceChannel()
        self.status_seen = {}
        self.deadlines = {}
        self.readbacks = {}
        self.next_readback = {}
        self.stopped = False
        self.observed = None

    async def load(self):
        saved = await self.storage.load()
        if saved is not None:
            if not isinstance(saved,dict) or set(saved)!={'jobs','sequences'} or not isinstance(saved['jobs'],dict) or not isinstance(saved['sequences'],dict) or len(saved['jobs'])>MAX_NODES:
                raise DeviceError('machine_storage')
            for node,job in saved['jobs'].items():
                if (not isinstance(job,dict) or not hex_value(job.get('id'),32) or job.get('node_id')!=node
                    or not hex_value(job.get('fingerprint'),64) or not isinstance(job.get('descriptor'),str)
                    or hashlib.sha256(job['descriptor'].encode('ascii')).hexdigest()!=job['fingerprint']):
                    raise DeviceError('machine_storage')
                try:
                    d=decoded(job['descriptor'])
                    canonical=descriptor(d['id'],d['seq'],d['op'],d['size'],d['sha'],d['version'],d['expected'])
                    if (canonical.decode('ascii')!=job['descriptor'] or d['id']!=job['id']
                        or not hex_value(job.get('binding_id'),32) or job.get('state') not in (*TERMINAL,'waiting','running')
                        or saved['sequences'].get(node,0)<d['seq']
                        or any(type(job.get(k)) not in (int,float) or not math.isfinite(job[k]) for k in ('created','deadline'))
                        or not 0<job['deadline']-job['created']<=901
                        or type(job.get('export_size')) is not int or not 0<=job['export_size']<=2*1024*1024
                        or (job.get('export_sha')!='' and not hex_value(job.get('export_sha'),64))
                        or ('file_boot' in job and not hex_value(job['file_boot'],16))):raise ValueError()
                except (KeyError,TypeError,ValueError,DeviceError):raise DeviceError('machine_storage') from None
            if any(type(n)is not int or not 0<=n<=0xffffffff for n in saved['sequences'].values()): raise DeviceError('machine_storage')
            self.jobs, self.sequences = saved['jobs'], saved['sequences']
            for node,job in self.jobs.items():
                if job['state'] not in TERMINAL:
                    job['interrupted']=True
                remaining=0 if time.time()<job['created']-5 else max(0,min(900,job['deadline']-time.time()))
                self.deadlines[node]=time.monotonic()+remaining
        # New challenges after reload; durable running work requires result/readback,
        # never silently reissue an admitted effect on integration startup.

    async def save(self):
        from copy import deepcopy
        try:
            async with self.persist_lock:
                await self.storage.save(deepcopy({'jobs':self.jobs,'sequences':self.sequences}))
        except Exception: raise DeviceError('machine_storage') from None

    def supports(self, node):
        if hasattr(self.bindings, "mqtt_candidate") and self.bindings.mqtt_candidate(node.node_id):
            return self.bindings.mqtt_candidate(node.node_id)['state']=='active'
        # Once selected, missing discovery/converter data cannot reopen legacy HTTP.
        if self.registry.locators.get(node.node_id,{}).get('machine') or node.node_id in self.jobs:
            return True
        try: candidate = self.bindings.sources.candidate(node.z2m)
        except DeviceError: return False
        from .service_support import service_support
        supported=service_support(candidate).get('machine') is True
        if supported:self.registry.locators.setdefault(node.node_id,{})['machine']=True
        return supported

    def node_lock(self, node_id):
        self.registry.get(node_id)
        for removed in list(self.node_locks):
            if removed not in self.registry.nodes and not self.node_locks[removed].locked():
                self.node_locks.pop(removed)
                for cache in (self.challenges,self.attempts,self.last_seen,self.boots):cache.pop(removed,None)
        return self.node_locks.setdefault(node_id,asyncio.Lock())

    def expired(self,job):
        return (time.time()>job['deadline'] or time.time()<job['created']-5
                or time.monotonic()>self.deadlines.get(job['node_id'],0))

    def binding(self, node_id):
        matches=[r for r in self.bindings.records.values() if r['node_id']==node_id and r['state']=='active']
        if len(matches)!=1: raise DeviceError('binding_missing')
        return matches[0]

    async def enqueue(self, node, operation, data=None, firmware_id=None, expected_revision=None, allow_variant_change=False):
        if not self.supports(node):raise DeviceError('service_unsupported')
        record=self.binding(node.node_id)
        if (operation in ('profile_read','profile_validate','profile_store','profile_default','profile_file','diagnostics')
                and (node.status or {}).get('service_mode') is False
                and not (node.status or {}).get('recovery',{}).get('active')
                and (node.status or {}).get('restart_mode') != 'ota'):
            raise DeviceError('service_mode_required')
        if record.get('transport')=='mqtt' and operation not in OPERATIONS:
            raise DeviceError('service_unsupported')
        if record.get('transport')=='mqtt':
            from .domain.address_policy import validate_service_origin
            validate_service_origin(self.registry.settings.get('service_base_url',''))
        if self.stopped: raise DeviceError('machine_unavailable')
        async with self.lock:
            previous=self.jobs.get(node.node_id)
            if previous and previous['state'] not in TERMINAL: raise DeviceError('operation_unresolved')
            if self.registry.active(node.node_id): raise DeviceError('operation_unresolved')
            manifest=None; size=0; digest=version=expected=''
            if len(self.jobs)>=MAX_NODES and node.node_id not in self.jobs:raise DeviceError('node_limit')
            if operation in ('profile_store','profile_validate'):
                data=profile_transfer(data);size=len(data);digest=hashlib.sha256(data).hexdigest()
                if operation=='profile_store': expected=expected_revision or ''
            if operation=='profile_file':
                if not isinstance(data, bytes) or not 0 < len(data) <= FILE_TRANSFER_BYTES: raise DeviceError('machine_invalid')
                size=len(data);digest=hashlib.sha256(data).hexdigest();expected=expected_revision or ''
            if operation=='profile_default':expected=expected_revision or ''
            if operation=='ota':
                manifest=await self.hass.async_add_executor_job(self.library.get,firmware_id)
                require_variant((node.status or {}).get('variant_id'), manifest.get('variant'), allow_variant_change)
                size=manifest['artifact']['size'];digest=manifest['artifact']['sha256'];version=manifest['version']
            if operation in ('service_enter','diagnostics_save'): expected = (node.status or {}).get('boot_id', '')
            if operation == 'service_exit': expected = (node.status or {}).get('configuration_revision', '')
            if operation=='ota_confirm':
                status=node.status or {}; digest=status.get('ota_marker_sha256','');version=status.get('running_version','');expected=status.get('boot_id','')
                if not status.get('wifi_ota',{}).get('verification_pending'): raise DeviceError('artifact_mismatch')
            sequence=self.sequences.get(node.node_id,0)+1
            # Validate all admission before creating a public operation.
            raw=descriptor('1'*32,sequence,operation,size,digest,version,expected)
            op=await self.registry.begin(node.node_id,operation,manifest)
            if operation=='ota':
                before=node.status or {}
                op.update(before_boot_id=before.get('boot_id'),before_marker_sha256=before.get('ota_marker_sha256'),
                          before_marker_partition=before.get('ota_marker_partition'))
            raw=descriptor(op['id'],sequence,operation,size,digest,version,expected)
            job={'id':op['id'],'node_id':node.node_id,'binding_id':record['binding_id'],
                 'descriptor':raw.decode('ascii'),'fingerprint':hashlib.sha256(raw).hexdigest(),
                 'state':'waiting','created':time.time(),'deadline':time.time()+900,'export_sha':'','export_size':0}
            if operation=='ota': job['firmware_id']=firmware_id
            try:
                if data is not None:
                    await self.files.write(job['id'],'input',data)
                self.sequences[node.node_id]=sequence;self.jobs[node.node_id]=job
                self.deadlines[node.node_id]=time.monotonic()+900
                await self.save();await self.registry.transition(op,'waiting','machine_waiting')
                if previous:
                    for suffix in ('input','output','partial'):
                        await self.files.remove(previous['id'],suffix)
            except Exception:
                await self.registry.transition(op,'uncertain','machine_storage');raise
        # Wake is explicit operator work, not startup polling or a broad MQTT command.
        # Failure leaves the job waiting for the next already-authorized Wi-Fi window.
        task=self.hass.async_create_task(self.wake(node,job));self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        return {'ok':True,'accepted':True,'job_id':job['id'],'operation':op}

    async def wake(self,node,job):
        # A recent authenticated device poll already provides delivery. Opening
        # Zigbee while its radio is off only holds the shared tunnel lock.
        if self.stopped or self.jobs.get(node.node_id) is not job or job['state']!='waiting' or job.get('interrupted'):return
        if self.wifi_observed(node):
            # The last poll can precede the end of the Wi-Fi window. If no
            # device poll accepts this job, wake it after that observation ages.
            await asyncio.sleep(16)
            if (self.stopped or self.jobs.get(node.node_id) is not job or
                job['state']!='waiting' or self.wifi_observed(node)):return
        try:
            async with self.bindings.lock:
                async with asyncio.timeout(90):
                    if job.get('interrupted'):return
                    await self.bindings.machine_rpc(self.bindings.candidate_for_node(node),'maintenance_submit',job=job['descriptor'].encode('ascii').hex())
        except DeviceError as error:
            _LOGGER.warning("Maintenance wake failed for %s (%s): %s", node.node_id,
                            decoded(job['descriptor'])['op'], error.code)
            if (error.code in ('service_mode_required', 'machine_conflict', 'machine_unavailable')
                    and self.jobs.get(node.node_id) is job and job['state']=='waiting'):
                job.update(state='failed',result=7)
                await self.save()
                operation=next((item for item in self.registry.operations if item['id']==job['id']),None)
                if operation: await self.registry.transition(operation,'failed',error.code)
        except TimeoutError:
            _LOGGER.warning("Maintenance wake timed out for %s (%s)", node.node_id,
                            decoded(job['descriptor'])['op'])

    async def request_resource(self, node, binding_id, request, origin):
        observed = self.last_seen.get(node.node_id)
        boot = self.boots.get(node.node_id) or (node.status or {}).get('boot_id')
        try:
            return await self.resource_channel.request(node.node_id, binding_id, request, origin, boot_id=boot)
        except DeviceError as error:
            if error.code == 'request_not_delivered' and self.last_seen.get(node.node_id) == observed:
                self.last_seen.pop(node.node_id, None)
            raise

    async def poll(self, node_id, binding_id, status, report):
        """Apply an authenticated decoded report under the caller's node lock."""
        self.observe_boot(node_id, status['boot_id'])
        node=self.registry.get(node_id);node.status=status;node.reachable=True
        from .registry import timestamp
        node.checked_at=timestamp()
        self.last_seen[node.node_id]=time.monotonic()
        self.status_seen[node.node_id]=time.monotonic()
        job=self.jobs.get(node_id);ack='';cancel=''
        if job and job['binding_id']!=binding_id:
            if job['state'] not in TERMINAL: raise DeviceError('machine_auth')
            # A confirmed rebind does not grant the new credential authority over
            # the previous binding's terminal job/history or replay its descriptor.
            job=None
        if job and report['job_id']==job['id']:
            desc=decoded(job['descriptor'])
            if (type(report['seq'])is not int or report['seq']!=desc['seq'] or type(report['phase_id'])is not int
                or report['phase_id'] not in (1,2,3,4) or type(report['result'])is not int or not 0<=report['result']<=8
                or type(report['flags'])is not int or not 0<=report['flags']<=(0xffffffff if desc['op']=='diagnostics_save' else 3)):
                raise DeviceError('machine_invalid')
            job['observed_id']=report['job_id'];job['observed_phase']=report['phase_id']
            if report['phase_id'] in (3,4):
                state=maintenance_result_state(report['phase_id'],report['result'])
                if desc['op'] in ('profile_read','profile_file','diagnostics') and state=='verified' and not job['export_sha']: state='uncertain'
                if (job['state'],job.get('result'),job.get('flags'))!=(state,report['result'],report['flags']):
                    job.update(state=state,result=report['result'],flags=report['flags'])
                    await self.save()
                ack=job['id']
                op=next((o for o in self.registry.operations if o['id']==job['id']),None)
                if op and op['state'] not in ('verified','failed','closed_unverified'): await self.registry.transition(op,state,maintenance_result_message(state,report['result']))
            elif job['state'] not in TERMINAL:
                if report['phase_id']==1 and (self.expired(job) or job.get('interrupted')):
                    await self.expire(job)
                else:
                    if job['state']!='running':
                        job['state']='running';await self.save()
                        op=next((o for o in self.registry.operations if o['id']==job['id']),None)
                        if job['state']=='running' and op and op['state'] not in TERMINAL:
                            await self.registry.transition(op,'waiting','machine_running')
                    ack=job['id']
            if report['phase_id']==1 and job['state'] in TERMINAL:
                cancel=job['id'];ack=''
        available=None
        if job and job['state']=='waiting' and not job.get('interrupted'):
            if self.expired(job):
                await self.expire(job)
            else: available=job['descriptor']
        # An admitted/running job is never redelivered automatically after a
        # backend restart. ESP reports its journal to reconcile the outcome.
        if self.observed:
            await self.observed(node)
        return {'job':available or '', 'ack':ack, 'cancel':cancel}

    def transfer_job(self, node_id, binding_id, identifier):
        """Select the active authorized job under the caller's node lock."""
        job=self.jobs.get(node_id)
        if (not job or job['id']!=identifier or job['binding_id']!=binding_id or
            job['state'] in TERMINAL or self.expired(job)): raise DeviceError('machine_auth')
        return job

    async def download_source(self, job):
        desc=decoded(job['descriptor'])
        if desc['op'] not in ('ota','profile_validate','profile_store','profile_file'): raise DeviceError('machine_invalid')
        if desc['op']=='ota':
            manifest=await self.hass.async_add_executor_job(self.library.get,job['firmware_id'])
            path=self.library.root/job['firmware_id']/'firmware.bin'
            if manifest['artifact']['sha256']!=desc['sha']: raise DeviceError('machine_storage')
        else: path=self.files.path(job['id'],'input')
        return path,desc['size'],desc['sha']

    def upload_limit(self, job):
        operation=decoded(job['descriptor'])['op']
        if operation not in ('profile_read','profile_file','diagnostics'): raise DeviceError('machine_invalid')
        return 8192 if operation=='profile_read' else 1024 if operation=='profile_file' else 2*1024*1024

    async def complete_upload(self, job, size, digest, *, boot=None):
        """Publish a verified body and save evidence under the caller's node lock."""
        if decoded(job['descriptor'])['op']=='profile_file':
            if not hex_value(boot,16):raise DeviceError('machine_invalid')
            job['file_boot']=boot
        await self.files.publish(job['id'])
        if decoded(job['descriptor'])['op']=='profile_read':
            profile=decoded(await self.files.read(job['id'],'output'))
            try:
                validate_resource_data('profile', profile)
            except DeviceError:
                raise DeviceError('machine_invalid') from None
        from .registry import timestamp
        job.update(export_size=size,export_sha=digest,export_at=timestamp());await self.save()

    async def result(self,node,identifier):
        job=self.jobs.get(node.node_id)
        if not job or job['id']!=identifier: raise DeviceError('machine_invalid')
        if job['state'] not in TERMINAL and self.expired(job):await self.expire(job)
        result=job.get('result')
        if job['state'] in ('verified','failed') and type(result)is int and 0<=result<=8:
            op=next((item for item in self.registry.operations if item['id']==identifier),None)
            if op and op['state'] not in ('verified','failed','closed_unverified'):
                await self.registry.transition(op,job['state'],maintenance_result_message(job['state'],result))
        operation=decoded(job['descriptor'])['op']
        if (not self.stopped and (job['state']=='running' and operation in ('retry_transport','reboot_zigbee','recovery_retry','reboot_wifi','ota')
            or job['state'] in ('waiting','running') and operation in ('service_enter','service_exit','diagnostics_save'))
            and not self.wifi_observed(node) and node.node_id not in self.readbacks
            and time.monotonic()>=self.next_readback.get(node.node_id,0)):
            # Once outgoing HTTP polls stop, observe the durable result over
            # the signed carrier. This task never submits or repeats an effect.
            self.next_readback[node.node_id]=time.monotonic()+10
            async def readback():
                try:await self.refresh(node)
                except (DeviceError,TimeoutError):pass
            task=self.hass.async_create_task(readback())
            self.readbacks[node.node_id]=task;self.tasks.add(task)
            def finished(done):
                self.tasks.discard(done)
                if self.readbacks.get(node.node_id) is done:self.readbacks.pop(node.node_id,None)
            task.add_done_callback(finished)
        output={'ok':True,'job_id':identifier,'state':job['state'],'result':job.get('result'),'flags':job.get('flags',0)}
        if operation == 'diagnostics_save' and job['state']=='verified':
            generation = job.get('flags')
            if type(generation) is not int or not 1 <= generation <= 0xffffffff:
                raise DeviceError('machine_invalid')
            output['snapshot_generation'] = generation
        if operation in ('profile_read','profile_file') and job['state']=='verified':
            raw=await self.files.read(identifier,'output')
            if hashlib.sha256(raw).hexdigest()!=job['export_sha']: raise DeviceError('machine_storage')
            output['profile' if operation=='profile_read' else 'file_receipt']=decoded(raw)
            if operation=='profile_file':output['file_boot']=job['file_boot']
        return output

    async def expire(self,job):
        job['state']='failed' if job['state']=='waiting' else 'uncertain'
        await self.save()
        op=next((o for o in self.registry.operations if o['id']==job['id']),None)
        if op:await self.registry.transition(op,job['state'],'machine_expired')

    async def refresh(self,node):
        job=self.jobs.get(node.node_id)
        if node.status and self.wifi_observed(node):
            return node.status
        async with self.bindings.lock:
            async with asyncio.timeout(90):
                reply=await self.bindings.machine_rpc(self.bindings.candidate_for_node(node),'maintenance_read')
        status=reply.get('status')
        validate_status(status,node.node_id)
        self.observe_boot(node.node_id, status['boot_id'])
        from .registry import timestamp
        node.status=status;node.checked_at=timestamp();node.reachable=True
        self.status_seen[node.node_id]=time.monotonic()
        job=self.jobs.get(node.node_id)
        if job and reply.get('job_id')==job['id'] and reply.get('phase_id') in (3,4):
            result=reply.get('result')
            if type(result)is not int or not 0<=result<=8:raise DeviceError('machine_invalid')
            state=maintenance_result_state(reply['phase_id'],result)
            if decoded(job['descriptor'])['op'] in ('profile_read','profile_file','diagnostics') and not job['export_sha']:state='uncertain'
            job.update(state=state,result=result,flags=reply.get('flags',0));await self.save()
            op=next((o for o in self.registry.operations if o['id']==job['id']),None)
            if op and op['state'] not in ('verified','failed','closed_unverified'):await self.registry.transition(op,state,maintenance_result_message(state,result))
        if job:
            job['observed_id']=reply.get('job_id');job['observed_phase']=reply.get('phase_id')
        return status

    async def prepare_read(self,node,identifier):
        """Explicit operator read: reconcile/cancel the old journal before a new read.

        The Wi-Fi switch is authorized by the check/retry action. It never submits
        the old descriptor and never repeats its write.
        """
        job=self.jobs.get(node.node_id)
        if not job or job['id']!=identifier:raise DeviceError('operation_changed')
        await self.refresh(node)
        if job.get('observed_id')==identifier and job.get('observed_phase') in (1,2):
            job['interrupted']=True
            await self.save()
            if not self.wifi_observed(node):
                candidate=self.bindings.candidate_for_node(node)
                if candidate.get('transport')=='mqtt':
                    async with self.bindings.lock:
                        async with asyncio.timeout(90):
                            await self.bindings.machine_rpc(candidate,'maintenance_submit',job=job['descriptor'].encode('ascii').hex())
                else:await self.bindings.sources.command(node.z2m,'switch_to_wifi')
            end=time.monotonic()+90
            while (job.get('observed_id')==identifier and job.get('observed_phase') in (1,2)
                   and time.monotonic()<end):
                await asyncio.sleep(1)
            if job.get('observed_phase') in (1,2):raise DeviceError('operation_still_running')
        await self.resolve(node,identifier)
        op=self.registry.active(node.node_id)
        if op and op['id']==identifier:
            await self.registry.transition(op,'closed_unverified','result_check')

    def status_age(self,node):
        return max(0,int((time.monotonic()-self.status_seen.get(node.node_id,time.monotonic()))*1000))

    def wifi_observed(self,node):
        return time.monotonic()-self.last_seen.get(node.node_id,0)<15

    def observe_boot(self, node_id, boot_id):
        """Fresh authenticated evidence ends old exchanges, not durable jobs."""
        node = self.registry.get(node_id)
        previous = self.boots.get(node_id) or (node.status or {}).get('boot_id')
        self.boots[node_id] = boot_id
        if previous and previous != boot_id:
            self.last_seen.pop(node_id, None)
            self.challenges.pop(node_id, None)
            self.bindings.invalidate_boot(node_id, boot_id)
        self.resource_channel.observe_boot(node_id, boot_id)

    def progress(self,job,count,total):
        op=next((o for o in self.registry.operations if o['id']==job['id']),None)
        if op:
            op.update(state='sending',message='machine_transferring')
            op['total_bytes']=total
            op['sent_bytes']=min(total,op.get('sent_bytes',0)+count)

    async def resolve(self,node,identifier):
        async with self.node_lock(node.node_id):
            job=self.jobs.get(node.node_id)
            if job and job['id']==identifier:
                job['state']='closed_unverified'
                await self.save()

    async def stop(self):
        self.stopped=True;self.challenges.clear();self.last_seen.clear();self.boots.clear()
        await self.resource_channel.stop()
        tasks=list(self.tasks)
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)

    async def download(self,node,identifier,request):
        job=self.jobs.get(node.node_id)
        if not job or job['id']!=identifier or job['state']!='verified' or not job['export_sha']:raise DeviceError('machine_unavailable')
        size,sha=await self.files.identity(self.files.path(identifier,'output'))
        if (size,sha)!=(job['export_size'],job['export_sha']):raise DeviceError('machine_storage')
        # The first record is a stable full status snapshot, not a UART record.
        # Reuse the diagnostic bundle allowlist before exposing/sharing status.
        raw=await self.files.read(identifier,'output')
        status,trace=await self.hass.async_add_executor_job(diagnostic_parts,raw,node.node_id)
        completeness='complete' if trace else 'partial'
        if request.query.get('bundle')=='1':
            from io import BytesIO
            from zipfile import ZipFile,ZIP_DEFLATED
            def package():
                output=BytesIO()
                with ZipFile(output,'w',compression=ZIP_DEFLATED) as archive:
                    archive.writestr('diagnostics.ndjson',trace)
                    archive.writestr('status.json',encoded(status))
                    archive.writestr('metadata.json',encoded({'schema_version':1,'node_id':node.node_id,'job_id':identifier,
                        'captured_at':job.get('export_at'),'transfer_sha256':sha,'trace_sha256':hashlib.sha256(trace).hexdigest(),'complete':bool(trace)}))
                return output.getvalue()
            data=await self.hass.async_add_executor_job(package)
            return web.Response(body=data,content_type='application/zip',headers={'Content-Disposition':'attachment; filename=espoid-diagnostics.zip','Cache-Control':'no-store','X-ESPOID-Completeness':completeness})
        return web.Response(body=trace,headers={'Content-Disposition':'attachment; filename=espoid-diagnostics.ndjson','Content-Type':'application/x-ndjson','Cache-Control':'no-store','X-ESPOID-Completeness':completeness})

def diagnostic_parts(raw,node_id):
    from .diagnostic_bundle import project,STATUS
    first,separator,trace=raw.partition(b'\n')
    if not separator or len(first)>65536:raise DeviceError('machine_invalid')
    header=decoded(first)
    if (not isinstance(header,dict) or set(header)!={'type','value'} or header['type']!='status'
        or not isinstance(header['value'],dict) or header['value'].get('node_id')!=node_id):raise DeviceError('machine_invalid')
    status,_=project(header['value'],STATUS)
    return status,trace


class MaintenanceStorage(Protocol):
    """Read raw records and persist the owner's captured jobs/sequences snapshot."""

    async def load(self) -> object: ...

    async def save(self, records: dict[str, Any]) -> None: ...
