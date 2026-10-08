"""Explicit operator smoke test. Stop the normal supervisor before running.

This posts a test notice, speaks a one-minute sermon and one public test answer,
then disconnects. Never run automatically at startup.
"""
import asyncio
import logging
import socket
import sys
from dotenv import dotenv_values
from pastor_ray.bot import Ray
from pastor_ray.settings import ROOT


class CheckRay(Ray):
    checked = False
    passed = False

    async def on_ready(self):
        await super().on_ready()
        if self.checked:
            return
        self.checked=True
        asyncio.create_task(self.verify())

    async def verify(self):
        try:
            await self.sermon.announce('**Pastor Ray voice check:** testing a requested service, pause/resume, interruption, and public Q&A. The session will end automatically.')
            result=await self.sermon.start('Lead a morning service titled Built on Rock. Choose three related verses and explain their context and practical meaning. 10 minutes' if '--progressive-check' in sys.argv else 'forgiveness 1 minute')
            print(result,flush=True)
            async def wait_for(predicate):
                for _ in range(1200 if '--progressive-check' in sys.argv else 480):
                    if predicate(): return
                    if not self.sermon.active: raise RuntimeError('Session ended before verification completed')
                    await asyncio.sleep(1)
                raise TimeoutError('Live verification timed out')
            await wait_for(lambda:self.sermon.state=='preaching' and self.sermon.voice and self.sermon.voice.is_playing())
            await self.sermon.control('pause')
            assert self.sermon.voice.is_paused()
            await asyncio.sleep(1)
            await self.sermon.control('resume')
            assert self.sermon.voice.is_playing()
            print('LIVE: voice connected; sermon playing; pause/resume passed',flush=True)
            self.sermon.interruptions.put_nowait((self.cfg['owner_id'],'What does forgiveness mean when someone has not apologized?'))
            await wait_for(lambda:len(self.sermon.history)>=2 and not self.sermon.interrupting)
            print('LIVE: injected interruption answered; original audio resumed',flush=True)
            print(self.sermon.ask(self.cfg['owner_id'],'How is forgiving someone different from trusting them again?'),flush=True)
            await wait_for(lambda:self.sermon.state=='questions' and len(self.sermon.history)>=4)
            print('LIVE: queued public question answered aloud; sermon context retained',flush=True)
            if '--listen-check' in sys.argv:
                await wait_for(lambda:self.sermon.listening)
                print('LIVE LISTENING READY: say Ray followed by your question in Meditation Vibes.',flush=True)
                await self.sermon.announce('**Microphone check ready.** Say: Ray, how is forgiveness different from trusting someone again?')
                heard=False
                for _ in range(120):
                    if self.sermon.heard_count:
                        heard=True
                        break
                    await asyncio.sleep(1)
                if heard:
                    await wait_for(lambda:len(self.sermon.history)>=6)
                    print('LIVE: incoming DAVE speech transcribed and answered aloud',flush=True)
                else:
                    print('LIVE: no addressed microphone question received; human receive test remains unverified',flush=True)
            (ROOT/'data'/'latest-live-sermon.txt').write_text(self.sermon.transcript,encoding='utf-8')
            await self.sermon.control('end')
            assert not self.sermon.active and self.sermon.voice is None
            self.passed=True
            print('LIVE: end/disconnect passed',flush=True)
        except Exception as exc:
            print('LIVE FAILED: '+type(exc).__name__+': '+str(exc),flush=True)
        finally:
            await self.close()


def main():
    guard=socket.socket()
    guard.bind(('127.0.0.1',18763))
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s:%(name)s:%(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    token=dotenv_values(ROOT/'.env')['PASTOR_RAY_DISCORD_BOT_TOKEN']
    bot=CheckRay()
    try:
        bot.run(token,log_handler=None)
    finally:
        guard.close()
    if not bot.passed:
        raise SystemExit(1)


if __name__=='__main__': main()
