import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from pastor_ray.node_voice import NodeVoice

class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_player_started_without_packets_is_not_success(self):
        voice=NodeVoice(SimpleNamespace(),SimpleNamespace(id=2,guild=SimpleNamespace(id=1)))
        voice.request=AsyncMock(return_value={'playing':True,'packetsSent':0})
        with self.assertRaisesRegex(RuntimeError,'did not send packets'):
            await voice.start_file('test.mp3')

    async def test_packet_dispatch_passes_start_check(self):
        voice=NodeVoice(SimpleNamespace(),SimpleNamespace(id=2,guild=SimpleNamespace(id=1)))
        voice.request=AsyncMock(return_value={'playing':True,'packetsSent':3})
        await voice.start_file('test.mp3')
        voice.request.assert_awaited_once_with('play',path='test.mp3',offset=0)

    async def test_failed_join_releases_protocol(self):
        voice=NodeVoice(SimpleNamespace(),SimpleNamespace(id=2,guild=SimpleNamespace(id=1)))
        voice.request=AsyncMock(side_effect=RuntimeError('join timeout'))
        voice.disconnect=AsyncMock()
        voice.read_events=AsyncMock()
        voice.drain_stderr=AsyncMock()
        with patch('pastor_ray.node_voice.shutil.which',return_value='node'),patch('pastor_ray.node_voice.asyncio.create_subprocess_exec',AsyncMock()):
            with self.assertRaises(RuntimeError):
                await voice.connect(timeout=40,reconnect=True)
        voice.disconnect.assert_awaited_once_with(force=True)
        await asyncio.gather(voice.reader,voice.stderr)

    async def test_spawn_failure_also_releases_registration(self):
        voice=NodeVoice(SimpleNamespace(),SimpleNamespace())
        voice.disconnect=AsyncMock()
        with patch('pastor_ray.node_voice.shutil.which',return_value=None):
            with self.assertRaises(RuntimeError):
                await voice.connect(timeout=40,reconnect=True)
        voice.disconnect.assert_awaited_once_with(force=True)
