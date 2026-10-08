import unittest
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
from pastor_ray import reread
from pastor_ray.guild_config import GuildConfig


def make_bot(**overrides):
    gcfg = GuildConfig(guild_id=1, text_channel_id=4, voice_channel_id=2,
                       music_controller_ids=[])
    sermon = S(prayer=AsyncMock(return_value='read'))
    bot = S(globals={'owner_id': 7}, user=S(id=9),
            guild_config=lambda gid: gcfg if gid is not None and int(gid) == 1 else None,
            sermon_for=lambda gid: sermon)
    bot._sermon = sermon
    bot._gcfg = gcfg
    for key, value in overrides.items():
        setattr(bot, key, value)
    return bot

class RereadTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_source_and_access_boundary(self):
        source=S(author=S(id=9),content='Original excerpt, unchanged.',jump_url='https://discord.com/channels/1/2/3')
        channel=S(fetch_message=AsyncMock(return_value=source),permissions_for=lambda _:S(view_channel=True))
        bot=make_bot(get_channel=lambda _:channel)
        message=S(guild=S(id=1,get_member=lambda _:S()),author=S(id=7),content='!ray reread',reference=S(channel_id=2,message_id=3))
        self.assertEqual(await reread.handle(bot,message),'read')
        self.assertEqual(bot._sermon.prayer.call_args.kwargs['text'],source.content)
        message.content='!ray reread https://discord.com/channels/1/99/3'
        self.assertIn('Choose a Ray message',await reread.handle(bot,message))
        self.assertEqual(channel.fetch_message.await_count,1)
        message.content='!ray reread'
        source.author.id=22
        self.assertIn('Select one of my',await reread.handle(bot,message))

    def test_requests(self):
        for text in ['Ray, read this aloud','!ray reread','Could you reread this excerpt?']:
            self.assertTrue(reread.requested(text))
        for text in ['Do not reread this','I read this yesterday']:
            self.assertFalse(reread.requested(text))

    async def test_natural_history_lookup_reads_actual_source(self):
        from datetime import datetime, timezone
        original='A sermon about forgiveness and grace. '*12
        item=S(author=S(id=9),content=original,jump_url='https://discord.com/channels/1/2/3',created_at=datetime(2026,9,25,15,tzinfo=timezone.utc))
        async def history(**kwargs):
            yield item
        channel=S(history=history,permissions_for=lambda _:S(view_channel=True))
        brain=S(complete=AsyncMock(side_effect=['{"topic":"forgiveness","date_from":"2026-09-25","date_to":"2026-09-25"}','{"id":0}']))
        bot=make_bot(brain=brain,get_channel=lambda cid:channel if cid==2 else None)
        message=S(guild=S(id=1,get_member=lambda _:S()),author=S(id=7),content='Listen dude, find your sermon on September 25 about forgiveness and reread it in voice',reference=None,channel=S(send=AsyncMock()))
        self.assertTrue(reread.requested(message.content))
        self.assertEqual(await reread.handle(bot,message),'read')
        self.assertEqual(bot._sermon.prayer.call_args.kwargs['text'],original)
