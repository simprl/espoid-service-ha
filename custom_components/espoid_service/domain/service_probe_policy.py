"""Read-only proof of an existing Service binding, independent of Wi-Fi jobs."""
from __future__ import annotations

import hashlib
import hmac
import re
from .address_policy import validate_service_origin
from .errors import DeviceError


def service_probe_reply(body, service_id, records):
    fields = {'v', 'purpose', 'service_id', 'binding_id', 'revision', 'node_id', 'request_id', 'origin', 'nonce', 'proof'}
    if (not isinstance(body, dict) or set(body) != fields or type(body['v']) is not int or body['v'] != 1 or
        body['purpose'] != 'service' or type(body['revision']) is not int or not 1 <= body['revision'] <= 0xffffffff or
        not isinstance(body['node_id'], str) or not re.fullmatch(r'espoid-[0-9a-f]{12}', body['node_id']) or
        any(not isinstance(body[key], str) or not re.fullmatch('[0-9a-f]{%d}' % size, body[key])
            for key, size in (('service_id', 32), ('binding_id', 32), ('request_id', 32), ('nonce', 64), ('proof', 64)))):
        raise DeviceError('network_auth')
    try:
        if validate_service_origin(body['origin']) != body['origin']:
            raise DeviceError('network_auth')
    except DeviceError:
        raise DeviceError('network_auth') from None
    matches = [record for record in records.values() if record.get('state') == 'active' and
        record.get('node_id') == body['node_id'] and record.get('binding_id') == body['binding_id'] and
        record.get('revision') == body['revision']]
    if body['service_id'] != service_id or len(matches) != 1:
        raise DeviceError('network_auth')
    token = matches[0]['token']
    if not hmac.compare_digest(service_probe_proof(token, body), body['proof']):
        raise DeviceError('network_auth')
    return {'ok': True, 'proof': service_probe_proof(token, body, response=True)}


def service_probe_proof(token, body, *, response=False):
    transcript = '\n'.join(('ESPOID-SERVICE-1', 'response' if response else 'request', body['service_id'],
        body['binding_id'], str(body['revision']), body['node_id'], body['request_id'], body['origin'], body['nonce']))
    return hmac.new(bytes.fromhex(token), transcript.encode('ascii'), hashlib.sha256).hexdigest()
