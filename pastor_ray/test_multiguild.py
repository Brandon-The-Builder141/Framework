"""Multi-guild refactor tests (T1, T3, T4, T5, T6, T8, T9).

Single-guild behavior is the degenerate case: one active guild row must behave
exactly like the old single-server code.
"""
import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from pastor_ray.bot import Ray
from pastor_ray.brain import Brain
from pastor_ray.guild_config import GuildConfig
from pastor_ray.music import Choir
from pastor_ray.sermons import SermonSession
from pastor_ray.settings import load_config, load_globals
from pastor_ray.storage import Store


def temp_store():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "mg.sqlite3")
    return tmp, store


class GuildStoreTests(unittest.TestCase):
    """T1: per-guild config store."""

    def test_seed_runs_once_from_legacy_config(self):
        tmp, store = temp_store()
        try:
            cfg = load_config()
            first = store.seed_guild_from_legacy(cfg)
            self.assertIsNotNone(first)
            self.assertEqual(first.guild_id, cfg["guild_id"])
            self.assertEqual(first.text_channel_id, cfg["text_channel_id"])
            self.assertEqual(first.prayer_hours, cfg["prayer_hours"])
            # Second seed is a no-op: the live row is never overwritten.
            self.assertIsNone(store.seed_guild_from_legacy(cfg))
            self.assertEqual(len(store.active_guilds()), 1)
        finally:
            store.close()
            tmp.cleanup()

    def test_two_guilds_roundtrip(self):
        tmp, store = temp_store()
        try:
            a = GuildConfig(guild_id=111, text_channel_id=1, voice_channel_id=2,
                            timezone="America/Chicago", prayer_hours=[9, 18])
            b = GuildConfig(guild_id=222, text_channel_id=3, voice_channel_id=4,
                            music_controller_ids=[42])
            store.upsert_guild(a)
            store.upsert_guild(b)
            back = {g.guild_id: g for g in store.active_guilds()}
            self.assertEqual(back[111].timezone, "America/Chicago")
            self.assertEqual(back[111].prayer_hours, [9, 18])
            self.assertEqual(back[222].music_controller_ids, [42])
            self.assertEqual(back[222].text_channel_id, 3)
            # get_guild falls back to the database when the cache misses.
            self.assertEqual(store.get_guild(111).voice_channel_id, 2)
            self.assertIsNone(store.get_guild(999))
        finally:
            store.close()
            tmp.cleanup()

    def test_from_row_ignores_unknown_keys(self):
        g = GuildConfig.from_row(5, '{"guild_id": 5, "future_field": true}')
        self.assertEqual(g.guild_id, 5)
        self.assertEqual(g.prayer_hours, [8, 13, 20])


