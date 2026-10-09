"""Custom Discord voice protocol backed by a DAVE-capable Node child over stdio."""
import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import discord
from pastor_ray.settings import ROOT

log=logging.getLogger('pastor_ray.node_voice')


class NodeVoice(discord.VoiceProtocol):
    def __init__(self,client,channel):
        super().__init__(client,channel)
        self.process=None
        self.reader=None
        self.stderr=None
        self.pending={}
        self.counter=0
        self.connected=False
        self.playing=False
        self.paused=False
        self.finished=asyncio.Event()
        self.error=None
        self.on_utterance=None
        self.receive_errors=0
        self.write_lock=asyncio.Lock()

    async def send(self,command,**values):
        if not self.process or self.process.returncode is not None:
            raise RuntimeError('Voice sidecar is offline')
        async with self.write_lock:
            self.process.stdin.write((json.dumps({'command':command,**values})+'\n').encode())
            await self.process.stdin.drain()

    async def request(self,command,**values):
        self.counter+=1
        key=self.counter
        future=asyncio.get_running_loop().create_future()
        self.pending[key]=future
        try:
            await self.send(command,id=key,**values)
            return await asyncio.wait_for(future,40)
        finally:
            self.pending.pop(key,None)

    async def read_events(self):
        try:
            while line:=await self.process.stdout.readline():
                message=json.loads(line)
                if 'id' in message:
                    future=self.pending.get(message['id'])
                    if future and not future.done():
                        if message.get('error'):
                            log.warning('%s; call sites=%s',message['error'],message.get('diagnostic',[]))
                            future.set_exception(RuntimeError(message['error']))
                        else: future.set_result(message.get('result'))
                elif message.get('event')=='gateway':
                    await self.client.ws.send_as_json(message['payload'])
                elif message.get('event')=='connection':
                    log.info('Node voice state: guild=%s channel=%s state=%s',self.channel.guild.id,self.channel.id,message['state'])
                    self.connected=message['state']=='ready'
                    if message['state'] in ('destroyed','disconnected'):
                        self.error='Voice connection lost'
                        self.finished.set()
                elif message.get('event')=='player':
                    self.playing=message['state']=='playing'
                    self.paused=message['state'] in ('paused','autopaused')
                    if message['state']=='idle': self.finished.set()
                elif message.get('event')=='playback_error':
                    self.error='Node audio playback failed'
                    self.finished.set()
                elif message.get('event')=='utterance' and self.on_utterance:
                    self.on_utterance(message['userId'],message['pcm'])
                elif message.get('event')=='receive_error':
                    self.receive_errors+=1
                    log.warning('Voice receive failure: %s',message.get('kind','unknown'))
        except (ValueError,ConnectionError,RuntimeError) as exc:
            log.warning('Voice bridge failed: %s',type(exc).__name__)
        finally:
            self.connected=False
            self.error='Voice sidecar disconnected'
            self.finished.set()
            for future in self.pending.values():
                if not future.done(): future.set_exception(RuntimeError(self.error))

    async def drain_stderr(self):
        # Child stderr can contain voice internals; do not expose payloads or credentials.
        while await self.process.stderr.readline():
            log.debug('Voice sidecar diagnostic received')

    async def connect(self,*,timeout,reconnect,self_deaf=False,self_mute=False):
        try:
            node=shutil.which('node')
            if not node: raise RuntimeError('Node.js is required for spoken Q&A')
            self.process=await asyncio.create_subprocess_exec(node,str(ROOT/'voice_sidecar'/'index.cjs'),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                limit=12_000_000,creationflags=subprocess.CREATE_NO_WINDOW)
            self.reader=asyncio.create_task(self.read_events())
            self.stderr=asyncio.create_task(self.drain_stderr())
            await self.request('connect',guildId=str(self.channel.guild.id),channelId=str(self.channel.id))
        except BaseException:
            # channel.connect has not returned to the session yet: this protocol
            # must release its child and Discord voice registration itself.
            with contextlib.suppress(Exception):
                await self.disconnect(force=True)
            raise

    async def on_voice_state_update(self,data):
        await self.send('voice_state',data=data)

    async def on_voice_server_update(self,data):
        await self.send('voice_server',data=data)

    def is_connected(self): return self.connected
    def is_playing(self): return self.playing
    def is_paused(self): return self.paused

    async def start_file(self,path,offset=0):
        self.finished.clear()
        self.error=None
        result=await self.request('play',path=str(path),offset=offset)
        if not result.get('packetsSent',0):
            raise RuntimeError('Voice audio transport did not send packets')
        log.info('Voice transport active: guild=%s channel=%s packets=%s',self.channel.guild.id,self.channel.id,result['packetsSent'])

    async def wait_finished(self):
        await self.finished.wait()
        if self.error: raise RuntimeError(self.error)

    async def listen(self,enabled,users=()):
        await self.request('listen',enabled=enabled,users=[str(u) for u in users])

    def fire(self,command):
        async def dispatch():
            try: await self.send(command)
            except (RuntimeError,ConnectionError): pass
        asyncio.create_task(dispatch())

    def pause(self):
        self.paused=True
        self.playing=False
        self.fire('pause')

    def resume(self):
        self.paused=False
        self.playing=True
        self.fire('resume')

    def stop(self):
        self.playing=False
        self.paused=False
        self.fire('stop')

    async def disconnect(self,*,force=False):
        self.on_utterance=None
        try:
            if self.process and self.process.returncode is None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.request('disconnect'),5)
                self.process.stdin.close()
                try: await asyncio.wait_for(self.process.wait(),5)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
        finally:
            self.connected=False
            self.finished.set()
            self.cleanup()
            for task in (self.reader,self.stderr):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError,Exception): await task
