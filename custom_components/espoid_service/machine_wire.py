"""Bounded machine wire. No HA dependencies or secret serialization in errors."""
from __future__ import annotations
import hashlib
import hmac
import json
import re
from .domain.errors import DeviceError

EXCHANGE = '/api/espoid_service/device/exchange'
TRANSFER = '/api/espoid_service/device/transfers/'
OPERATIONS = ('status','retry_transport','profile_read','profile_validate','profile_store','diagnostics',
              'ota','ota_confirm','hold','reboot_wifi','reboot_zigbee','recovery_retry','profile_default','profile_file','service_enter','service_exit','diagnostics_save')
ZERO = '0' * 64

def hex_value(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{'+str(length)+'}', value) is not None

def context(value):
    if not isinstance(value, str) or len(value) >= 256:
        raise DeviceError('machine_auth')
    fields = value.split(':')
    if (len(fields) != 6 or not hex_value(fields[0],32) or not hex_value(fields[1],32)
        or not re.fullmatch(r'espoid-[0-9a-f]{12}',fields[2]) or not hex_value(fields[3],16)
        or not hex_value(fields[4],64) or not hex_value(fields[5],64)):
        raise DeviceError('machine_auth')
    return fields

def proof(key, response, method, path, ctx, content_type, size, digest):
    context(ctx)
    if (method not in ('POST','GET') or not isinstance(path,str) or not path.startswith('/') or len(path)>160
        or any(c in path for c in '\r\n?#') or content_type not in ('application/json','application/octet-stream')
        or type(size) is not int or not 0 <= size <= 2*1024*1024 or not hex_value(digest,64)):
        raise DeviceError('machine_auth')
    base = f'ESPOID-MACHINE-1\n{"response" if response else "request"}\n{method}\n{path}\n{ctx}\n{content_type}\n{size}\n{digest}\n'
    return hmac.new(key, base.encode('ascii'), hashlib.sha256).hexdigest()

def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',',':'), allow_nan=False).encode('ascii')

def decoded(raw):
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result: raise ValueError()
            result[key] = value
        return result
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError,UnicodeError,RecursionError,TypeError):
        raise DeviceError('machine_invalid') from None

def descriptor(identifier, sequence, operation, size=0, digest='', version='', expected=''):
    if (not hex_value(identifier,32) or type(sequence) is not int or not 1<=sequence<=0xffffffff
        or operation not in OPERATIONS or type(size) is not int or not 0<=size<=2*1024*1024
        or (digest and not hex_value(digest,64)) or (version and not re.fullmatch(r'0x[0-9a-f]{8}',version))
        or (expected and not hex_value(expected,64) and not hex_value(expected,16))):
        raise DeviceError('machine_invalid')
    if operation == 'ota' and (not 288<=size<=0x1e0000 or not digest or not version): raise DeviceError('machine_invalid')
    if operation in ('profile_store','profile_validate') and (not 1<=size<=6144 or not digest): raise DeviceError('machine_invalid')
    if operation == 'profile_file' and (not 1<=size<=8710 or not digest or not hex_value(expected,64)): raise DeviceError('machine_invalid')
    if operation == 'profile_store' and not hex_value(expected,64): raise DeviceError('machine_profile_read_required')
    if operation == 'profile_default' and not hex_value(expected,64): raise DeviceError('machine_profile_read_required')
    if operation == 'ota_confirm' and (not hex_value(expected,16) or not digest or not version): raise DeviceError('machine_invalid')
    if operation in ('service_enter','diagnostics_save') and not hex_value(expected,16): raise DeviceError('machine_invalid')
    if operation == 'service_exit' and not hex_value(expected,64): raise DeviceError('machine_profile_read_required')
    return encoded({'id':identifier,'seq':sequence,'op':operation,'size':size,'sha':digest,'version':version,'expected':expected})


def validate_status(status, node, boot=None):
    fields={'node_id','boot_id','running_version','free_heap','profile_sha','wifi_admin_remaining_ms',
            'ota_marker_sha256','ota_marker_version','ota_marker_configured','wifi_ota','recovery','restart_mode','variant_id','configuration_revision','runtime_transport','uptime_ms','sta_connected','service_mode','service_mode_saved'}
    added = {'configuration_revision','runtime_transport','uptime_ms','sta_connected','service_mode','service_mode_saved'}
    if (not isinstance(status,dict) or set(status) not in (fields, fields-added) or status['node_id']!=node
        or not hex_value(status['boot_id'],16) or (boot and status['boot_id']!=boot)
        or not re.fullmatch(r'0x[0-9a-f]{8}',str(status['running_version']))
        or not hex_value(status['profile_sha'],64) or type(status['ota_marker_configured']) is not bool
        or not (status['variant_id'] == '' or hex_value(status['variant_id'],64))
        or status['restart_mode'] not in ('init_wifi','init_zigbee','zigbee','wifi_admin','mqtt','ota','recovery')):
        raise DeviceError('machine_invalid')
    if added & set(status) and (not hex_value(status['configuration_revision'],64) or status['runtime_transport'] not in ('mqtt','zigbee') or
        any(type(status[k]) is not bool for k in ('sta_connected','service_mode','service_mode_saved'))):
        raise DeviceError('machine_invalid')
    for name in ('free_heap','wifi_admin_remaining_ms','uptime_ms'):
        if name not in status: continue
        if type(status[name]) is not int or not 0<=status[name]<=0xffffffff:raise DeviceError('machine_invalid')
    marker=status['ota_marker_configured']
    if (status['ota_marker_sha256'] if not marker else not hex_value(status['ota_marker_sha256'],64)) or (status['ota_marker_version'] if not marker else not re.fullmatch(r'0x[0-9a-f]{8}',str(status['ota_marker_version']))):
        raise DeviceError('machine_invalid')
    ota=status['wifi_ota'];recovery=status['recovery']
    ota_fields={'running','verification_pending','state','downloaded_bytes','total_bytes'}
    if (not isinstance(ota,dict) or set(ota) not in (ota_fields, ota_fields | {'stage','error'})
        or any(type(ota[k]) is not bool for k in ('running','verification_pending'))
        or not isinstance(ota['state'],str) or not re.fullmatch('[a-z_]{1,32}',ota['state'])
        or any(type(ota[k]) is not int or not 0<=ota[k]<=0x1e0000 for k in ('downloaded_bytes','total_bytes'))
        or not isinstance(recovery,dict) or set(recovery)!={'active'} or type(recovery['active']) is not bool):
        raise DeviceError('machine_invalid')
    if 'stage' in ota:
        if (ota['stage'] not in ('','admission','start','manifest','download','image','commit')
            or not isinstance(ota['error'],str) or not re.fullmatch(r'(?:[a-z][a-z0-9_]{0,31})?',ota['error'])
            or bool(ota['stage']) != bool(ota['error'])
            or (ota['error'] and ota['state'] != 'failed')):
            raise DeviceError('machine_invalid')
    return status
