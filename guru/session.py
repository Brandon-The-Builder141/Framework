"""Meditation session: voice join, music, TTS script delivery."""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any

import discord

from guru.audio import ffmpeg_pcm_source, pick_ambient_source
from guru.config import load_config
from guru.logger import log_action
from guru.profile import banter_line, load_profile, pick_script_for_profile
from guru.scripts_loader import list_scripts, load_script
from guru.tasks import add_pending, complete_pending, notify_task_complete


def _guild_from_cfg(bot: Any, cfg: dict, ctx: Any) -> discord.Guild | None:
    gid = (cfg.get("guild_id") or "").strip()
    if not gid and getattr(ctx, "guild", None):
        gid = str(ctx.guild.id)
    if not gid and bot.guilds:
        gid = str(bot.guilds[0].id)
    if not gid:
        return None
    return bot.get_guild(int(gid))


class GuruSessionManager:
    def __init__(self) -> None:
        self.active = False
        self.session_mode: str = "idle"  # idle | chill | meditate
        self.paused = False
        self.mood = "calm"
        self.script_choice: str | None = None
        self.last_script_name: str | None = None
        self._task_id: str | None = None
        self._guild_id: int | None = None
        self._recent_track_keys: list[str] = []
        self._current_track_key: str = ""
        self._max_recent_tracks = 12
        self._play_gen = 0
        self._bot: Any = None
        self._voice: discord.VoiceClient | None = None
        self._last_skip_at = 0.0
        self._ambient_next_task: asyncio.Task | None = None

    def set_mood(self, mood: str) -> None:
        self.mood = mood

    def set_script_choice(self, name: str) -> None:
        self.script_choice = name

    def status_text(self) -> str:
        cfg = load_config()
        return (
            f"Guru session active: **{self.active}**\n"
            f"Paused: **{self.paused}**\n"
            f"Mood: **{self.mood}**\n"
            f"Last script: **{self.last_script_name or 'none'}**\n"
            f"Guild: `{cfg.get('guild_id') or '(auto)'}`\n"
            f"Voice channel: `{cfg.get('voice_channel_id') or '(not set)'}`"
        )

    async def _resolve_voice_channel(
        self, bot: Any, ctx: Any, cfg: dict
    ) -> discord.VoiceChannel | None:
        guild = _guild_from_cfg(bot, cfg, ctx)
        if not guild:
            return None

        vid = (cfg.get("voice_channel_id") or "").strip()
        if vid:
            ch = bot.get_channel(int(vid))
            if isinstance(ch, discord.VoiceChannel):
                return ch
            ch = guild.get_channel(int(vid))
            if isinstance(ch, discord.VoiceChannel):
                return ch

        name = cfg.get("voice_channel_name") or "Meditation Vibes"
        return discord.utils.get(guild.voice_channels, name=name)

    def _exclude_track_keys(self) -> frozenset[str]:
        return frozenset(self._recent_track_keys[-self._max_recent_tracks :])

    def _remember_track(self, key: str) -> None:
        if not key:
            return
        if key in self._recent_track_keys:
            self._recent_track_keys.remove(key)
        self._recent_track_keys.append(key)
        if len(self._recent_track_keys) > self._max_recent_tracks:
            self._recent_track_keys = self._recent_track_keys[-self._max_recent_tracks :]

    def _track_label(self, key: str) -> str:
        if key.startswith("local:"):
            return key[6:].replace("-", " ").replace("_", " ").rsplit(".", 1)[0]
        if key.startswith("yt:"):
            return "a YouTube ambient track"
        return "ambient music"

    def _cancel_ambient_schedule(self) -> None:
        task = self._ambient_next_task
        self._ambient_next_task = None
        if task and not task.done():
            task.cancel()

    def _bump_play_gen(self) -> int:
        self._play_gen += 1
        self._cancel_ambient_schedule()
        return self._play_gen

    def _local_only_ambient(self, cfg: dict) -> bool:
        if self.session_mode == "chill":
            return True
        return bool(cfg.get("ambient_local_only"))

    def _play_ambient(
        self, voice: discord.VoiceClient, cfg: dict, *, force_new: bool = False
    ) -> str | None:
        """Start one track. Does not chain on failure (prevents speed-run bug)."""
        if not voice or not voice.is_connected():
            log_action("ambient_play_failed", "Not connected to voice.", level="error")
            return None

        gen = self._bump_play_gen()

        exclude = self._exclude_track_keys()
        if force_new and self._current_track_key:
            exclude = frozenset(set(exclude) | {self._current_track_key})

        picked = pick_ambient_source(
            cfg,
            exclude=exclude,
            local_only=self._local_only_ambient(cfg),
        )
        if not picked:
            return None
        ambient, key = picked
        self._current_track_key = key
        self._remember_track(key)
        self._voice = voice
        self.paused = False

        try:
            vol = float(cfg.get("background_volume") or 0.15)
            source = ffmpeg_pcm_source(ambient, volume=vol)

            def _after(err: Exception | None) -> None:
                if gen != self._play_gen:
                    return
                if err:
                    log_action("ambient_error", str(err)[:120], level="error")
                    return
                if not self.active or not voice.is_connected():
                    return
                if self.paused:
                    return
                gap = float(cfg.get("ambient_gap_seconds") or 4)
                loop = self._bot.loop if self._bot else None
                if loop and loop.is_running():
                    self._ambient_next_task = asyncio.run_coroutine_threadsafe(
                        self._play_next_after_gap(voice, cfg, gen, gap),
                        loop,
                    )

            if voice.is_playing():
                voice.stop()
            voice.play(source, after=_after)
            log_action("ambient_now_playing", self._track_label(key), level="info")
            return self._track_label(key)
        except Exception as e:
            log_action("ambient_play_failed", str(e)[:200], level="error")
            return None

    async def _play_next_after_gap(
        self,
        voice: discord.VoiceClient,
        cfg: dict,
        gen: int,
        gap: float,
    ) -> None:
        """Wait between tracks, then play the next song (natural end only)."""
        await asyncio.sleep(max(2.0, gap))
        if gen != self._play_gen or not self.active:
            return
        if self.paused:
            return
        if not voice.is_connected():
            return
        if voice.is_playing():
            return
        self._play_ambient(voice, cfg, force_new=True)

    async def skip_track(self, bot: Any, ctx: Any) -> str:
        """Skip to a different ambient track (no guided speech)."""
        if not self.active:
            return "I'm not in voice yet — ask me to join with chill music first."

        cfg = load_config()
        cooldown = float(cfg.get("skip_cooldown_seconds") or 5)
        now = time.monotonic()
        if now - self._last_skip_at < cooldown:
            wait = int(cooldown - (now - self._last_skip_at)) + 1
            return f"Easy — let the current song breathe ({wait}s), then I'll switch."

        voice = self._voice
        if not voice or not voice.is_connected():
            for vc in bot.voice_clients:
                if vc.is_connected():
                    voice = vc
                    break
        if not voice or not voice.is_connected():
            return "I'm not connected to a voice channel."

        self._last_skip_at = now
        self._bot = bot
        try:
            self.paused = False
            if voice.is_playing():
                voice.stop()
            await asyncio.sleep(0.6)
            label = self._play_ambient(voice, cfg, force_new=True)
            if not label:
                return "Couldn't load another track — try again in a moment."
            return f"Now playing **{label}** — I'll let it ride unless you ask for another."
        except Exception as e:
            log_action("skip_track_error", str(e)[:200], level="error")
            return f"Had trouble switching tracks: {e}"

    async def pause(self, bot: Any) -> str:
        """Pause playback while staying connected to voice."""
        if not self.active:
            return "I'm not in voice yet."
        voice = self._voice
        if not voice or not voice.is_connected():
            for vc in bot.voice_clients:
                if vc.is_connected():
                    voice = vc
                    break
        if not voice or not voice.is_connected():
            return "I'm not connected to a voice channel."
        if voice.is_paused():
            self.paused = True
            return "Already paused — still here in the channel."
        if not voice.is_playing():
            return "Nothing is playing right now to pause."
        voice.pause()
        self.paused = True
        self._cancel_ambient_schedule()
        return "Paused. I'm still in the channel — say play when you want to continue."

    async def resume(self, bot: Any) -> str:
        """Resume playback while staying connected to voice."""
        if not self.active:
            return "I'm not in voice yet."
        voice = self._voice
        if not voice or not voice.is_connected():
            for vc in bot.voice_clients:
                if vc.is_connected():
                    voice = vc
                    break
        if not voice or not voice.is_connected():
            return "I'm not connected to a voice channel."
        if voice.is_paused():
            voice.resume()
            self.paused = False
            return "Back on — music resumed."

        if voice.is_playing():
            self.paused = False
            return "Already playing."

        # If playback ended while paused/idle, start a fresh ambient track.
        cfg = load_config()
        self.paused = False
        label = self._play_ambient(voice, cfg, force_new=True)
        if label:
            return f"Back on — now playing **{label}**."
        return "I couldn't resume audio yet — try again in a moment."

    async def start(
        self,
        bot: Any,
        ctx: Any,
        user_id: str,
        *,
        script_name: str | None = None,
    ) -> str:
        if self.active:
            return "A session is already running. Use `/guru stop` or `!guru stop`."

        cfg = load_config()
        channel = await self._resolve_voice_channel(bot, ctx, cfg)
        if not channel:
            return (
                "Could not find the voice channel. Invite Guru to your server, run "
                "`!guru setup`, or set `guild_id` + `voice_channel_id` in guru_config.json."
            )

        guild = channel.guild
        self._guild_id = guild.id

        profile = load_profile(user_id)
        self.mood = profile.get("mood") or cfg.get("default_mood") or "calm"

        available = list_scripts()
        pick = script_name or self.script_choice or pick_script_for_profile(available, profile)
        script = load_script(pick or "random")
        if not script:
            return f"No script found for `{pick}`. Available: {', '.join(available)}."

        self.last_script_name = script.get("name") or pick
        self._task_id = add_pending(
            user_id=user_id,
            action="meditation_session",
            detail=self.last_script_name,
            notify_on_complete=True,
        )

        try:
            if guild.voice_client:
                await guild.voice_client.disconnect(force=True)
            voice = await channel.connect()
        except discord.DiscordException as e:
            log_action("voice_join_failed", str(e), level="error")
            complete_pending(self._task_id or "", "failed")
            self._task_id = None
            return f"Could not join voice: {e}"

        self.active = True
        self.session_mode = "meditate"
        self.paused = False
        self._bot = bot
        intro = banter_line(profile, self.mood)
        title = script.get("title", self.last_script_name)
        self._play_ambient(voice, cfg)

        asyncio.create_task(
            self._run_script(bot, ctx, voice, script, user_id),
            name="guru_meditation_script",
        )
        return (
            f"Starting **{title}** in **{channel.name}**. {intro}\n"
            "I'll DM you when the meditation finishes."
        )

    async def start_chill(self, bot: Any, ctx: Any, user_id: str) -> str:
        """Join voice and play ambient music only — no guided script."""
        if self.active:
            return "Already in voice — say stop first if you want to switch."

        cfg = load_config()
        channel = await self._resolve_voice_channel(bot, ctx, cfg)
        if not channel:
            return "No voice channel yet — ask me to set up Relaxing Spot first."

        guild = channel.guild
        try:
            if guild.voice_client:
                await guild.voice_client.disconnect(force=True)
            voice = await channel.connect()
        except discord.DiscordException as e:
            return f"Could not join voice: {e}"

        self.active = True
        self.session_mode = "chill"
        self.paused = False
        self.last_script_name = "chill"
        self._guild_id = guild.id
        self._bot = bot
        self._recent_track_keys = []
        self._last_skip_at = 0.0
        profile = load_profile(user_id)
        intro = banter_line(profile, self.mood)
        label = self._play_ambient(voice, cfg) or "ambient"
        return (
            f"I'm in **{channel.name}** — **{label}** is on. {intro}\n"
            "I'll let each song play through. Say *skip* or *change track* when you want the next one."
        )
    async def _run_script(
        self,
        bot: Any,
        ctx: Any,
        voice: discord.VoiceClient,
        script: dict,
        user_id: str,
    ) -> None:
        try:
            for seg in script.get("segments") or []:
                if not self.active:
                    break
                stype = seg.get("type")
                if stype == "pause":
                    await asyncio.sleep(float(seg.get("seconds") or 10))
                elif stype == "speech":
                    text = (seg.get("text") or "").strip()
                    if not text:
                        continue
                    if self.mood == "playful" and seg.get("playful"):
                        text = seg["playful"]
                    await self._speak_in_voice(voice, text)
            ch = ctx.channel
            if ch:
                await ch.send(
                    f"Meditation **{script.get('title', 'complete')}** finished. "
                    "Rate with `/guru rate` or `!guru rate 1-5`."
                )
        except Exception as e:
            log_action("script_run_error", str(e), level="error")
            try:
                if ctx.channel:
                    await ctx.channel.send(f"Meditation ended with an error: {e}")
            except Exception:
                pass
        finally:
            tid = self._task_id or ""
            task = complete_pending(tid, "completed") if tid else None
            if task:
                await notify_task_complete(
                    bot,
                    task,
                    f"Guru session **{self.last_script_name}** is done. `/guru rate` if it helped.",
                )
            await self.stop(bot, ctx, quiet=True)

    async def _speak_in_voice(self, voice: discord.VoiceClient, text: str) -> None:
        from guru.config import load_config
        from guru.voice_cache import cached_voice_path

        cfg = load_config()
        self._bump_play_gen()
        if voice.is_playing():
            voice.stop()
        await asyncio.sleep(0.4)

        # Prefer a pre-rendered voice clip (Fish, voice 6). Fall back to live
        # Edge TTS for any line that hasn't been rendered yet.
        cached = cached_voice_path(text)
        is_temp = False
        if cached.exists():
            path = str(cached)
        else:
            from guru.tts import synthesize

            voice_id = cfg.get("tts_voice") or "en-US-AriaNeural"
            try:
                audio_bytes = await synthesize(text, voice=voice_id)
            except Exception as e:
                log_action("tts_failed", str(e)[:120], level="error")
                return
            if not audio_bytes:
                return
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            path = tmp.name
            is_temp = True
            tmp.write(audio_bytes)
            tmp.close()

        try:
            done = asyncio.Event()

            def after(_e):
                done.set()

            voice.play(ffmpeg_pcm_source(path, volume=1.0), after=after)
            await asyncio.wait_for(done.wait(), timeout=120)
        except asyncio.TimeoutError:
            log_action("tts_play_timeout", text[:40], level="warn")
        except Exception as e:
            log_action("tts_play_failed", str(e)[:120], level="error")
        finally:
            if is_temp:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass

        if self.active and voice.is_connected():
            await asyncio.sleep(0.5)
            self._play_ambient(voice, cfg, force_new=True)

    async def stop(self, bot: Any, ctx: Any, *, quiet: bool = False) -> str:
        self.active = False
        self.session_mode = "idle"
        self.paused = False
        self._current_track_key = ""
        self._bump_play_gen()
        self._cancel_ambient_schedule()
        self._voice = None
        disconnected = False
        for vc in list(bot.voice_clients):
            try:
                if vc.is_playing():
                    vc.stop()
                await vc.disconnect(force=True)
                disconnected = True
            except Exception as e:
                log_action("voice_leave_error", str(e), level="warn")
        if not quiet:
            if disconnected:
                return "Guru stopped — left voice and silenced music."
            return "Guru was not in a voice channel."
        return ""
