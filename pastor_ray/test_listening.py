import asyncio
import base64
import unittest
import json
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pastor_ray.listening import addressed_question, Transcriber
from pastor_ray.node_voice import NodeVoice
from pastor_ray.sermons import SermonSession
from pastor_ray.settings import ROOT


class SpeechTests(unittest.TestCase):
    def test_addressed_questions(self):
        for text in ('Ray, how do I forgive?', 'Hey Ray, what did that verse mean?', 'Pastor Ray, explain that again.'):
            self.assertIsNotNone(addressed_question(text))
        for text in ('I was talking to Ray yesterday.','What did he say?','Ray.','Pray for patience.'):
            self.assertIsNone(addressed_question(text))

    def test_silence_does_not_load_model_or_hallucinate(self):
        transcriber=Transcriber()
        self.assertEqual(transcriber.transcribe(base64.b64encode(bytes(192000)).decode()),'')
        self.assertIsNone(transcriber.model)

    def test_limits(self):
        transcriber=Transcriber()
        self.assertEqual(transcriber.transcribe('a'*7_680_001),'')
        self.assertEqual(transcriber.transcribe(base64.b64encode(b'abcd').decode()),'')


class ListeningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session=SermonSession(SimpleNamespace(cfg={'owner_id':1,'music_controller_ids':[]}))
        self.session.announce=AsyncMock()
        self.session.transcriber.transcribe=MagicMock(return_value='Ray, what does forgiveness mean?')

    async def test_audio_not_queued_outside_listening(self):
        self.session.receive_utterance('1','audio')
        self.assertTrue(self.session.audio_queue.empty())
        self.session.listening=True
        self.session.gate.clear()
        self.session.receive_utterance('1','audio')
        self.assertTrue(self.session.audio_queue.empty())

    async def test_utterance_reaches_existing_question_queue(self):
        self.session.state='questions'
        self.session.listening=True
        worker=asyncio.create_task(self.session.transcribe_loop())
        try:
            self.session.receive_utterance('123','audio')
            await asyncio.wait_for(self.session.audio_queue.join(),2)
            uid,text=self.session.questions.get_nowait()
            self.assertEqual(uid,123)
            self.assertEqual(text,'what does forgiveness mean?')
            self.assertEqual(self.session.heard_count,1)
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError): await worker

    async def test_stale_audio_discarded_after_pause(self):
        self.session.state='questions'
        self.session.listening=True
        self.session.receive_utterance('123','audio')
        self.session.listen_epoch+=1
        worker=asyncio.create_task(self.session.transcribe_loop())
        try:
            await asyncio.wait_for(self.session.audio_queue.join(),2)
            self.session.transcriber.transcribe.assert_not_called()
            self.assertTrue(self.session.questions.empty())
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError): await worker

    async def test_next_audio_piece_preserves_utterance_epoch(self):
        voice=MagicMock(spec=NodeVoice)
        voice.is_connected.return_value=True
        voice.channel=SimpleNamespace(members=[SimpleNamespace(id=123,bot=False)])
        voice.listen=AsyncMock()
        self.session.voice=voice
        await self.session.set_listening(True)
        epoch=self.session.listen_epoch
        self.session.receive_utterance('123','audio')
        await self.session.set_listening(True)
        self.assertEqual(self.session.listen_epoch,epoch)
        self.assertEqual(self.session.audio_queue.get_nowait()[0],epoch)
        await self.session.set_listening(False)
        self.assertGreater(self.session.listen_epoch,epoch)

    async def test_echo_and_sermon_gate(self):
        self.session.transcription_ready=True
        self.session.set_listening=AsyncMock()
        for state,answering in [('questions',True),('preparing',False)]:
            self.session.state=state
            self.session.answering=answering
            await self.session.refresh_listening()
            self.session.set_listening.assert_awaited_with(False)
        self.session.state='questions'
        self.session.answering=False
        await self.session.refresh_listening()
        self.session.set_listening.assert_awaited_with(True)
        self.session.state='preaching'
        await self.session.refresh_listening()
        self.session.set_listening.assert_awaited_with(True)

    async def test_private_stdio_command_shape(self):
        protocol=NodeVoice(SimpleNamespace(),SimpleNamespace())
        protocol.process=SimpleNamespace(returncode=None,stdin=SimpleNamespace(write=MagicMock(),drain=AsyncMock()))
        await protocol.send('listen',enabled=False)
        payload=protocol.process.stdin.write.call_args.args[0]
        self.assertIn(b'"enabled": false',payload)
        self.assertNotIn(b'token',payload)

    async def test_installed_sidecar_starts_and_exits_on_pipe_close(self):
        process=await asyncio.create_subprocess_exec(shutil.which('node'),str(ROOT/'voice_sidecar'/'index.cjs'),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            process.stdin.write(b'{"id":1,"command":"listen","enabled":false}\n')
            await process.stdin.drain()
            result=json.loads(await asyncio.wait_for(process.stdout.readline(),10))
            self.assertEqual(result['id'],1)
            self.assertFalse(result['result']['listening'])
            async def listen(enabled):
                process.stdin.write((json.dumps({'id':2,'command':'listen','enabled':enabled,'users':['123']})+'\n').encode())
                await process.stdin.drain()
                return json.loads(await asyncio.wait_for(process.stdout.readline(),10))['result']
            first=await listen(True)
            repeated=await listen(True)
            self.assertEqual(first['epoch'],repeated['epoch'])
            stopped=await listen(False)
            self.assertGreater(stopped['epoch'],repeated['epoch'])
            process.stdin.close()
            self.assertEqual(await asyncio.wait_for(process.wait(),5),0)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


if __name__=='__main__': unittest.main()
