"""Bounded network provisioning. Passwords exist only in a running submission.

The public HTTP probe is a challenge/response, never a settings endpoint.
Its HMAC covers direction, both identities, job, keyed fingerprint and nonce.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import re
import secrets
import time
from homeassistant.helpers.storage import Store
from .bindings import hex_string, stamp
from .domain.errors import DeviceError
from .service_support import require_service_feature, service_support
from .domain.device_resource_policy import resource_request, wifi_fingerprint
from .domain.binding_policy import binding_key
from .domain.service_probe_policy import service_probe_reply
from .const import DOMAIN, MAX_HISTORY
from .domain.address_policy import validate_service_origin as service_origin


def credentials(body):
    ssid, password = body.get('ssid'), body.get('password')
    try:
        if isinstance(ssid,str): ssid.encode('utf-8')
        if isinstance(password,str): password.encode('utf-8')
    except UnicodeError: raise DeviceError('network_invalid') from None
    if (not isinstance(ssid, str) or not isinstance(password, str) or
        not 1 <= len(ssid.encode('utf-8')) <= 32 or '\0' in ssid or '\0' in password or
        (password and not 8 <= len(password.encode('utf-8')) <= 64) or
        (len(password.encode('utf-8')) == 64 and not re.fullmatch('[0-9A-Fa-f]{64}', password))):
        raise DeviceError('network_invalid')
    return ssid, password


def proof(token, service_id, binding_id, node_id, job_id, fingerprint, nonce, response=False):
    text = '\n'.join(('ESPOID-NET-1', 'response' if response else 'request',
        service_id, binding_id, node_id, job_id, fingerprint, nonce, ''))
    return hmac.new(bytes.fromhex(token), text.encode('ascii'), hashlib.sha256).hexdigest()


class NetworkJobs:
    def __init__(self, hass, entry, bindings):
        self.hass, self.bindings = hass, bindings
        self.store = Store(hass, 1, f'{DOMAIN}.network.{entry.entry_id}', private=True)
        self.jobs = {}
        self.tasks = set()
        self.lock = asyncio.Lock()
        self.stopped = False
        self.changed = lambda: None

    async def load(self):
        saved = await self.store.async_load()
        if saved is None: return
        if not isinstance(saved, dict) or len(saved) > MAX_HISTORY:
            raise DeviceError('network_storage')
        for key, job in saved.items():
            if (not hex_string(key, 32) or not isinstance(job, dict) or job.get('job_id') != key or
                not hex_string(job.get('fingerprint'), 64) or not isinstance(job.get('expires'), (int, float)) or
                not isinstance(job.get('key'), str) or not isinstance(job.get('request_id'), str) or
                job.get('state') not in ('queued','sending','checking','uncertain','ready','done','failed') or
                set(job) - {'job_id','key','request_id','fingerprint','state','error','result',
                    'created_at','checked_at','expires','probe_seen','device','resource_api','expected_revision'}):
                raise DeviceError('network_storage')
            if job['state'] in ('queued','sending','checking'): job['state'] = 'uncertain'
        self.jobs = saved

    async def save(self):
        try: await self.store.async_save(self.jobs)
        except Exception: raise DeviceError('network_storage') from None
        self.changed()

    def summaries(self):
        return [{k: j.get(k) for k in ('job_id','key','state','error','result','created_at','checked_at','probe_seen','device')}
            for j in self.jobs.values()]

    async def submit(self, target, body, request_id, url):
        if self.stopped: raise DeviceError('tunnel_failed')
        task=asyncio.current_task();self.tasks.add(task)
        try: return await self._submit(target,body,request_id,url)
        finally: self.tasks.discard(task)

    async def _submit(self, target, body, request_id, url):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9:_.-]{1,128}', request_id):
            raise DeviceError('invalid_request')
        candidate = self.bindings.candidate(target)
        require_service_feature(candidate, 'network')
        key = binding_key(candidate)
        ssid, password = credentials(body)
        url = service_origin(url)
        async with self.lock:
            # First binding/resumption uses the existing trusted-Z2M transaction.
            # An active binding is checked by the authenticated network RPC;
            # duplicate submissions therefore do not send even another bind.
            if self.bindings.records.get(key,{}).get('state') != 'active':
                if candidate.get('transport')=='mqtt':raise DeviceError('binding_missing')
                async with self.bindings.lock:
                    async with asyncio.timeout(90): await self.bindings.perform(key, candidate, 'bind')
            record = self.bindings.records[key]
            payload = {'ssid':ssid, 'password':password, 'url':url}
            fingerprint = hmac.new(bytes.fromhex(record['token']), b'ESPOID-NET-CONFIG-1\n' +
                json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
            resources = service_support(candidate).get('resources') is True
            expected_revision = ''
            if resources:
                previous = next((job for job in self.jobs.values() if job['request_id'] == request_id), None)
                if previous:
                    expected_revision = previous.get('expected_revision', '')
                else:
                    async with self.bindings.lock:
                        snapshot = await self.bindings.resource_rpc(candidate, {'resource': 'wifi', 'action': 'item'})
                    if 'data' not in snapshot: raise DeviceError(snapshot['error'])
                    if snapshot['state'] == 'saving': raise DeviceError('network_busy')
                    expected_revision = snapshot['revision']
                update = {'ssid': ssid, 'password_action': 'replace' if password else 'open'}
                if password: update['password'] = password
                resource = {'resource': 'wifi', 'action': 'save', 'request_id': '0'*32,
                            'expected_revision': expected_revision, 'data': update}
                resource_request(resource)
                fingerprint = wifi_fingerprint(resource, url, bytes.fromhex(record['token']))
            for job in self.jobs.values():
                if job['request_id'] == request_id:
                    if job['key'] != key or not hmac.compare_digest(job['fingerprint'], fingerprint):
                        raise DeviceError('network_conflict')
                    # Never replay a write, including after restart/lost reply.
                    return {'ok':True, 'job_id':job['job_id'], 'accepted':True}
                if job['key'] == key and job['state'] not in ('done','failed'):
                    raise DeviceError('network_busy')
            while len(self.jobs) >= MAX_HISTORY:
                evict = next((k for k,j in self.jobs.items() if j['state'] in ('done','failed')), None)
                if evict is None: raise DeviceError('network_busy')
                self.jobs.pop(evict)
            job_id = secrets.token_hex(16)
            job = {'job_id':job_id,'key':key,'request_id':request_id,'fingerprint':fingerprint,
                'state':'queued','created_at':stamp(),'expires':time.time()+900}
            if resources: job.update(resource_api=True, expected_revision=expected_revision)
            self.jobs[job_id] = job
            try: await self.save()
            except DeviceError:
                self.jobs.pop(job_id, None)
                raise
            task = self.hass.async_create_task(self.run(job, candidate, payload))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return {'ok':True, 'job_id':job_id, 'accepted':True}

    async def run(self, job, candidate, payload):
        try:
            job['state'] = 'sending'; await self.save()
            async with self.bindings.lock:
                async with asyncio.timeout(90):
                    if job.get('resource_api'):
                        data = {'ssid': payload['ssid'], 'password_action': 'replace' if payload['password'] else 'open'}
                        if payload['password']: data['password'] = payload['password']
                        try:
                            reply = await self.bindings.resource_rpc(candidate, {'resource': 'wifi', 'action': 'save',
                                'request_id': job['job_id'], 'expected_revision': job['expected_revision'], 'data': data}, payload['url'])
                        finally:
                            data.clear()
                        if reply['error']: raise DeviceError(reply['error'])
                    else:
                        await self.bindings.network_rpc(candidate, 'network_set',
                            job_id=job['job_id'], fingerprint=job['fingerprint'],
                            ssid=payload['ssid'].encode().hex(), password=payload['password'].encode().hex(), url=payload['url'])
                    # No password retained across the mode switch or in Store.
                    payload.clear()
                    if not job.get('resource_api'):
                        await self.bindings.network_rpc(candidate, 'network_start', job_id=job['job_id'])
            job['state'] = 'checking'; await self.save()
            # Read-only recovery. No credential/configuration replay. A reboot
            # or HA restart leaves the same durable job available for readback.
            await self.observe(job, candidate)
        except asyncio.CancelledError:
            job.update(state='uncertain', error='network_interrupted')
            raise
        except (DeviceError, TimeoutError) as err:
            code = err.code if isinstance(err, DeviceError) else 'tunnel_timeout'
            job.update(state='failed' if code == 'request_not_delivered' else 'uncertain', error=code)
            await self.save()
        finally:
            payload.clear()

    async def observe(self, job, target):
        try:
            await asyncio.sleep(75)
            await self.read(target)
        except (DeviceError,TimeoutError) as err:
            job.update(state='uncertain',error=err.code if isinstance(err,DeviceError) else 'tunnel_timeout')
            await self.save()

    async def read(self, target, start=False, expected_job_id=None):
        if self.stopped: raise DeviceError('tunnel_failed')
        task=asyncio.current_task();owned=task in self.tasks
        if not owned: self.tasks.add(task)
        try: return await self._read(target,start,expected_job_id)
        finally:
            if not owned: self.tasks.discard(task)

    async def _read(self, target, start=False, expected_job_id=None):
        candidate = self.bindings.candidate(target)
        require_service_feature(candidate, 'network')
        key = binding_key(candidate)
        async with self.bindings.lock:
            async with asyncio.timeout(90):
                if service_support(candidate).get('resources'):
                    snapshot = await self.bindings.resource_rpc(candidate, {'resource': 'wifi', 'action': 'item'})
                    if 'data' not in snapshot: raise DeviceError(snapshot['error'])
                    matching = self.jobs.get(snapshot['request_id'])
                    errors = {'wifi_failed': 2, 'service_unavailable': 3, 'service_rejected': 4,
                              'operation_interrupted': 5, 'storage_error': 6}
                    value = {'job_id': snapshot['request_id'] or '', 'fingerprint': matching['fingerprint'] if matching else '',
                             'state': 3 if snapshot['state'] == 'saving' else 4 if snapshot['request_id'] else 0,
                             'result': errors.get(snapshot['error'], 1 if snapshot['request_id'] else 0),
                             'ssid': snapshot['data']['ssid'].encode().hex(), 'password_set': snapshot['data']['password_set']}
                else:
                    snapshot = None
                    value = await self.bindings.network_rpc(candidate, 'network_read')
                if expected_job_id is not None and value.get('job_id') != expected_job_id:
                    raise DeviceError('network_conflict')
                job = self.jobs.get(value.get('job_id'))
                if job and job['key'] == key:
                    if value.get('fingerprint') != job['fingerprint']: raise DeviceError('network_conflict')
                    if start and value.get('state') in (1,2):
                        job['expires']=time.time()+900
                        await self.save()
                        await self.bindings.network_rpc(candidate,'network_start',job_id=job['job_id'])
                        task=self.hass.async_create_task(self.observe(job,target))
                        self.tasks.add(task);task.add_done_callback(self.tasks.discard)
                    job.update(checked_at=stamp(), device={k:value.get(k) for k in ('state','result','ssid','password_set')})
                    if snapshot: job['device']['snapshot'] = snapshot
                    if value.get('state') == 4:
                        job.update(state='done' if value.get('result') == 1 else 'failed', result=value.get('result'), error=None)
                    elif start: job.update(state='checking',error=None)
                    else: job['state'] = 'ready' if value.get('state') == 1 else 'checking'
                    await self.save()
                # An older terminal/empty device job proves that an uncertain
                # newer submission never arrived. Do not leave admission stuck.
                if value.get('state') in (0,4):
                    for pending in self.jobs.values():
                        if pending['key']==key and pending['job_id']!=value.get('job_id') and pending['state']=='uncertain':
                            pending.update(state='failed',error='network_interrupted')
                    await self.save()
                return {'ok':True,'network':value}

    async def probe(self, body):
        if isinstance(body, dict) and body.get('purpose') == 'service':
            if self.stopped: raise DeviceError('network_auth')
            return service_probe_reply(body, self.bindings.service_id, self.bindings.records)
        fields = {'v','service_id','binding_id','node_id','job_id','fingerprint','nonce','proof'}
        if (not isinstance(body,dict) or set(body) != fields or type(body['v']) is not int or body['v'] != 1 or
            not all(hex_string(body.get(k), n) for k,n in
                (('service_id',32),('binding_id',32),('job_id',32),('fingerprint',64),('nonce',64),('proof',64))) or
            not isinstance(body.get('node_id'),str)):
            raise DeviceError('network_auth')
        job = self.jobs.get(body['job_id'])
        record = self.bindings.records.get(job['key']) if job else None
        if (not record or job['expires'] < time.time() or job['state'] in ('done','failed') or
            body['service_id'] != self.bindings.service_id or body['binding_id'] != record['binding_id'] or
            body['node_id'] != record['node_id'] or body['fingerprint'] != job['fingerprint']):
            raise DeviceError('network_auth')
        args = (record['token'],self.bindings.service_id,record['binding_id'],record['node_id'],
            job['job_id'],job['fingerprint'],body['nonce'])
        if not hmac.compare_digest(proof(*args), body['proof']): raise DeviceError('network_auth')
        if not job.get('probe_seen'):
            job['probe_seen'] = stamp(); await self.save()
        return {'ok':True,'proof':proof(*args,response=True)}

    async def stop(self):
        self.stopped = True
        tasks = list(self.tasks)
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
