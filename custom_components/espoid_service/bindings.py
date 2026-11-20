"""Private binding transactions. UI/history never receive credentials or certs."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime,timezone
from contextlib import asynccontextmanager
from homeassistant.helpers.storage import Store
from .domain.errors import DeviceError
from .const import DOMAIN,MAX_NODES
from .infrastructure.z2m_service_channel import Z2MChannel
from .infrastructure.mqtt_service_channel import MqttChannel
from .domain.mqtt_enrollment_policy import mqtt_target, enrollment_certificate
from .domain.binding_policy import binding_key
from .domain.mqtt_service_policy import resource_supported, OPERATIONS
from .infrastructure.service_tls import TLSStream,tls_context
from .infrastructure.service_control import control_rpc
from .service_support import require_service_feature, service_control_supported
_LOGGER=logging.getLogger(__name__)

class Bindings:
    def __init__(self,hass,entry,sources):
        self.hass,self.sources=hass,sources
        self.store=Store(hass,1,f'{DOMAIN}.bindings.{entry.entry_id}',private=True)
        self.service_id=None
        self.records={}
        self.lock=asyncio.Lock()
        self.tasks=set()
        self.channels={}
        self.stopped=False
        self.changed=lambda:None
        self.transition_busy=lambda node_id:False

    async def load(self):
        saved=await self.store.async_load()
        if saved is None:
            self.service_id=secrets.token_hex(16)
            await self.save()
            return
        if (not isinstance(saved,dict) or not hex_string(saved.get('service_id'),32) or
            not isinstance(saved.get('bindings'),dict) or len(saved['bindings'])>MAX_NODES):
            raise DeviceError('binding_storage')
        nodes = set()
        for key,record in saved['bindings'].items():
            if not valid_binding(key, record):
                raise DeviceError('binding_storage')
            if record['node_id'] in nodes:
                raise DeviceError('binding_storage')
            nodes.add(record['node_id'])
            if not valid_replacement(key, record):
                raise DeviceError('binding_storage')
        self.service_id=saved['service_id'];self.records=saved['bindings']

    async def save(self):
        try: await self.store.async_save({'service_id':self.service_id,'bindings':self.records})
        except Exception: raise DeviceError('binding_storage') from None
        self.changed()

    def summaries(self):
        return [{k:r.get(k) for k in ('prefix','ieee','node_id','state','checked_at','status','error','transport','topic')}|
            {'prefix':r.get('prefix',''),'ieee':r.get('ieee',''),'certificate_sha256':hashlib.sha256(bytes.fromhex(r['certificate'])).hexdigest(),
             'rebind_state':r.get('replacement',{}).get('state')}
            for r in self.records.values()]

    async def identity(self,candidate):
        channel=Z2MChannel(self.hass,candidate)
        try:
            await channel.open(0)
            raw=await channel.read()
            if len(raw)>2048: raise DeviceError('tunnel_invalid')
            try: value=json.loads(raw)
            except (ValueError,UnicodeError): raise DeviceError('tunnel_invalid') from None
            if (not isinstance(value,dict) or set(value)!={'v','node_id','certificate'} or value['v']!=1 or
                not re.fullmatch(r'espoid-[0-9a-f]{12}',str(value['node_id'])) or
                not isinstance(value['certificate'],str) or not re.fullmatch(r'(?:[0-9a-f]{2}){100,768}',value['certificate'])):
                raise DeviceError('tunnel_invalid')
            return value
        finally: await channel.close()

    async def execute(self,binding,action):
        if self.stopped: raise DeviceError('tunnel_failed')
        candidate=self.sources.candidate(binding)
        require_service_feature(candidate, 'binding')
        key=candidate['prefix']+':'+candidate['ieee']
        return await self._run(lambda: self.perform(key,candidate,action))

    def mqtt_candidate(self, node_id):
        record = self.records.get("mqtt:" + node_id)
        return record if record and record.get("transport") == "mqtt" else None

    def for_node(self, node_id):
        return next((record for record in self.records.values() if record['node_id'] == node_id), None)

    def candidate(self, target):
        if isinstance(target, dict) and target.get("transport") == "mqtt":
            record = self.mqtt_candidate(target.get("node_id", ""))
            if not record or record["state"] != "active":
                raise DeviceError("binding_missing")
            return record
        return self.sources.candidate(target)

    def candidate_for_node(self, node):
        return self.mqtt_candidate(node.node_id) or self.sources.candidate(node.z2m)

    def mqtt_topic(self, record):
        # A saved broker/topic change takes effect after ESP restart. A locator
        # may move the carrier, never the persisted TLS pin or credential.
        observed=getattr(self.sources,'announcements',{}).get(record['node_id'],{})
        if observed.get('service_mqtt')==1:
            try:return mqtt_target({**observed,'node_id':record['node_id'],'transport':'mqtt'})['topic']
            except DeviceError:pass
        return record['topic']

    async def enroll_mqtt(self, candidate, certificate, nonce, *, reset=False):
        candidate = mqtt_target(candidate)
        certificate = enrollment_certificate(certificate)
        if not hex_string(nonce, 64):
            raise DeviceError("invalid_request")
        return await self._run(lambda: self._enroll_mqtt(candidate, certificate, nonce, reset=reset))

    async def mqtt_status(self, node_id):
        async def read():
            record = self.mqtt_candidate(node_id)
            if not record:
                raise DeviceError("binding_missing")
            try:
                snapshot = await self.resource_rpc(record, {"resource": "status", "action": "item"})
                if snapshot.get("error"):
                    raise DeviceError(snapshot["error"])
                data = snapshot["data"]
                record.update(checked_at=stamp(), error=None, status={
                    "node_id": data["node_id"], "boot_id": data.get("boot_id"), "revision": 1,
                    "firmware_version": data.get("running_version"), "free_heap": data.get("free_heap")})
                await self.save()
                return snapshot
            except DeviceError as error:
                record.update(error=error.code, checked_at=stamp())
                await self.save()
                raise
        return await self._run(read)

    async def perform(self,key,candidate,action):
        _LOGGER.debug("Service channel action=%s target=%s",action,candidate['ieee'])
        record=self.records.get(key)
        if action == 'rebind':
            return await self.rebind(key, candidate)
        if record and record.get('replacement'):
            raise DeviceError('binding_rebind_pending')
        if action=='status' and record is None: raise DeviceError('binding_missing')
        if record is None:
            if len(self.records)>=MAX_NODES: raise DeviceError('too_many_nodes')
            identity=await self.identity(candidate)
            previous = self.for_node(identity['node_id'])
            if previous is not None:
                return await self.replace_target(previous, candidate, identity['certificate'], reset=False)
            _LOGGER.debug("Public identity received target=%s",candidate['ieee'])
            # The accepted Z2M installation is the initial trust path. Every
            # later connection uses this persisted certificate, never discovery.
            record={k:candidate[k] for k in ('prefix','ieee')}
            record.update(node_id=identity['node_id'],certificate=identity['certificate'],
                binding_id=secrets.token_hex(16),token=secrets.token_hex(32),revision=1,state='pending')
            self.records[key]=record
            # Persist recovery material BEFORE any credential reaches the ESP.
            try: await self.save()
            except DeviceError:
                self.records.pop(key,None)
                raise
        try:
            await self.authenticate(candidate, record, prepare=action == 'bind')
            await self.save()
            return self.result(key)
        except DeviceError as error:
            record.update(state='uncertain',error=error.code,checked_at=stamp())
            await self.save()
            raise

    async def rebind(self, key, candidate):
        record = self.records.get(key)
        identity = None
        if record is None:
            identity = await self.identity(candidate)
            record = self.for_node(identity['node_id'])
        if record is None:
            raise DeviceError('binding_missing')
        replacement = record.get('replacement')
        if replacement is not None:
            certificate = replacement['certificate']
        else:
            identity = identity or await self.identity(candidate)
            if identity['node_id'] != record['node_id']:
                raise DeviceError('binding_identity_mismatch')
            certificate = identity['certificate']
        return await self.replace_target(record, candidate, certificate, reset=True)

    async def replace_target(self, record, candidate, certificate, *, reset, nonce=None):
        """Stage one node's new carrier or reset credential before any prepare."""
        if self.transition_busy(record['node_id']):
            raise DeviceError('operation_busy')
        key = binding_key(record)
        target = mqtt_target(candidate) if candidate.get('transport') == 'mqtt' else {
            field: candidate[field] for field in ('prefix', 'ieee')}
        if reset and certificate == record['certificate']:
            raise DeviceError('binding_not_reset')
        if not reset and certificate != record['certificate']:
            raise DeviceError('binding_identity_mismatch')
        replacement = record.get('replacement')
        if replacement is not None:
            if (replacement['certificate'] != certificate or binding_key(replacement) != binding_key(target)
                    or (replacement['certificate'] != record['certificate']) != reset):
                raise DeviceError('binding_rebind_pending')
        else:
            replacement = {**target, 'node_id': record['node_id'], 'certificate': certificate,
                'binding_id': secrets.token_hex(16) if reset else record['binding_id'],
                'token': secrets.token_hex(32) if reset else record['token'],
                'revision': 1, 'state': 'pending'}
            if nonce is not None:
                replacement['enrollment'] = nonce
            record['replacement'] = replacement
        record['state'] = 'uncertain'
        # Keep the previous pin/credential and durably stage the replacement
        # BEFORE any prepare packet. Restart never sends or promotes this intent.
        await self.save()
        try:
            await self.authenticate(candidate, replacement, prepare=True)
            replacement.pop('enrollment', None)
            next_key = binding_key(replacement)
            self.records.pop(key)
            self.records[next_key] = replacement
            try:
                await self.save()
            except BaseException:
                self.records.pop(next_key, None)
                self.records[key] = record
                raise
            return self.result(next_key)
        except BaseException as error:
            code = error.code if isinstance(error, DeviceError) else 'outcome_uncertain'
            replacement.update(state='uncertain', error=code, checked_at=stamp())
            record.update(error=code, checked_at=stamp())
            await self.save()
            raise

    async def authenticate(self, candidate, record, *, prepare):
        if not prepare and record['state'] in ('active','uncertain') and self.control_supported(candidate, record):
            result = await self.machine_rpc(candidate, 'maintenance_read')
            status = result['status']
            record.update(state='active', checked_at=stamp(), error=None, status={
                'node_id': status['node_id'], 'boot_id': status['boot_id'], 'revision': record['revision'],
                'firmware_version': status['running_version'], 'free_heap': status['free_heap']})
            return
        certificate = bytes.fromhex(record['certificate'])
        context = await self.hass.async_add_executor_job(tls_context, certificate)
        channel = MqttChannel(self.hass, self.mqtt_topic(record)) if record.get('transport') == 'mqtt' else Z2MChannel(self.hass, candidate)
        request = {field: record[field] for field in ('binding_id', 'token', 'revision')}
        request.update(v=1, service_id=self.service_id)
        async with self._channel(record, channel):
            await channel.open(1)
            stream = await TLSStream(channel, context, record['node_id']).handshake(certificate)
            if prepare:
                await stream.rpc({**request, 'op': 'prepare', **({'enrollment': record.get('enrollment', '0' * 64)} if record.get('transport') == 'mqtt' else {})})
                await stream.rpc({**request, 'op': 'commit'})
            result = await stream.rpc({**request, 'op': 'status'})
            if (result.get('node_id') != record['node_id'] or result.get('revision') != record['revision']
                    or result.get('active') is not True):
                raise DeviceError('binding_identity_mismatch')
            record.update(state='active', checked_at=stamp(), error=None,
                status={field: result.get(field) for field in
                    ('node_id', 'boot_id', 'revision', 'firmware_version', 'free_heap')})

    def result(self, key):
        return {'ok': True, 'binding': next(row for row in self.summaries()
            if binding_key(row) == key)}

    async def stop(self):
        self.stopped=True
        tasks=list(self.tasks)
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)

    async def network_rpc(self,candidate,op,**fields):
        """Caller owns lock and timeout; machine credentials stay in this layer."""
        require_service_feature(candidate, 'network')
        key=candidate['prefix']+':'+candidate['ieee']
        record=self.records.get(key)
        if record is None: raise DeviceError('binding_missing')
        if self.control_supported(candidate, record):
            observation = await self.machine_rpc(candidate, 'maintenance_read')
            if not observation['status']['service_mode']:
                raise DeviceError('service_mode_required')
        certificate=bytes.fromhex(record['certificate'])
        context=await self.hass.async_add_executor_job(tls_context,certificate)
        channel=Z2MChannel(self.hass,candidate)
        async with self._channel(record, channel):
            await channel.open(1)
            stream=await TLSStream(channel,context,record['node_id']).handshake(certificate)
            request={k:record[k] for k in ('binding_id','token','revision')}
            result=await stream.rpc({**request,'v':1,'service_id':self.service_id,'op':op,**fields})
            if (type(result.get('state')) is not int or result['state'] not in range(5) or
                type(result.get('result')) is not int or result['result'] not in range(7) or
                type(result.get('password_set')) is not bool or
                not isinstance(result.get('ssid'),str) or not re.fullmatch(r'(?:[0-9a-f]{2}){0,32}',result['ssid']) or
                (result['state']==0 and (result.get('job_id')!='' or result.get('fingerprint')!='')) or
                (result['state']!=0 and (not hex_string(result.get('job_id'),32) or not hex_string(result.get('fingerprint'),64))) or
                ('job_id' in fields and result.get('job_id')!=fields['job_id']) or
                ('fingerprint' in fields and result.get('fingerprint')!=fields['fingerprint'])):
                raise DeviceError('tunnel_invalid')
            return result

    async def resource_rpc(self, candidate, request, origin=''):
        """Caller owns binding lock; resource DTOs stay identical on both carriers."""
        from .domain.device_resource_policy import resource_request, resource_response
        mqtt = candidate.get("transport") == "mqtt"
        if mqtt:
            if not resource_supported(request):
                raise DeviceError("service_unsupported")
            record = self.mqtt_candidate(candidate["node_id"])
        else:
            require_service_feature(candidate, 'resources')
            record = self.records.get(candidate['prefix'] + ':' + candidate['ieee'])
        if not record or record['state'] != 'active': raise DeviceError('binding_missing')
        raw = resource_request(request)
        maintenance = getattr(self, 'maintenance', None)
        node = maintenance.registry.nodes.get(record['node_id']) if maintenance else None
        # Choose the already authenticated outgoing session before opening a
        # carrier. OTA/Recovery deliberately have no MQTT runtime. This is not
        # fallback after a TLS failure and a cached online flag grants nothing.
        if node and maintenance.wifi_observed(node) and (
            not mqtt or (node.status or {}).get('restart_mode') in ('ota', 'recovery', 'wifi_admin')
        ):
            return await maintenance.request_resource(node, record['binding_id'], request, origin)
        if self.control_supported(candidate, record):
            observation = await self.machine_rpc(candidate, 'maintenance_read')
            status = observation['status']
            if request == {'resource': 'status', 'action': 'item'}:
                result = {'id': record['node_id'], 'entity': 'status', 'revision': '', 'request_id': None,
                          'state': 'idle', 'error': None, 'data': status}
                return resource_response(result, request, record['node_id'])
            if not status['service_mode']:
                raise DeviceError('service_mode_required')
        binding = {key: record[key] for key in ('node_id', 'binding_id', 'token', 'revision', 'certificate')}
        if mqtt:
            binding['topic'] = record['topic']
        topic = self.mqtt_topic(record) if mqtt else None
        certificate = bytes.fromhex(binding['certificate'])
        context = await self.hass.async_add_executor_job(tls_context, certificate)
        channel = MqttChannel(self.hass, topic) if mqtt else Z2MChannel(self.hass, candidate)
        async with self._channel(record, channel):
            await channel.open(1)
            stream = await TLSStream(channel, context, binding['node_id']).handshake(certificate)
            envelope = {key: binding[key] for key in ('binding_id', 'token', 'revision')}
            reply = await stream.rpc({**envelope, 'v': 1, 'service_id': self.service_id, 'op': 'resource',
                                      'body': base64.b64encode(raw).decode(), 'origin': origin})
            result = resource_response(reply, request, binding['node_id'])
        if mqtt and request == {'resource': 'status', 'action': 'item'} and result.get('error') is None and result.get('state') == 'idle':
            if (self.stopped or self.mqtt_candidate(binding['node_id']) is not record or record['state'] != 'active'
                    or any(record.get(key) != value for key, value in binding.items())):
                raise DeviceError('binding_auth')
            if topic != binding['topic']:
                record['topic'] = topic
                try:
                    await self.save()
                except BaseException:
                    record['topic'] = binding['topic']
                    raise
        return result

    async def machine_rpc(self,candidate,op,**fields):
        """Serialized caller, same pinned TLS/binding as network provisioning."""
        mqtt=candidate.get('transport')=='mqtt'
        if mqtt:
            if op not in ('maintenance_read','maintenance_submit'):raise DeviceError('service_unsupported')
            if op=='maintenance_submit':
                from .machine_wire import decoded
                from .domain.address_policy import validate_service_origin
                try: operation=decoded(bytes.fromhex(fields['job']))['op']
                except (ValueError,KeyError,TypeError):raise DeviceError('machine_invalid') from None
                if operation not in OPERATIONS:raise DeviceError('service_unsupported')
                fields['origin']=validate_service_origin(self.maintenance.registry.settings.get('service_base_url',''))
            record=self.mqtt_candidate(candidate['node_id'])
        else:
            candidate=await self.sources.service_candidate(candidate,'machine')
            record=self.records.get(candidate['prefix']+':'+candidate['ieee'])
        if record is None or (record['state']!='active' and not (
            op=='maintenance_read' and record['state']=='uncertain' and self.control_supported(candidate,record)
        )): raise DeviceError('binding_missing')
        if not self.control_supported(candidate, record):
            certificate=bytes.fromhex(record['certificate'])
            tls=await self.hass.async_add_executor_job(tls_context,certificate)
            channel=MqttChannel(self.hass,self.mqtt_topic(record)) if mqtt else Z2MChannel(self.hass,candidate)
            async with self._channel(record, channel):
                await channel.open(1)
                stream=await TLSStream(channel,tls,record['node_id']).handshake(certificate)
                return await stream.rpc({'v':1,'op':op,'service_id':self.service_id,
                    **{k:record[k] for k in ('binding_id','token','revision')},**fields})
        if op not in ('maintenance_read', 'maintenance_submit'):
            raise DeviceError('service_unsupported')
        if op == 'maintenance_submit' and not mqtt:
            fields['origin'] = ''
        topic = self.mqtt_topic(record) if mqtt else None
        channel=MqttChannel(self.hass,topic) if mqtt else Z2MChannel(self.hass,candidate)
        captured = dict(record)
        service_id = self.service_id
        async with self._channel(record, channel):
            result = await control_rpc(channel, service_id, captured, {'op': op, **fields})
        if (service_id != self.service_id or not any(value is record for value in self.records.values()) or
            any(record.get(key) != captured.get(key) for key in
               ('node_id','binding_id','token','revision','state','certificate'))):
            raise DeviceError('binding_auth')
        if 'status' in result:
            from .machine_wire import validate_status
            validate_status(result['status'], captured['node_id'])
            if mqtt and topic != captured['topic']:
                record['topic'] = topic
                try:
                    await self.save()
                except BaseException:
                    record['topic'] = captured['topic']
                    raise
        return result

    def control_supported(self, candidate, record):
        return service_control_supported(candidate, record, getattr(self.sources, 'announcements', {}))

    def invalidate_boot(self, node_id, boot_id):
        active = self.channels.get(node_id)
        if active and active['boot_id'] and active['boot_id'] != boot_id:
            active['interrupted'] = True
            active['channel'].abort()

    @asynccontextmanager
    async def _channel(self, record, channel):
        node_id = record['node_id']
        maintenance = getattr(self, 'maintenance', None)
        node = maintenance.registry.nodes.get(node_id) if maintenance else None
        boot = maintenance.boots.get(node_id) if maintenance else None
        if not boot and node:
            boot = (node.status or {}).get('boot_id')
        active = {'channel': channel, 'boot_id': boot, 'interrupted': False}
        self.channels[node_id] = active
        try:
            yield
        finally:
            try:
                await channel.close()
            finally:
                if self.channels.get(node_id) is active:
                    self.channels.pop(node_id)
        if active['interrupted']:
            raise DeviceError('tunnel_failed')

    async def _run(self, execute):
        if self.stopped:
            raise DeviceError("tunnel_failed")
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with self.lock:
                async with asyncio.timeout(90):
                    return await execute()
        except TimeoutError:
            raise DeviceError("tunnel_timeout") from None
        finally:
            self.tasks.discard(task)

    async def _enroll_mqtt(self, candidate, certificate, nonce, *, reset=False):
        key = "mqtt:" + candidate["node_id"]
        record = self.records.get(key)
        previous = self.for_node(candidate['node_id'])
        if previous is not None and (previous is not record or reset or previous.get('replacement')):
            return await self.replace_target(previous, candidate, certificate, reset=reset, nonce=nonce)
        if reset:
            raise DeviceError('binding_missing')
        if record:
            if record["certificate"] != certificate or record["topic"] != candidate["topic"]:
                raise DeviceError("binding_identity_mismatch")
        else:
            if any(r["node_id"] == candidate["node_id"] for r in self.records.values()):
                raise DeviceError("binding_conflict")
            if len(self.records) >= MAX_NODES:
                raise DeviceError("too_many_nodes")
            # Validate the public pin before persisting any new private intent.
            await self.hass.async_add_executor_job(tls_context, bytes.fromhex(certificate))
            record = {**candidate, "certificate": certificate, "enrollment": nonce,
                      "binding_id": secrets.token_hex(16), "token": secrets.token_hex(32),
                      "revision": 1, "state": "pending"}
            self.records[key] = record
            try:
                await self.save()
            except DeviceError:
                self.records.pop(key, None)
                raise
        try:
            await self.authenticate(candidate, record, prepare=True)
            record.pop("enrollment", None)
            await self.save()
            return self.result(key)
        except DeviceError as error:
            record.update(state="uncertain", error=error.code, checked_at=stamp())
            await self.save()
            raise



