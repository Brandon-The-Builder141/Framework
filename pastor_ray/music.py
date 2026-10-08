"""Local-file playlist; leave the channel when another bot joins."""
import asyncio
import json
import random
import shutil
import time
import logging

import discord

from pastor_ray.settings import ROOT
log = logging.getLogger('pastor_ray.music')


class Choir:
    def __init__(self, bot, cfg):
        self.bot, self.cfg = bot, cfg
        self.voice = None
        self.track = None
        self.task = None
        self.done = None
        self.recent = []
        self.last_skip = 0.0
        self.lock = asyncio.Lock()
        self.error = ""
        self.started = asyncio.Event()

    def tracks(self):
        path = ROOT / "music_catalog.json"
        if not path.exists():
            return []
        return [t for t in json.loads(path.read_text(encoding="utf-8")) if (ROOT / t["file"]).is_file()]

    @staticmethod
    def another_bot(channel, self_id):
        return any(m.bot and m.id != self_id for m in channel.members)

    async def start(self):
        async with self.lock:
            if self.voice and self.voice.is_connected():
                return "The choir is already connected. Use !ray pause, resume, skip, or stop."
            if not shutil.which("ffmpeg"):
                return "Music needs FFmpeg installed first."
            if not self.tracks():
                return "The music library is empty. Run python -m pastor_ray.fetch_music."
            channel = self.bot.get_channel(self.cfg["voice_channel_id"])
            if not isinstance(channel, discord.VoiceChannel):
                return "I can't find Meditation Vibes. Check my channel permissions."
            if self.another_bot(channel, self.bot.user.id):
                return "Another bot is in Meditation Vibes. Have Garth leave first so we don't play over each other."
            self.voice = await channel.connect(timeout=30, reconnect=True)
            self.error = ""
            self.started.clear()
            self.task = asyncio.create_task(self._play_loop(), name="ray_choir")
            try:
                await asyncio.wait_for(self.started.wait(), timeout=20)
            except asyncio.TimeoutError:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
                return "I couldn't start the audio in time. Please try again."
            if not self.voice or not self.voice.is_playing() or not self.track:
                return f"The choir could not start playback: {self.error or 'audio stopped before it started'}."
            return f"I'm in Meditation Vibes, playing **{self.track['title']}**."

    async def _play_loop(self):
        failures = 0
        try:
            while self.voice and self.voice.is_connected():
                if self.another_bot(self.voice.channel, self.bot.user.id):
                    break
                tracks = self.tracks()
                if not tracks:
                    break
                fresh = [t for t in tracks if t["title"] not in self.recent[-max(1, len(tracks)-1):]]
                self.track = random.choice(fresh or tracks)
                self.recent = (self.recent + [self.track["title"]])[-20:]
                self.done = asyncio.Event()
                done = self.done
                loop = asyncio.get_running_loop()
                errors = []
                def after(error):
                    if error:
                        errors.append(error)
                    loop.call_soon_threadsafe(done.set)
                source = discord.FFmpegPCMAudio(str(ROOT / self.track["file"]),
                    before_options="-nostdin", options=f"-vn -af loudnorm=I=-18:TP=-1.5:LRA=11,volume={float(self.cfg['volume'])}")
                self.voice.play(source, after=after)
                channel = self.bot.get_channel(self.cfg["text_channel_id"])
                if channel:
                    try:
                        await channel.send(f"🎵 **{self.track['title']}**\n{self.track['attribution']}\n"
                            f"[Recording]({self.track['source']}) · [License]({self.track['license_url']})\n"
                            "Playback volume normalized; original recording unchanged.",
                            allowed_mentions=discord.AllowedMentions.none())
                    except discord.HTTPException:
                        # Stop if attribution cannot be displayed.
                        raise RuntimeError("Unable to display recording credits") from None
                else:
                    raise RuntimeError("Attribution channel unavailable")
                await asyncio.sleep(0.5)
                if not self.voice.is_playing():
                    raise RuntimeError("Audio stopped immediately after starting")
                log.info("Playback verified: channel=%s track=%s connected=%s playing=%s", self.voice.channel.id, self.track['title'], self.voice.is_connected(), self.voice.is_playing())
                self.started.set()
                await done.wait()
                failures = failures + 1 if errors else 0
                if failures >= 3:
                    raise RuntimeError("Repeated audio playback failures")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)[:160] or type(exc).__name__
            log.exception("Choir playback failed")
        finally:
            if self.voice:
                await self.voice.disconnect(force=True)
                self.voice = None
            self.track = None
            self.started.set()

    async def stop(self):
        async with self.lock:
            if self.task and not self.task.done():
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
            elif self.voice:
                await self.voice.disconnect(force=True)
                self.voice = None
            self.task = None
            return "The choir has stopped and left voice."

    def control(self, action):
        voice = self.voice
        if not voice or not voice.is_connected():
            return "The choir isn't in voice. Use !ray play."
        if action == "pause":
            if voice.is_playing():
                voice.pause()
            return "Music paused."
        if action == "resume":
            if voice.is_paused():
                voice.resume()
            return "Music resumed." if voice.is_playing() else "The next song is loading."
        if action == "skip":
            if time.monotonic() - self.last_skip < 5:
                return "Give the new song a few seconds before skipping again."
            self.last_skip = time.monotonic()
            voice.stop()
            return "Switching to the next song."
        return "Unknown playback control."

    def status(self):
        if self.track:
            return f"{'Paused' if self.voice and self.voice.is_paused() else 'Playing'}: {self.track['title']} — {self.track['artist']}"
        return "Choir idle." + (f" Last audio error: {self.error}" if self.error else "")

    def credits(self):
        return "\n".join(f"**{t['title']}** — {t['attribution']} · [License]({t['license_url']}) · [Source]({t['source']})" for t in self.tracks())
