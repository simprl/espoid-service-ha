"""Pinned TLS and authenticated RPC, independent of the packet transport."""
from __future__ import annotations
import json
import secrets
import ssl
from ..domain.errors import DeviceError
from ..resource_contract import RESOURCE_PROTOCOL
from .service_channel import MAX_MESSAGE

RPC_MAX=RESOURCE_PROTOCOL["RESPONSE_BYTES"]
RPC_REQUEST_MAX=2*RESOURCE_PROTOCOL["MQTT_REQUEST_BYTES"]

class TLSStream:
    def __init__(self,channel,context,node_id):
        self.channel=channel
        self.input,self.output=ssl.MemoryBIO(),ssl.MemoryBIO()
        self.tls=context.wrap_bio(self.input,self.output,server_side=False,server_hostname=node_id)

    async def flush(self):
        while self.output.pending: await self.channel.send(self.output.read(MAX_MESSAGE))

    async def handshake(self,certificate):
        try:
            for _ in range(128):
                try:
                    self.tls.do_handshake()
                    await self.flush()
                    if not secrets.compare_digest(self.tls.getpeercert(binary_form=True),certificate):
                        raise DeviceError('binding_identity_mismatch')
                    return self
                except ssl.SSLWantReadError:
                    await self.flush()
                    self.input.write(await self.channel.read())
                except ssl.SSLWantWriteError: await self.flush()
        except ssl.SSLError: raise DeviceError('binding_identity_mismatch') from None
        raise DeviceError('tunnel_failed')

    async def read_exactly(self,size):
        result=bytearray()
        try:
            while len(result)<size:
                try:
                    part=self.tls.read(size-len(result))
                    if not part: raise DeviceError('tunnel_failed')
                    result.extend(part)
                except ssl.SSLWantReadError:
                    await self.flush();self.input.write(await self.channel.read())
                except ssl.SSLWantWriteError: await self.flush()
        except ssl.SSLError: raise DeviceError('tunnel_failed') from None
        return bytes(result)

    async def rpc(self,request):
        body=json.dumps(request,separators=(',',':')).encode()
        if not 0<len(body)<=RPC_REQUEST_MAX: raise DeviceError('invalid_request')
        data=len(body).to_bytes(2,'big')+body
        offset=0
        try:
            while offset<len(data):
                try: offset+=self.tls.write(data[offset:])
                except ssl.SSLWantWriteError: pass
                await self.flush()
        except ssl.SSLError: raise DeviceError('tunnel_failed') from None
        size=int.from_bytes(await self.read_exactly(2),'big')
        if not 0<size<=RPC_MAX: raise DeviceError('tunnel_invalid')
        try: value=json.loads(await self.read_exactly(size))
        except (ValueError,UnicodeError,RecursionError): raise DeviceError('tunnel_invalid') from None
        if not isinstance(value,dict): raise DeviceError('tunnel_invalid')
        if request.get('op') == 'resource' and 'id' in value and 'error' in value:
            return value
        if value.get('ok') is not True:
            code=value.get('error')
            raise DeviceError(code if code in ('binding_auth','binding_conflict','binding_storage',
                'network_invalid','network_busy','network_conflict','network_storage',
                'machine_invalid','machine_conflict','machine_storage') else 'tunnel_failed')
        return value

def tls_context(certificate):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.maximum_version=ssl.TLSVersion.TLSv1_2
    context.set_ciphers('ECDHE-ECDSA-AES128-GCM-SHA256')
    try: context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
    except (ValueError,ssl.SSLError): raise DeviceError('binding_identity_mismatch') from None
    return context