class ScopedStorageTests(unittest.TestCase):
    """T3: prayer claims and shared requests are scoped per guild."""

    def test_prayer_claim_scoped_per_guild(self):
        tmp, store = temp_store()
        try:
            self.assertTrue(store.claim_prayer(111, "2026-09-22T08:00"))
            # Same slot in another guild is independent.
            self.assertTrue(store.claim_prayer(222, "2026-09-22T08:00"))
            # Same guild + slot is still claimed once.
            self.assertFalse(store.claim_prayer(111, "2026-09-22T08:00"))
            store.prayer_result(111, "2026-09-22T08:00", "sent", "1")
            self.assertEqual(store.last_prayer(111)["state"], "sent")
            self.assertEqual(store.last_prayer(222)["state"], "claimed")
        finally:
            store.close()
            tmp.cleanup()

    def test_requests_scoped_per_guild(self):
        tmp, store = temp_store()
        try:
            store.share_request(7, "Pray for guild A", 111)
            store.share_request(7, "Pray for guild B", 222)
            self.assertEqual(store.public_requests(111), ["Pray for guild A"])
            self.assertEqual(store.public_requests(222), ["Pray for guild B"])
            self.assertEqual(store.public_requests(333), [])
        finally:
            store.close()
            tmp.cleanup()

    def test_legacy_migration(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "legacy.sqlite3"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE prayers (slot TEXT PRIMARY KEY, state TEXT, message_id TEXT, detail TEXT)")
        db.execute("INSERT INTO prayers VALUES ('2026-01-01T08:00','sent','1','')")
        db.execute("CREATE TABLE requests (uid TEXT PRIMARY KEY, content TEXT, expires REAL)")
        db.execute("INSERT INTO requests VALUES ('9','hello', 9999999999)")
        db.commit()
        db.close()
        store = Store(path)
        try:
            store.migrate_guild_scoping(555)
            # Old claim survives under the seed guild; other guilds unaffected.
            self.assertFalse(store.claim_prayer(555, "2026-01-01T08:00"))
            self.assertTrue(store.claim_prayer(556, "2026-01-01T08:00"))
            self.assertEqual(store.public_requests(555), ["hello"])
            self.assertEqual(store.public_requests(556), [])
            # Idempotent: second run changes nothing.
            store.migrate_guild_scoping(555)
            self.assertEqual(store.public_requests(555), ["hello"])
        finally:
            store.close()
            tmp.cleanup()


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    """T4: per-guild prayer scheduler."""

    async def test_two_guilds_independent_schedules(self):
        tmp, store = temp_store()
        try:
            ga = GuildConfig(guild_id=111, text_channel_id=10, voice_channel_id=11,
                             timezone="America/New_York", prayer_hours=[8])
            gb = GuildConfig(guild_id=222, text_channel_id=20, voice_channel_id=21,
                             timezone="America/Chicago", prayer_hours=[20])
            store.upsert_guild(ga)
            store.upsert_guild(gb)
            sent = {}

            def get_channel(cid):
                channel = MagicMock(spec=discord.TextChannel)
                async def _send(text, **kw):
                    sent[cid] = text
                    return SimpleNamespace(id=cid)
                channel.send = _send
                return channel

            async def fake_sermon_prayer(period, text=None, publish=None, reading=False):
                if publish:
                    await publish(text)
                return "Prayer spoken in Meditation Vibes and posted in chat."

            fake = SimpleNamespace(
                store=store, get_channel=get_channel,
                public_context=AsyncMock(return_value=[]),
                brain=SimpleNamespace(prayer=AsyncMock(return_value="Amen.")),
                sermon_for=lambda gid: SimpleNamespace(prayer=fake_sermon_prayer),
            )
            # The loop body dispatches per guild through self._prayer_tick_guild.
            fake._prayer_tick_guild = lambda gcfg: Ray._prayer_tick_guild(fake, gcfg)
            # Only guild A's hour is due.
            with patch("pastor_ray.bot.due_slot",
                       side_effect=lambda now, sched: "2026-09-22T08:00" if 8 in sched["prayer_hours"] else None):
                await Ray.prayer_tick(fake)
            self.assertIn(10, sent)
            self.assertNotIn(20, sent)
            self.assertEqual(store.last_prayer(111)["state"], "sent")
            self.assertIsNone(store.last_prayer(222))
        finally:
            store.close()
            tmp.cleanup()

    async def test_disabled_guild_skipped(self):
        tmp, store = temp_store()
        try:
            g = GuildConfig(guild_id=111, text_channel_id=10, prayers_enabled=False)
            store.upsert_guild(g)
            fake = SimpleNamespace(store=store, get_channel=MagicMock())
            fake._prayer_tick_guild = lambda gcfg: Ray._prayer_tick_guild(fake, gcfg)
            with patch("pastor_ray.bot.due_slot", return_value="2026-09-22T08:00"):
                await Ray.prayer_tick(fake)
            self.assertIsNone(store.last_prayer(111))
            fake.get_channel.assert_not_called()
        finally:
            store.close()
            tmp.cleanup()


class GateTests(unittest.IsolatedAsyncioTestCase):
    """T5: unknown servers get the setup prompt; known servers route."""

    def make_fake(self, gcfg):
        return SimpleNamespace(
            user=SimpleNamespace(id=999),
            guild_config=lambda gid: gcfg if gid is not None and int(gid) == gcfg.guild_id else None,
            _handle_setup_answer=AsyncMock(return_value=False),
            sermon_for=lambda gid: SimpleNamespace(active=False),
            public_chat=AsyncMock(),
            user_locks={},
            pending_chats=0,
        )

    async def test_unknown_guild_gets_setup_prompt(self):
        gcfg = GuildConfig(guild_id=111, text_channel_id=10, voice_channel_id=11)
        fake = self.make_fake(gcfg)
        channel = MagicMock()
        channel.send = AsyncMock()
        message = SimpleNamespace(author=SimpleNamespace(bot=False, id=5), content="!ray help",
                                  channel=channel, guild=SimpleNamespace(id=999))
        await Ray.on_message(fake, message)
        channel.send.assert_awaited_once()
        self.assertIn("!ray setup", channel.send.call_args.args[0])
        fake.public_chat.assert_not_called()

    async def test_unknown_guild_silent_for_unrelated_chat(self):
        gcfg = GuildConfig(guild_id=111, text_channel_id=10, voice_channel_id=11)
        fake = self.make_fake(gcfg)
        channel = MagicMock()
        channel.send = AsyncMock()
        message = SimpleNamespace(author=SimpleNamespace(bot=False, id=5), content="good morning all",
                                  channel=channel, guild=SimpleNamespace(id=999), mentions=[])
        await Ray.on_message(fake, message)
        channel.send.assert_not_called()


class JoinLeaveTests(unittest.IsolatedAsyncioTestCase):
    """T6: join registers with defaults + welcome; leave deactivates."""

    async def test_join_registers_and_welcomes(self):
        tmp, store = temp_store()
        try:
            fake = SimpleNamespace(store=store, guild_cache={})
            channel = MagicMock()
            channel.send = AsyncMock()
            guild = SimpleNamespace(id=777, system_channel=channel, text_channels=[], me=SimpleNamespace())
            await Ray.on_guild_join(fake, guild)
            gcfg = store.get_guild(777)
            self.assertIsNotNone(gcfg)
            self.assertTrue(gcfg.prayers_enabled)
            channel.send.assert_awaited_once()
            self.assertIn("!ray setup", channel.send.call_args.args[0])
        finally:
            store.close()
            tmp.cleanup()

    async def test_remove_deactivates_but_keeps_data(self):
        tmp, store = temp_store()
        try:
            store.upsert_guild(GuildConfig(guild_id=777, text_channel_id=5))
            fake = SimpleNamespace(store=store, guild_cache={777: store.get_guild(777)})
            await Ray.on_guild_remove(fake, SimpleNamespace(id=777))
            self.assertEqual(store.active_guilds(), [])
            # Data is kept for rejoin.
            self.assertIsNotNone(store.get_guild(777))
            self.assertNotIn(777, fake.guild_cache)
        finally:
            store.close()
            tmp.cleanup()


class VoiceSessionTests(unittest.IsolatedAsyncioTestCase):
    """T8: voice sessions are independent per guild (mocked voice)."""

    def make_bot(self, guilds):
        store_holder = {}
        bot = SimpleNamespace(
            globals={"owner_id": 1, "volume": 0.35},
            user=SimpleNamespace(id=2),
            guild_config=lambda gid: guilds.get(int(gid)),
            get_channel=MagicMock(),
        )
        sessions = {}
        def sermon_for(gid):
            if int(gid) not in sessions:
                sessions[int(gid)] = SermonSession(bot, gid)
            return sessions[int(gid)]
        bot.sermon_for = sermon_for
        choirs = {}
        def choir_for(gid):
            if int(gid) not in choirs:
                choirs[int(gid)] = Choir(bot, guilds[int(gid)])
            return choirs[int(gid)]
        bot.choir_for = choir_for
        return bot

    async def test_sessions_are_per_guild(self):
        guilds = {111: GuildConfig(guild_id=111, voice_channel_id=11, text_channel_id=10),
                  222: GuildConfig(guild_id=222, voice_channel_id=21, text_channel_id=20)}
        bot = self.make_bot(guilds)
        s1 = bot.sermon_for(111)
        s2 = bot.sermon_for(222)
        self.assertIsNot(s1, s2)
        self.assertIs(bot.sermon_for(111), s1)  # cached
        self.assertEqual(s1.gcfg.guild_id, 111)
        self.assertEqual(s2.gcfg.guild_id, 222)
        # Disconnecting one session never touches the other.
        s1.voice = AsyncMock()
        s2.voice = AsyncMock()
        self.assertIsNot(s1.voice, s2.voice)

    async def test_announce_targets_own_guild_channel(self):
        guilds = {111: GuildConfig(guild_id=111, voice_channel_id=11, text_channel_id=10),
                  222: GuildConfig(guild_id=222, voice_channel_id=21, text_channel_id=20)}
        bot = self.make_bot(guilds)
        seen = []
        channel = MagicMock()
        channel.send = AsyncMock()
        bot.get_channel = lambda cid: seen.append(cid) or channel
        await bot.sermon_for(111).announce("hello")
        await bot.sermon_for(222).announce("hello")
        self.assertEqual(seen, [11, 21])

    async def test_choirs_are_per_guild(self):
        guilds = {111: GuildConfig(guild_id=111, voice_channel_id=11, text_channel_id=10),
                  222: GuildConfig(guild_id=222, voice_channel_id=21, text_channel_id=20)}
        bot = self.make_bot(guilds)
        c1 = bot.choir_for(111)
        c2 = bot.choir_for(222)
        self.assertIsNot(c1, c2)
        self.assertEqual(c1.gcfg.voice_channel_id, 11)
        self.assertEqual(c2.gcfg.voice_channel_id, 21)


class BrainConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    """T9: at most 2 model calls in flight."""

    async def test_semaphore_bounds_concurrency(self):
        brain = Brain({"ollama_url": "http://127.0.0.1:11434", "model": "test"})
        in_flight = 0
        peak = 0

        async def fake_post(*a, **kw):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            response = MagicMock()
            response.json.return_value = {"message": {"content": "ok"}}
            return response

        brain.client.post = fake_post
        try:
            await asyncio.gather(*[brain.complete([{"role": "user", "content": "hi"}]) for _ in range(4)])
        finally:
            await brain.close()
        self.assertLessEqual(peak, 2)
        self.assertEqual(peak, 2)  # all four really overlapped


class SetupQuestionnaireTests(unittest.TestCase):
    """T7: setup input parsing."""

    def test_parse_hours(self):
        self.assertEqual(Ray._parse_hours("default"), [8, 13, 20])
        self.assertEqual(Ray._parse_hours("8 13 20"), [8, 13, 20])
        self.assertEqual(Ray._parse_hours("6,12,18"), [6, 12, 18])
        self.assertIsNone(Ray._parse_hours("25"))
        self.assertIsNone(Ray._parse_hours("nope"))
        self.assertIsNone(Ray._parse_hours("1 2 3 4 5 6 7"))

    def test_parse_timezone(self):
        self.assertEqual(Ray._parse_timezone("default"), "America/New_York")
        self.assertEqual(Ray._parse_timezone("America/Chicago"), "America/Chicago")
        self.assertIsNone(Ray._parse_timezone("Mars/Olympus"))

    def test_parse_channel_mention(self):
        self.assertEqual(Ray._parse_channel_mention("<#123456>"), 123456)
        self.assertEqual(Ray._parse_channel_mention("123456"), 123456)
        self.assertIsNone(Ray._parse_channel_mention("hello"))


if __name__ == "__main__":
    unittest.main()
