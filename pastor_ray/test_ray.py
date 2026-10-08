import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import discord

from pastor_ray.bot import Ray, music_allowed, owner_allowed
from pastor_ray.music import Choir
from pastor_ray.schedule import due_slot, next_prayer
from pastor_ray.settings import load_config
from pastor_ray.storage import Store
from pastor_ray.scripture import passages, context
from pastor_ray.music_intent import music_intent


class MusicIntentTests(unittest.TestCase):
    def test_join_and_play_wordings(self):
        for text in ("Join and play the choir", "1. Join and play the choir", "join the party and play music", "join", "hop in", "I want you to join and play the choir", "join Meditation Vibes and play the choir", "Pastor Ray, can you join Meditation Vibes and play the choir?", "play worship music", "Hey Ray, please play the choir", "<@999> join the voice channel", "go ahead and start the choir"):
            self.assertEqual(music_intent(text), "play", text)

    def test_controls(self):
        for text, expected in (("pause the music", "pause"), ("resume", "resume"), ("skip this song", "skip"), ("stop the choir", "stop"), ("leave Meditation Vibes", "stop"), ("what songs can you play", "playlist")):
            self.assertEqual(music_intent(text), expected)

    def test_not_conversation_or_negated(self):
        for text in ("don't play the choir", "I play music at church", "I told him to join Meditation Vibes", 'What does "play the choir" mean?', "How do you play the choir?", "Can you explain worship?", "I want to stop worrying"):
            self.assertIsNone(music_intent(text), text)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/"test.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_users_and_public_requests_are_isolated(self):
        self.store.remember_turn(1, "private health concern", "private answer")
        self.store.note(1, "private note")
        self.store.summarize(1, "private summary")
        self.assertEqual(self.store.history(2), [])
        self.assertEqual(self.store.profile(2)["notes"], [])
        self.assertEqual(self.store.public_requests(), [])
        self.store.share_request(1, "Please pray for patience")
        self.assertEqual(self.store.public_requests(), ["Please pray for patience"])
        self.store.forget(1)
        self.assertEqual(self.store.history(1), [])
        self.assertEqual(self.store.profile(1), {"notes": [], "conversation_summary": ""})
        self.assertEqual(self.store.public_requests(), [])

    def test_prayer_claim_survives_restart(self):
        self.assertTrue(self.store.claim_prayer("2026-09-22T08:00"))
        self.store.close()
        self.store = Store(Path(self.temp.name)/"test.sqlite3")
        self.assertFalse(self.store.claim_prayer("2026-09-22T08:00"))
        self.assertTrue(self.store.claim_prayer("2026-09-22T13:00"))

    def test_history_bounded_and_ordered(self):
        for i in range(30):
            self.store.remember_turn(1, str(i), f"reply {i}")
        history = self.store.history(1)
        self.assertEqual(len(history), 24)
        self.assertEqual(history[-1]["content"], "reply 29")
        self.assertEqual(history[0]["role"], "user")

    def test_requests_expire(self):
        self.store.share_request(1, "old request")
        with self.store.db:
            self.store.db.execute("UPDATE requests SET expires=0")
        self.assertEqual(self.store.public_requests(), [])


class ScheduleTests(unittest.TestCase):
    def test_dst_and_standard_time(self):
        cfg = load_config()
        for date in ("2026-07-01T12:00:00+00:00", "2026-12-01T13:00:00+00:00"):
            self.assertTrue(due_slot(datetime.fromisoformat(date), cfg).endswith("T08:00"))
        self.assertIsNone(due_slot(datetime.fromisoformat("2026-09-22T12:05:00+00:00"), cfg))

    def test_next_prayer_across_dst(self):
        result = next_prayer(datetime.fromisoformat("2026-11-01T01:00:00+00:00"), load_config())
        self.assertEqual(result.hour, 8)
        self.assertEqual(result.utcoffset().total_seconds(), -5*3600)

    def test_no_backlog(self):
        self.assertIsNone(due_slot(datetime.fromisoformat("2026-09-22T15:30:00+00:00"), load_config()))


