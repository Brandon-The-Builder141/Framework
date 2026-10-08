import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pastor_ray.sermons import synthesize,audio_duration
from pastor_ray.settings import ROOT

class ChunkTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_requests_preserve_text_and_join_decodable_audio(self):
        received=[]
        sample=ROOT/'data'/'fish-voice-check.mp3'
        if not sample.exists():self.skipTest('Local audio fixture unavailable')
        async def fake_fish(text,path):
            received.append(text)
            path.write_bytes(sample.read_bytes())
        for text in ('A complete sentence about patience. '*150,'x'*5000):
            received.clear()
            with tempfile.TemporaryDirectory() as folder,patch('pastor_ray.sermons.fish_speech',fake_fish):
                path=Path(folder)/'joined.mp3'
                await asyncio.wait_for(synthesize(text,path),10)
                self.assertGreater(await audio_duration(path),0)
            self.assertGreater(len(received),1)
            self.assertLessEqual(max(map(len,received)),2200)
            self.assertEqual(''.join(''.join(received).split()),''.join(text.split()))
