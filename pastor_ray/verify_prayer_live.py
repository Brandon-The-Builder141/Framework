"""Explicitly invoked short live prayer check; never used on normal startup."""
import asyncio
import logging
import socket
from dotenv import dotenv_values
from pastor_ray.bot import Ray
from pastor_ray.settings import ROOT

class PrayerCheck(Ray):
    checked=False
    passed=False
    async def on_ready(self):
        await super().on_ready()
        if not self.checked:
            self.checked=True
            asyncio.create_task(self.verify())
    async def verify(self):
        try:
            text=('Heavenly Father, thank You for carrying us into a new morning. '
                  'Before the day gets loud, steady our hearts. Give those who are tired strength, '
                  'those facing hard choices wisdom, and those feeling alone a reminder that they matter. '
                  'Help us listen well, speak with kindness, and take the next right step, even when the whole path is not clear. '
                  'Bless this community and the people we will meet today. Let us bring patience instead of anger, '
                  'courage instead of fear, and grace wherever we go. In Jesus\' name, Amen.')
            async def publish(prayer):
                channel=self.get_channel(self.cfg['text_channel_id'])
                await channel.send('**Pre-morning prayer · voice test**\n\n'+prayer)
            result=await asyncio.wait_for(self.sermon.prayer('pre-morning',text=text,publish=publish),180)
            self.passed=result.startswith('Prayer spoken') and self.sermon.voice is None and not self.sermon.active
            print('LIVE PRAYER: '+result,flush=True)
            print('DISCONNECT VERIFIED: '+str(self.passed),flush=True)
        finally:
            await self.close()

def main():
    guard=socket.socket()
    guard.bind(('127.0.0.1',18763))
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    bot=PrayerCheck()
    try: bot.run(dotenv_values(ROOT/'.env')['PASTOR_RAY_DISCORD_BOT_TOKEN'],log_handler=None)
    finally: guard.close()
    if not bot.passed: raise SystemExit(1)

if __name__=='__main__': main()
