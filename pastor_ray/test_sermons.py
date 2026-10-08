import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from pastor_ray.sermons import SermonSession, intent, parse_topic, build_sermon
from pastor_ray.bot import Ray
from pastor_ray.guild_config import GuildConfig
from pastor_ray.settings import load_config, load_globals


def make_gcfg(cfg):
    return GuildConfig(
        guild_id=cfg["guild_id"], text_channel_id=cfg["text_channel_id"],
        voice_channel_id=cfg["voice_channel_id"], timezone=cfg.get("timezone", "America/New_York"),
        prayer_hours=list(cfg.get("prayer_hours", [8, 13, 20])),
        public_context_channel_ids=list(cfg.get("public_context_channel_ids", [])),
        music_controller_ids=list(cfg.get("music_controller_ids", [])))


class RoutingTests(unittest.TestCase):
    def test_natural_requests_and_negation(self):
        for text in ('Ray, preach about forgiveness','join Meditation Vibes and preach about forgiveness','Can you give us a sermon on forgiveness'):
            self.assertEqual(intent(text),('sermon','forgiveness'))
        for text in ("Don't preach about forgiveness",'I told him to preach about faith','How do sermons work?'):
            self.assertIsNone(intent(text))
        self.assertEqual(intent('end the sermon and resume the choir'),('sermon','end choir'))

    def test_lengths(self):
        self.assertEqual(parse_topic('forgiveness for 3 minutes'),('forgiveness',3))
        self.assertEqual(parse_topic('Romans 12:9-13'),('Romans 12:9-13',5))
        for text in ('','faith 0 minutes','faith 25 minutes'):
            with self.assertRaises(ValueError): parse_topic(text)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg=load_config()
        self.channel=MagicMock(spec=discord.VoiceChannel)
        self.channel.send=AsyncMock()
        self.fake_voice=MagicMock()
        self.fake_voice.disconnect=AsyncMock()
        self.channel.connect=AsyncMock(return_value=self.fake_voice)
        self.bot=SimpleNamespace(cfg=self.cfg,globals=load_globals(self.cfg),user=SimpleNamespace(id=999),
            get_channel=lambda _:self.channel,brain=SimpleNamespace(complete=AsyncMock(return_value='A thoughtful answer.')),
            guild_config=lambda gid:make_gcfg(self.cfg),
            primary_guild_for=AsyncMock(return_value=None),member=AsyncMock(return_value=None),
            sermon_for=lambda gid:self.session,choir_for=lambda gid:self.bot.choir,
            _handle_setup_answer=AsyncMock(return_value=False),
            user_locks={},pending_chats=0,public_chat=AsyncMock())
        self.bot.choir=SimpleNamespace(another_bot=lambda *a:False,stop=AsyncMock(),start=AsyncMock(return_value='music started'))
        self.session=SermonSession(self.bot,self.cfg["guild_id"])
        self.session.transcriber.ready=MagicMock()
        self.bot.sermon=self.session

    async def test_answer_repairs_commentary_misquoted_as_scripture(self):
        self.session.transcript='Forgiveness and renewed trust are different.'
        self.bot.brain.complete=AsyncMock(side_effect=[
            'The Scripture says, "Forgiveness and renewed trust are different."',
            'Forgiveness does not require renewed trust. Trust needs evidence of changed behavior.'])
        answer=await self.session.answer('Should I trust them?')
        self.assertIn('evidence',answer)
        self.assertEqual(self.bot.brain.complete.await_count,2)

    async def test_answer_fails_closed_if_fabricated_quote_remains(self):
        self.bot.brain.complete=AsyncMock(return_value='The Scripture says, "Trust everyone blindly."')
        with self.assertRaises(ValueError):await self.session.answer('Should I trust them?')
        self.assertEqual(self.bot.brain.complete.await_count,2)

    async def test_host_gate_and_private_question_rejection(self):
        result=await Ray.command(self.bot,42,'sermon','forgiveness',private=False)
        self.assertIn('Only Brandon',result)
        self.assertFalse(self.session.active)
        self.assertIn('stay private',await Ray.command(self.bot,42,'ask','a secret',private=True))

    async def test_question_queue_limits(self):
        self.session.state='preaching'
        self.assertIn('queued',self.session.ask(1,'First question?'))
        self.assertIn('wait',self.session.ask(1,'Second question?'))
        for i in range(2,11): self.session.ask(i,'Question?')
        self.assertIn('full',self.session.ask(11,'Question?'))

    async def test_cancel_during_preparation(self):
        async def slow(*args,**kwargs): await asyncio.sleep(100)
        with patch('pastor_ray.sermons.build_sermon',side_effect=slow):
            await self.session.start('faith')
            await asyncio.sleep(0)
            self.assertIn('ended',await self.session.control('end'))
        self.assertEqual(self.session.state,'idle')
        self.channel.connect.assert_awaited_once()
        self.fake_voice.disconnect.assert_awaited_once()

    async def test_long_service_cancel_before_audio_never_joins(self):
        self.bot.public_context=AsyncMock(return_value=[])
        waiting=asyncio.Event()
        async def slow(*args,**kwargs):
            waiting.set()
            await asyncio.sleep(100)
        with patch('pastor_ray.sermons.plan_service',side_effect=slow):
            await self.session.start('morning service 20 minutes')
            await asyncio.wait_for(waiting.wait(),1)
            self.channel.connect.assert_not_awaited()
            await self.session.control('end')
        self.channel.connect.assert_not_awaited()
        self.assertEqual(self.session.state,'idle')

    async def test_collision_blocks_start(self):
        with patch('pastor_ray.sermons.Choir.another_bot',return_value=True):
            self.assertIn('Another bot',await self.session.start('faith'))
        self.assertFalse(self.session.active)

    async def test_pause_resume_controls_audio(self):
        self.session.state='preaching'
        self.session.voice=MagicMock()
        await self.session.control('pause')
        self.assertFalse(self.session.gate.is_set())
        self.session.voice.pause.assert_called_once()
        await self.session.control('resume')
        self.assertTrue(self.session.gate.is_set())
        self.session.voice.resume.assert_called_once()

    async def test_questions_never_access_private_store(self):
        self.bot.store=MagicMock()
        self.session.transcript='Public sermon on patience.'
        await self.session.answer('How can I practice patience?')
        self.assertEqual(self.bot.store.mock_calls,[])
        self.assertIn('Public sermon',str(self.bot.brain.complete.call_args))

    async def test_choir_conflict_and_end_resume(self):
        self.session.state='questions'
        uid=self.bot.cfg['owner_id']
        self.assertIn('session is active',await Ray.command(self.bot,uid,'play','',private=False,guild_id=self.cfg['guild_id']))
        self.bot.choir.start.assert_not_called()
        self.assertIn('music started',await Ray.command(self.bot,uid,'sermon','end choir',private=False,guild_id=self.cfg['guild_id']))

    async def test_full_session_with_audio_failure_and_question(self):
        voice=MagicMock()
        voice.disconnect=AsyncMock()
        self.channel.connect=AsyncMock(return_value=voice)
        async def fake_synth(text,path): path.write_bytes(b'test')
        self.session.play=AsyncMock()
        with patch('pastor_ray.sermons.build_sermon',AsyncMock(return_value=(['John 3:16 (KJV): Source'],'Public sermon'))),patch('pastor_ray.sermons.synthesize',side_effect=fake_synth):
            await self.session.start('faith 1 minute')
            for _ in range(20):
                await asyncio.sleep(.01)
                if self.session.state=='questions': break
            self.assertEqual(self.session.state,'questions')
            self.session.ask(42,'What does that mean?')
            for _ in range(30):
                await asyncio.sleep(.01)
                if self.session.history: break
            self.assertEqual(self.session.play.await_count,4)
            self.assertTrue(self.session.history)
            await self.session.control('end')
            voice.disconnect.assert_awaited_once()
            self.assertEqual(self.session.state,'idle')

    async def test_progressive_service_reaches_questions_and_cleans_up(self):
        self.bot.public_context=AsyncMock(return_value=[])
        self.session.play=AsyncMock()
        async def sections(brain,topic,minutes,**kwargs):
            for i in range(6): await kwargs['on_section'](f'Service section {i}',i)
        with patch('pastor_ray.sermons.plan_service',AsyncMock(return_value={'title':'Independent plan','sources':['KJV source']})),patch('pastor_ray.sermons.build_service',sections),patch('pastor_ray.sermons.synthesize',AsyncMock()):
            await self.session.start('morning service 20 minutes')
            for _ in range(100):
                await asyncio.sleep(.01)
                if self.session.state=='questions':break
            self.assertEqual(self.session.state,'questions')
            self.assertIn('Service section 5',self.session.transcript)
            self.session.ask(42,'How do I apply this?')
            for _ in range(100):
                await asyncio.sleep(.01)
                if self.session.history:break
            self.assertTrue(self.session.history)
            await self.session.control('end')
        self.fake_voice.disconnect.assert_awaited_once()
        self.assertEqual(self.session.state,'idle')
        self.assertIsNone(self.session.listener_task)

    async def test_tts_failure_never_claims_playback(self):
        with patch('pastor_ray.sermons.build_sermon',AsyncMock(return_value=([],'Public sermon'))),patch('pastor_ray.sermons.synthesize',AsyncMock(side_effect=RuntimeError('offline'))):
            await self.session.start('faith')
            await self.session.task
        self.assertEqual(self.session.state,'idle')
        self.channel.connect.assert_awaited_once()
        self.fake_voice.disconnect.assert_awaited_once()
        self.assertNotIn('is speaking',str(self.channel.send.call_args_list))

    async def test_audio_failure_never_announces_speaking(self):
        self.session.state='preaching'
        self.session.voice=MagicMock()
        self.session.voice.is_playing.return_value=False
        self.session.voice.is_paused.return_value=False
        with patch('pastor_ray.sermons.discord.FFmpegPCMAudio'):
            with self.assertRaises(RuntimeError):
                await self.session.play('missing-test-file.mp3')
        self.channel.send.assert_not_called()

    async def test_natural_sermon_dispatch_precedes_music_and_ai(self):
        channel=MagicMock()
        channel.id=self.bot.cfg['voice_channel_id']
        channel.send=AsyncMock()
        self.bot.command=AsyncMock(return_value='Preparing sermon')
        self.bot.public_chat=AsyncMock()
        message=SimpleNamespace(author=SimpleNamespace(bot=False,id=self.bot.cfg['owner_id']),
            guild=SimpleNamespace(id=self.bot.cfg['guild_id']),channel=channel,mentions=[],
            content='Ray, join Meditation Vibes and preach about forgiveness')
        await Ray.on_message(self.bot,message)
        self.bot.command.assert_awaited_once_with(self.bot.cfg['owner_id'],'sermon','forgiveness',private=False,guild_id=self.bot.cfg['guild_id'])
        self.bot.public_chat.assert_not_called()

    async def test_question_failure_allows_retry_and_session_stays_alive(self):
        voice=MagicMock()
        voice.disconnect=AsyncMock()
        self.channel.connect=AsyncMock(return_value=voice)
        self.session.play=AsyncMock()
        self.session.answer=AsyncMock(side_effect=RuntimeError('model unavailable'))
        with patch('pastor_ray.sermons.build_sermon',AsyncMock(return_value=([],'Public sermon'))),patch('pastor_ray.sermons.synthesize',AsyncMock()):
            await self.session.start('faith')
            for _ in range(30):
                await asyncio.sleep(.01)
                if self.session.state=='questions': break
            self.session.ask(42,'A question?')
            for _ in range(30):
                await asyncio.sleep(.01)
                if 42 not in self.session.question_users: break
            self.assertNotIn(42,self.session.question_users)
            self.assertTrue(self.session.active)
            self.assertEqual(self.session.history,[])
            await self.session.control('end')

    async def test_exact_reading_from_local_kjv(self):
        sources,text=await build_sermon(self.bot.brain,'forgiveness',1)
        self.assertIn('even as God for Christ',text)
        self.assertIn(sources[0],text)

    async def test_invalid_model_reference_fails_closed(self):
        self.bot.brain.complete=AsyncMock(return_value='Imaginary 999:999')
        with self.assertRaises(ValueError): await build_sermon(self.bot.brain,'a novel topic',1)


if __name__=='__main__': unittest.main()
