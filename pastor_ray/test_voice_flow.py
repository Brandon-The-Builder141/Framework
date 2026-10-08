import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from pastor_ray.sermons import SermonSession,intent
from pastor_ray.bot import Ray


class VoiceFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_reported_request_and_variants(self):
        cases={
            'Let me get a morning sermon for feeling energized Needing energy':'morning service for feeling energized Needing energy',
            'Do a sermon about patience':'patience',
            'Give me a funeral sermon about grief':'funeral grief',
            'Can I get a sermon on hope?':'hope',
            'continue sermon':'resume',
            'join voice chat and talk with us':'conversation',
        }
        for text,topic in cases.items():
            self.assertEqual(intent(text),('sermon',topic),text)
        self.assertEqual(intent('Write a sermon about hope'),('sermon','hope'))
        self.assertEqual(intent('Build a sermon about courage'),('sermon','courage'))
        self.assertEqual(intent('Give me a morning prayer'),('prayer','morning'))
        self.assertEqual(intent('Start a prayer session for strength'),('prayer','for strength'))
        self.assertIsNone(intent('What is a sermon?'))

    async def test_interruption_answers_and_resumes_at_position(self):
        ended=asyncio.Event()
        async def wait_finished(): await ended.wait()
        async def resume_file(*args,**kwargs): ended.set()
        voice=SimpleNamespace(wait_finished=wait_finished,request=AsyncMock(return_value={'seconds':42}),start_file=AsyncMock(side_effect=resume_file))
        bot=SimpleNamespace(brain=SimpleNamespace(complete=AsyncMock(return_value='Forgiveness does not mean abandoning boundaries.')))
        session=SermonSession(bot)
        session.voice=voice
        session.state='preaching'
        session.last_spoken='Original sermon'
        session.play=AsyncMock()
        session.announce=AsyncMock()
        session.refresh_listening=AsyncMock()
        session.set_listening=AsyncMock()
        session.interruptions.put_nowait((42,'What about boundaries?'))
        with tempfile.TemporaryDirectory() as folder,patch('pastor_ray.sermons.synthesize',AsyncMock()):
            path=Path(folder)/'sermon.mp3'
            await asyncio.wait_for(session.wait_with_interruptions(path),3)
            voice.start_file.assert_awaited_once_with(path,offset=41)
        self.assertEqual(len(session.history),2)
        self.assertFalse(session.interrupting)
        self.assertEqual(session.last_spoken,'Original sermon')

    async def test_failed_answer_still_resumes(self):
        ended=asyncio.Event()
        async def finish(): await ended.wait()
        async def resume_file(*args,**kwargs): ended.set()
        session=SermonSession(SimpleNamespace())
        session.voice=SimpleNamespace(wait_finished=finish,request=AsyncMock(return_value={'seconds':8}),start_file=AsyncMock(side_effect=resume_file))
        session.answer=AsyncMock(side_effect=RuntimeError('model offline'))
        session.announce=AsyncMock()
        session.set_listening=AsyncMock()
        session.refresh_listening=AsyncMock()
        session.interruptions.put_nowait((42,'Why?'))
        await asyncio.wait_for(session.wait_with_interruptions(Path('sermon.mp3')),3)
        session.voice.start_file.assert_awaited_once_with(Path('sermon.mp3'),offset=7)

    async def test_name_only_invites_question(self):
        session=SermonSession(SimpleNamespace())
        self.assertIn('Go ahead',await session.answer('__attention__'))

    async def test_prayer_publishes_speaks_and_disconnects_without_listening(self):
        import discord
        channel=MagicMock(spec=discord.VoiceChannel)
        voice=MagicMock()
        voice.disconnect=AsyncMock()
        channel.connect=AsyncMock(return_value=voice)
        bot=SimpleNamespace(cfg={'voice_channel_id':1},get_channel=lambda _:channel,user=SimpleNamespace(id=2),choir=SimpleNamespace(another_bot=lambda *a:False,stop=AsyncMock()))
        session=SermonSession(bot)
        session.play=AsyncMock()
        publish=AsyncMock()
        with patch('pastor_ray.sermons.synthesize',AsyncMock()):
            result=await session.prayer('morning',text='A complete prayer. Amen.',publish=publish)
        self.assertTrue(result.startswith('Prayer spoken'))
        publish.assert_awaited_once_with('A complete prayer. Amen.')
        session.play.assert_awaited_once()
        voice.disconnect.assert_awaited_once_with(force=True)
        self.assertEqual(session.state,'idle')
        self.assertFalse(session.listening)

    async def test_conversation_command_reuses_host_gate(self):
        session=SimpleNamespace(start=AsyncMock(return_value='joining'))
        bot=SimpleNamespace(sermon=session,cfg={'owner_id':1,'music_controller_ids':[]})
        self.assertIn('Only Brandon',await Ray.command(bot,2,'talk','',private=True))
        self.assertEqual(await Ray.command(bot,1,'talk','',private=True),'joining')
        session.start.assert_awaited_once_with('conversation')


if __name__=='__main__': unittest.main()
