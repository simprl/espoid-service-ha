"""Single authenticated, unencrypted control request on the common carrier."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from ..domain.errors import DeviceError
from ..machine_wire import context, decoded, encoded, proof

MAX_MESSAGE = 2048
PATH = '/service/control'


async def control_rpc(channel, service_id, record, request):
    fields = {'op'} if request.get('op') == 'maintenance_read' else {'op','job','origin'}
    if request.get('op') not in ('maintenance_read','maintenance_submit') or set(request) != fields:
        raise DeviceError('machine_invalid')
    nonce = secrets.token_bytes(32)
    key = bytes.fromhex(record['token'])
    await channel.open(2, nonce)
    hello = await channel.read()
    if not 32 < len(hello) <= MAX_MESSAGE:
        raise DeviceError('machine_auth')
    value = decoded(hello[:-32])
    if not isinstance(value, dict) or set(value) != {'context'}:
        raise DeviceError('machine_auth')
    ctx = value['context']
    fields = context(ctx)
    if (fields[:3] != [service_id, record['binding_id'], record['node_id']]
            or fields[4] != nonce.hex() or fields[5] == '0' * 64):
        raise DeviceError('binding_identity_mismatch')
    verify(key, ctx, hello)
    raw = encoded(request)
    if not 0 < len(raw) <= MAX_MESSAGE - 32:
        raise DeviceError('machine_invalid')
    await channel.send(raw + signature(key, False, ctx, raw))
    reply = await channel.read()
    verify(key, ctx, reply)
    result = decoded(reply[:-32])
    if not isinstance(result, dict) or type(result.get('ok')) is not bool:
        raise DeviceError('machine_invalid')
    if result['ok'] is not True:
        raise DeviceError(result.get('error', 'machine_invalid'))
    if 'status' in result and (not isinstance(result['status'], dict) or result['status'].get('boot_id') != fields[3]):
        raise DeviceError('binding_identity_mismatch')
    return result


def signature(key, response, ctx, raw):
    return bytes.fromhex(proof(key, response, 'POST', PATH, ctx, 'application/json',
                               len(raw), hashlib.sha256(raw).hexdigest()))


def verify(key, ctx, message):
    if (not 32 < len(message) <= MAX_MESSAGE or
            not hmac.compare_digest(signature(key, True, ctx, message[:-32]), message[-32:])):
        raise DeviceError('machine_auth')
