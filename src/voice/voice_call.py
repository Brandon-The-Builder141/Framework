"""
Live Discord voice channel presence: listen for the wake word ("Solen") and
route addressed utterances back out to a caller-supplied handler.

Wake-word gated on purpose — in a multi-person voice channel he should not
butt into every utterance, only ones directed at him. Join/leave is command-
only (see join_voice_channel / leave_voice_channel in src/discord_bot.py);
this module never decides to join anything on its own.

discord-ext-voice-recv delivers decoded PCM per user: 48kHz, 16-bit signed,
stereo. We buffer per-user audio and flush an "utterance" once that user has
gone quiet for SILENCE_GAP_SEC, then transcribe + check for the wake word.
"""
import asyncio
import time

from discord.ext import voice_recv

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2

SILENCE_GAP_SEC = 1.0     # gap since last packet from a user = end of utterance
MIN_UTTERANCE_SEC = 0.5   # ignore blips shorter than this (coughs, mic pops)
MAX_BUFFER_SEC = 30.0     # hard cap so a stuck-open mic can't grow unbounded

# Simple substring match, case-insensitive, near the start of the utterance.
# Whisper mishears are expected on a short local model — this is the v1
# bar; widen this tuple if "Solen" keeps getting missed in practice.
WAKE_WORDS = ("solen",)
WAKE_WORD_WINDOW_CHARS = 24


def has_wake_word(text: str) -> tuple[bool, str]:
    """Return (addressed, remainder_with_wake_word_stripped)."""
    lower = text.lower()
    for w in WAKE_WORDS:
        idx = lower.find(w)
        if idx != -1 and idx < WAKE_WORD_WINDOW_CHARS:
            rest = text[idx + len(w):].lstrip(" ,.-!:;")
            return True, (rest or text)
    return False, text


class ConversationSink(voice_recv.AudioSink):
    """Buffers per-user PCM and calls on_addressed(user, text) once a
    completed, wake-word-gated utterance is transcribed."""

    def __init__(self, on_addressed):
        super().__init__()
        self._buffers: dict[int, bytearray] = {}
        self._users: dict[int, object] = {}
        self._last_packet_at: dict[int, float] = {}
        self._on_addressed = on_addressed
        self._loop = asyncio.get_event_loop()
        self._flush_task: asyncio.Task | None = None

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data) -> None:
        # NOTE: voice_recv calls write() from its own packet-router thread,
        # not the asyncio event loop thread — loop.create_task() is not
        # thread-safe from here, must use run_coroutine_threadsafe.
        if user is None or getattr(user, "bot", False):
            return
        is_first_packet_from_user = user.id not in self._buffers
        buf = self._buffers.setdefault(user.id, bytearray())
        self._users[user.id] = user
        buf.extend(data.pcm)
        self._last_packet_at[user.id] = time.monotonic()

        if is_first_packet_from_user:
            try:
                from src.logging_config import log_voice_event

                log_voice_event("audio_receiving", f"first packet from user_id={user.id} ({len(data.pcm)} bytes)")
            except Exception:
                pass

        max_bytes = int(MAX_BUFFER_SEC * SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
        if len(buf) > max_bytes:
            del buf[: len(buf) - max_bytes]

        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.run_coroutine_threadsafe(self._flush_loop(), self._loop)

            def _report_flush_loop_error(fut):
                exc = fut.exception() if fut.done() and not fut.cancelled() else None
                if exc:
                    try:
                        from src.logging_config import log_error

                        log_error("voice_flush_loop", exc)
                    except Exception:
                        pass

            self._flush_task.add_done_callback(_report_flush_loop_error)

    async def _flush_loop(self) -> None:
        # Polls for users who have gone silent long enough to count as done
        # speaking. Exits once nothing is buffered; write() restarts it.
        while self._buffers:
            await asyncio.sleep(0.2)
            now = time.monotonic()
            for user_id in list(self._buffers.keys()):
                last = self._last_packet_at.get(user_id, 0)
                if now - last < SILENCE_GAP_SEC:
                    continue
                buf = self._buffers.pop(user_id, None)
                self._last_packet_at.pop(user_id, None)
                user = self._users.pop(user_id, None)
                if not buf:
                    continue
                duration = len(buf) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
                if duration < MIN_UTTERANCE_SEC:
                    try:
                        from src.logging_config import log_voice_event

                        log_voice_event("utterance_too_short", f"user_id={user_id} duration={duration:.2f}s")
                    except Exception:
                        pass
                    continue
                asyncio.create_task(self._process_utterance(user, bytes(buf)))

    async def _process_utterance(self, user, pcm: bytes) -> None:
        try:
            from src.logging_config import log_voice_event
            from src.voice.stt import transcribe_pcm

            duration = len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
            text = await asyncio.to_thread(
                transcribe_pcm, pcm, "en", SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH
            )
            text = (text or "").strip()
            log_voice_event(
                "transcribed", f"user_id={getattr(user, 'id', '?')} duration={duration:.2f}s text={text!r}"
            )
            if not text:
                return
            addressed, remainder = has_wake_word(text)
            if not addressed:
                log_voice_event("no_wake_word", f"text={text!r}")
                return
            log_voice_event("addressed", f"user_id={getattr(user, 'id', '?')} remainder={remainder!r}")
            await self._on_addressed(user, remainder)
        except Exception as e:
            try:
                from src.logging_config import log_error

                log_error("voice_call_utterance", e)
            except Exception:
                pass

    def cleanup(self) -> None:
        self._buffers.clear()
        self._users.clear()
        self._last_packet_at.clear()
