"""Bounded packet/session framing shared by Service transport adapters."""
from __future__ import annotations
import asyncio
import secrets
import struct
from ..domain.errors import DeviceError

HEADER=struct.Struct("!IIHHHH")
ACK=struct.Struct("!IIH")
MAX_MESSAGE=4096
PAYLOAD=32

class ServiceChannel:
    def __init__(self):
        self.queue=asyncio.Queue(64)
        self.unsubscribe=None
        self.epoch=secrets.randbelow(0xfffffffe)+1
        self.tx=0
        self.rx=0
        self.assembly=None
        self.completed=None
        self.messages=asyncio.Queue(4)
        self.failed=False
        self.maximum=MAX_MESSAGE

    async def open(self,mode,nonce=b''):
        if mode not in (0,1,2) or (len(nonce)!=32 if mode==2 else bool(nonce)):
            raise DeviceError('tunnel_invalid')
        self.maximum=2048 if mode==2 else MAX_MESSAGE
        self.unsubscribe=await self.subscribe()
        request=self.epoch.to_bytes(4,'big')+bytes([mode])+nonce
        for _ in range(3):
            await self.publish('open',request)
            end=asyncio.get_running_loop().time()+3
            while asyncio.get_running_loop().time()<end:
                try: kind,data=await self.event(end)
                except TimeoutError: break
                if kind=='open' and len(data)==5 and data[:4]==request[:4]:
                    if data[4]: raise DeviceError('tunnel_rejected')
                    return self
        raise DeviceError('tunnel_timeout')

    async def send(self,data):
        if not 0<len(data)<=self.maximum or self.tx==0xffffffff: raise DeviceError('tunnel_invalid')
        self.tx+=1
        count=(len(data)+PAYLOAD-1)//PAYLOAD
        for index in range(count):
            part=data[index*PAYLOAD:(index+1)*PAYLOAD]
            frame=HEADER.pack(self.epoch,self.tx,index,count,len(data),len(part))+part
            wanted=ACK.pack(self.epoch,self.tx,index)
            for _ in range(4):
                await self.publish('data',frame)
                end=asyncio.get_running_loop().time()+1.5
                acknowledged=False
                while asyncio.get_running_loop().time()<end:
                    try: kind,reply=await self.event(end)
                    except TimeoutError: break
                    if kind=='ack' and reply==wanted:
                        acknowledged=True
                        break
                if acknowledged: break
            else: raise DeviceError('tunnel_timeout')

    async def read(self):
        # The whole response uses stop-and-wait fragments. A 980-byte status
        # needs 31 round trips, including broker and radio scheduling latency.
        end=asyncio.get_running_loop().time()+60
        try:
            while self.messages.empty(): await self.event(end)
        except TimeoutError: raise DeviceError('tunnel_timeout') from None
        return self.messages.get_nowait()

    async def close(self):
        try:
            if self.unsubscribe:
                async with asyncio.timeout(2): await self.publish('close',self.epoch.to_bytes(4,'big'))
        except (TimeoutError,DeviceError): pass
        finally:
            if self.unsubscribe: self.unsubscribe();self.unsubscribe=None

    def abort(self):
        """Wake a blocked old-boot exchange; its owner closes the subscription."""
        self.failed = True
        try: self.queue.put_nowait(('closed', b''))
        except asyncio.QueueFull: pass

    def receive_packet(self,kind,data):
        if kind not in ("open","data","ack") or not 0 < len(data) <= 48:
            return
        try: self.queue.put_nowait((kind,data))
        except asyncio.QueueFull: self.failed=True

    async def subscribe(self):
        raise NotImplementedError

    async def publish(self,kind,data):
        raise NotImplementedError

    async def event(self,deadline):
        if self.failed: raise DeviceError('tunnel_failed')
        remaining=deadline-asyncio.get_running_loop().time()
        if remaining<=0: raise TimeoutError
        async with asyncio.timeout(remaining): kind,data=await self.queue.get()
        if self.failed: raise DeviceError('tunnel_failed')
        if kind=='data': await self.data(data)
        return kind,data

    async def data(self,frame):
        if len(frame)<HEADER.size: raise DeviceError('tunnel_invalid')
        epoch,message,index,count,total,size=HEADER.unpack_from(frame)
        if epoch!=self.epoch: return
        expected=(total+PAYLOAD-1)//PAYLOAD
        if (not message or not 0<total<=self.maximum or count!=expected or not index<count or
            size!=min(PAYLOAD,total-index*PAYLOAD) or len(frame)!=HEADER.size+size):
            raise DeviceError('tunnel_invalid')
        if message==self.rx and self.completed is not None:
            old=self.completed
            if old[0]!=(count,total) or old[1][index*PAYLOAD:index*PAYLOAD+size]!=frame[HEADER.size:]:
                raise DeviceError('tunnel_invalid')
            await self.publish('ack',ACK.pack(epoch,message,index))
            return
        if message!=self.rx+1: raise DeviceError('tunnel_invalid')
        if self.assembly is None: self.assembly=((count,total),{})
        shape,parts=self.assembly
        if shape!=(count,total): raise DeviceError('tunnel_invalid')
        part=frame[HEADER.size:]
        if index in parts and parts[index]!=part: raise DeviceError('tunnel_invalid')
        parts[index]=part
        await self.publish('ack',ACK.pack(epoch,message,index))
        if len(parts)==count:
            result=b''.join(parts[i] for i in range(count))
            try: self.messages.put_nowait(result)
            except asyncio.QueueFull: raise DeviceError('tunnel_failed') from None
            self.completed=(shape,result)
            self.assembly=None
            self.rx=message