class ScriptureTests(unittest.TestCase):
    def test_exact_verse(self):
        self.assertEqual(passages("John 3:16"), ["John 3:16 (KJV): For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life."])

    def test_numbered_book_and_range(self):
        verses = passages("Explain 1 John 1:8-9")
        self.assertEqual(len(verses), 2)
        self.assertTrue(verses[0].startswith("1 John"))

    def test_chapter_alias_and_invalid(self):
        self.assertEqual(len(passages("Psalm 23")), 6)
        self.assertEqual(passages("John 99:3"), [])
        self.assertEqual(passages("John 3:20-2"), [])

    def test_topic_grounding(self):
        self.assertTrue(context("What is grace?")[0].startswith("Ephesians 2:8"))


class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = load_config()

    async def test_nonowner_cannot_reachout(self):
        fake = SimpleNamespace(cfg=self.cfg, member=AsyncMock())
        result = await Ray.command(fake, 550782786013757442, "reachout", "123 hello", private=True)
        self.assertIn("Only Brandon", result)
        fake.member.assert_not_called()

    async def test_private_commands_rejected_in_public(self):
        fake = SimpleNamespace(cfg=self.cfg)
        for name in ("remember", "memory", "forget", "request", "unrequest"):
            result = await Ray.command(fake, self.cfg["owner_id"], name, "secret", private=False)
            self.assertIn("DM", result)

    async def test_owner_outreach_uses_exact_text(self):
        target = SimpleNamespace(id=42, bot=False, send=AsyncMock())
        tmp = tempfile.TemporaryDirectory()
        store = Store(Path(tmp.name)/"state.db")
        fake = SimpleNamespace(cfg=self.cfg, member=AsyncMock(return_value=target), store=store)
        try:
            result = await Ray.command(fake, self.cfg["owner_id"], "reachout", "42 How are you?", private=True)
            self.assertIn("Sent", result)
            self.assertEqual(target.send.call_args.args[0], "Brandon asked me to reach out:\n\nHow are you?")
        finally:
            store.close()
            tmp.cleanup()

    async def test_music_gate(self):
        fake = SimpleNamespace(cfg=self.cfg)
        result = await Ray.command(fake, 42, "play", "", private=True)
        self.assertIn("limited", result)

    def test_no_empty_trust_fail_open(self):
        cfg = {**self.cfg, "music_controller_ids": []}
        self.assertFalse(music_allowed(42, cfg))
        self.assertFalse(owner_allowed(42, cfg))
        self.assertTrue(music_allowed(cfg["owner_id"], cfg))

    def test_voice_collision(self):
        channel = SimpleNamespace(members=[SimpleNamespace(bot=True,id=2)])
        self.assertTrue(Choir.another_bot(channel, 1))
        self.assertFalse(Choir.another_bot(channel, 2))

    async def test_other_channels_do_not_trigger_ai(self):
        fake = SimpleNamespace(cfg=self.cfg, user=SimpleNamespace(id=999), public_chat=AsyncMock())
        message = SimpleNamespace(author=SimpleNamespace(bot=False), content="Pastor Ray, hello", channel=SimpleNamespace(id=123), guild=SimpleNamespace(id=self.cfg["guild_id"]))
        await Ray.on_message(fake, message)
        fake.public_chat.assert_not_called()

    async def test_both_requested_channels_route_plain_messages(self):
        fake = SimpleNamespace(cfg=self.cfg, user=SimpleNamespace(id=999), public_chat=AsyncMock())
        for channel_id in (self.cfg['voice_channel_id'], self.cfg['text_channel_id']):
            message = SimpleNamespace(author=SimpleNamespace(bot=False), content="Hello", channel=SimpleNamespace(id=channel_id), guild=SimpleNamespace(id=self.cfg['guild_id']), mentions=[])
            await Ray.on_message(fake, message)
        self.assertEqual(fake.public_chat.await_count, 2)

    async def test_natural_music_dispatches_real_command_before_ai(self):
        fake = SimpleNamespace(cfg=self.cfg, user=SimpleNamespace(id=999),
            command=AsyncMock(return_value="The choir joined Meditation Vibes."), public_chat=AsyncMock())
        for channel_id in (self.cfg['voice_channel_id'], self.cfg['text_channel_id']):
            channel = MagicMock()
            channel.id = channel_id
            channel.send = AsyncMock()
            channel.typing.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            message = SimpleNamespace(author=SimpleNamespace(bot=False,id=self.cfg['owner_id']), content="Join and play the choir", channel=channel, guild=SimpleNamespace(id=self.cfg['guild_id']), mentions=[])
            await Ray.on_message(fake, message)
            fake.command.assert_awaited_with(self.cfg['owner_id'], "play", "", private=False)
            channel.send.assert_awaited_once()
        fake.public_chat.assert_not_called()

    async def test_natural_music_in_dm(self):
        channel = MagicMock(spec=discord.DMChannel)
        channel.send = AsyncMock()
        channel.typing.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        fake = SimpleNamespace(cfg=self.cfg, member=AsyncMock(return_value=True),
            command=AsyncMock(return_value="Starting the choir."))
        message = SimpleNamespace(author=SimpleNamespace(bot=False,id=self.cfg['owner_id']),content="play the choir",channel=channel,guild=None)
        await Ray.on_message(fake, message)
        fake.command.assert_awaited_once_with(self.cfg['owner_id'], "play", "", private=True)

    async def test_garth_messages_and_bot_messages_ignored(self):
        fake = SimpleNamespace(cfg=self.cfg, user=SimpleNamespace(id=999), public_chat=AsyncMock())
        for content, bot in [('Garth, hello', False), ('hello', True)]:
            message = SimpleNamespace(author=SimpleNamespace(bot=bot), content=content, channel=SimpleNamespace(id=self.cfg['text_channel_id']), guild=SimpleNamespace(id=self.cfg['guild_id']), mentions=[])
            await Ray.on_message(fake, message)
        fake.public_chat.assert_not_called()

    async def test_public_reply_never_reads_private_store(self):
        channel = MagicMock()
        channel.id = self.cfg['voice_channel_id']
        channel.send = AsyncMock()
        channel.typing.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        store = MagicMock()
        fake = SimpleNamespace(user_locks={}, pending_chats=0, public_history={},
            store=store, brain=SimpleNamespace(public_chat=AsyncMock(return_value='Hello, glad you are here.')))
        message = SimpleNamespace(channel=channel, author=SimpleNamespace(id=42), content='Hello Ray')
        await Ray.public_chat(fake, message)
        fake.brain.public_chat.assert_awaited_once_with('Hello Ray', [])
        channel.send.assert_awaited_once()
        self.assertEqual(store.mock_calls, [])
        self.assertEqual(fake.pending_chats, 0)

    async def test_disabled_public_content_does_not_read_history(self):
        fake = SimpleNamespace(public_content_enabled=False, get_channel=lambda _: self.fail("Should not access channels"))
        self.assertEqual(await Ray.public_context(fake), [])


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_prayer_sent_once_and_only_public_data_supplied(self):
        temp = tempfile.TemporaryDirectory()
        store = Store(Path(temp.name)/"state.db")
        store.remember_turn(42, "PRIVATE SECRET", "PRIVATE REPLY")
        store.share_request(42, "Public prayer request")
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock(return_value=SimpleNamespace(id=100))
        fake = SimpleNamespace(cfg=load_config(), store=store,
            get_channel=lambda _: channel, public_context=AsyncMock(return_value=["Public news"]),
            brain=SimpleNamespace(prayer=AsyncMock(return_value="A community prayer. Amen.")))
        try:
            with patch("pastor_ray.bot.due_slot", return_value="2026-09-22T08:00"):
                await Ray.prayer_tick.coro(fake)
                await Ray.prayer_tick.coro(fake)
            channel.send.assert_awaited_once()
            fake.brain.prayer.assert_awaited_once_with("morning", ["Public news"], ["Public prayer request"])
            self.assertEqual(store.last_prayer()["state"], "sent")
        finally:
            store.close()
            temp.cleanup()

    async def test_model_failure_uses_fallback_without_repeat_send(self):
        temp = tempfile.TemporaryDirectory()
        store = Store(Path(temp.name)/"state.db")
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock(side_effect=TimeoutError())
        fake = SimpleNamespace(cfg=load_config(), store=store,
            get_channel=lambda _: channel, public_context=AsyncMock(return_value=[]),
            brain=SimpleNamespace(prayer=AsyncMock(side_effect=RuntimeError())))
        try:
            with patch("pastor_ray.bot.due_slot", return_value="2026-09-22T20:00"):
                await Ray.prayer_tick.coro(fake)
                await Ray.prayer_tick.coro(fake)
            channel.send.assert_awaited_once()
            self.assertIn("Father", channel.send.call_args.args[0])
            self.assertEqual(store.last_prayer()["state"], "failed")
        finally:
            store.close()
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
