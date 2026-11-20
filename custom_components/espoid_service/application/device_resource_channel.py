"""One in-flight RPC per device over its existing authenticated outgoing exchange.

Payloads exist only in RAM. Offered commands are never automatically offered twice.
The owning application operation persists uncertainty and owns explicit readback.
"""
from __future__ import annotations

import asyncio
import base64
import secrets
from ..domain.device_resource_policy import resource_request, resource_response
from ..domain.errors import DeviceError
from ..resource_contract import RESOURCE_PROTOCOL


class DeviceResourceChannel:
    def __init__(self, timeout=90, delivery_timeout=8):
        self.pending = {}
        self.timeout = timeout
        self.delivery_timeout = delivery_timeout
        self.stopped = False

    async def request(self, node_id, binding_id, request, origin, *, boot_id=None):
        if self.stopped or node_id in self.pending:
            raise DeviceError('operation_busy')
        raw = resource_request(request)
        pending = {'id': secrets.token_hex(16), 'binding_id': binding_id,
                   'request': request, 'body': base64.b64encode(raw).decode(), 'origin': origin,
                   'boot_id': boot_id, 'sent': False, 'interrupted': False,
                   'delivery_deadline': asyncio.get_running_loop().time() + min(self.delivery_timeout, self.timeout),
                   'offered': asyncio.Event(),
                   'future': asyncio.get_running_loop().create_future()}
        self.pending[node_id] = pending
        try:
            async with asyncio.timeout(self.timeout):
                try:
                    async with asyncio.timeout(self.delivery_timeout):
                        await pending['offered'].wait()
                except TimeoutError:
                    # A poll and timer can run in the same loop turn. Once
                    # offered, keep the response budget; never offer it again.
                    if not pending['sent']:
                        raise DeviceError('request_not_delivered') from None
                result = await pending['future']
                if pending['interrupted']:
                    raise DeviceError(self._interruption_error(pending))
                return result
        except TimeoutError:
            if not pending['sent']:
                raise DeviceError('request_not_delivered') from None
            # A lost read has no mutation outcome to infer. Writes still need
            # explicit result reconciliation, never an automatic retry.
            raise DeviceError('tunnel_timeout' if request['action'] == 'item' else 'outcome_uncertain') from None
        finally:
            if self.pending.get(node_id) is pending:
                self.pending.pop(node_id)
            pending.clear()

    def poll(self, node_id, binding_id, body):
        if self.stopped or set(body) != {'phase', 'reply_id', 'reply'} or body['phase'] != 'resource':
            raise DeviceError('machine_invalid')
        reply_id, reply = body['reply_id'], body['reply']
        if not isinstance(reply_id, str) or not isinstance(reply, str) or len(reply) > 4 * ((RESOURCE_PROTOCOL['RESPONSE_BYTES'] + 2) // 3) or (not reply_id) != (not reply):
            raise DeviceError('machine_invalid')
        pending = self.pending.get(node_id)
        if pending and pending['binding_id'] != binding_id:
            raise DeviceError('machine_auth')
        if reply and pending and reply_id == pending['id'] and pending['sent']:
            from ..machine_wire import decoded
            try:
                value = decoded(base64.b64decode(reply, validate=True))
                value = resource_response(value, pending['request'], node_id)
            except DeviceError as error:
                if not pending['future'].done(): pending['future'].set_exception(error)
            except ValueError:
                if not pending['future'].done(): pending['future'].set_exception(DeviceError('invalid_response'))
            else:
                if not pending['future'].done(): pending['future'].set_result(value)
        offered = pending if (pending and not pending['sent'] and not pending['future'].done()
                              and asyncio.get_running_loop().time() < pending['delivery_deadline']) else None
        if offered:
            offered['sent'] = True
            offered['offered'].set()
        return {'ack': reply_id, 'id': offered['id'] if offered else '',
                'body': offered['body'] if offered else '', 'origin': offered['origin'] if offered else ''}

    def observe_boot(self, node_id, boot_id):
        pending = self.pending.get(node_id)
        if not pending:
            return
        if pending['boot_id'] and pending['boot_id'] != boot_id:
            self._interrupt(pending)
        else:
            pending['boot_id'] = boot_id

    async def stop(self):
        self.stopped = True
        for pending in list(self.pending.values()):
            self._interrupt(pending)

    def _interrupt(self, pending):
        pending['interrupted'] = True
        if not pending['future'].done():
            pending['future'].set_exception(DeviceError(self._interruption_error(pending)))
            pending['offered'].set()

    def _interruption_error(self, pending):
        if not pending['sent']:
            return 'request_not_delivered'
        return 'tunnel_failed' if pending['request']['action'] == 'item' else 'outcome_uncertain'