def valid_binding(key, record):
    return (isinstance(record, dict)
        and binding_target_valid(key, record)
        and (record.get('enrollment') is None or hex_string(record['enrollment'], 64))
        and hex_string(record.get('binding_id'), 32) and hex_string(record.get('token'), 64)
        and record.get('revision') == 1 and record.get('state') in ('pending', 'active', 'uncertain')
        and re.fullmatch(r'espoid-[0-9a-f]{12}', str(record.get('node_id')))
        and isinstance(record.get('certificate'), str)
        and re.fullmatch(r'(?:[0-9a-f]{2}){100,768}', record['certificate']) is not None)


def valid_replacement(key, record):
    replacement = record.get('replacement')
    if replacement is None:
        return True
    try:
        next_key = binding_key(replacement)
        return (valid_binding(next_key, replacement) and replacement.get('replacement') is None
            and replacement['node_id'] == record['node_id']
            and (replacement['certificate'] != record['certificate'] or next_key != key)
            and record['state'] == 'uncertain' and replacement['state'] in ('pending', 'uncertain'))
    except (KeyError, TypeError, AttributeError):
        return False


def binding_target_valid(key, record):
    if record.get("transport") == "mqtt":
        try:
            mqtt_target(record)
            return key == "mqtt:" + record["node_id"]
        except DeviceError:
            return False
    return (record.get("transport") in (None, "zigbee") and isinstance(record.get("prefix"), str)
            and isinstance(record.get("ieee"), str) and key == record["prefix"] + ":" + record["ieee"])

def stamp(): return datetime.now(timezone.utc).isoformat()
def hex_string(value,length): return isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) is not None
