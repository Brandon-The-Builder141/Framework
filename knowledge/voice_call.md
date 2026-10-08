# Voice Call (live Discord voice channel)

You can join a Discord voice channel, listen, and speak — separate from the
file-attached TTS you already send with normal Discord replies.

## Tools

- `join_voice_channel(channel_id)` — join and start listening. Get `channel_id`
  from `list_connected_channels`.
- `leave_voice_channel(channel_id?)` — leave. Omit the id if only connected
  to one channel.

## How it works

- **Command-only.** You only join when the Creator (or someone with
  permission) asks. You never auto-join a channel because someone entered it.
- **Wake-word gated.** In a multi-person voice channel you'd otherwise be
  listening to everything — instead you only respond when someone says
  "Solen" near the start of what they say ("Solen, what's the weather" /
  "hey Solen, ..."). Anything without your name is transcribed, checked, and
  discarded. This is deliberate: it keeps you from butting into conversation
  that isn't directed at you, and keeps the reasoning model from getting a
  paid call on every utterance in the channel.
- Audio is buffered per speaker and flushed as one "utterance" once they've
  been quiet for about a second (`src/voice/voice_call.py`,
  `ConversationSink`). Short blips under ~0.5s (coughs, mic pops) are
  dropped.
- Transcription is the same local faster-whisper model used elsewhere
  (`src/voice/stt.py`, `transcribe_pcm`) — no cloud STT call, no extra cost.
- A reply goes through the normal `agent.chat()` path (memory, tools,
  everything you'd do in text), then gets spoken back into the channel via
  TTS + ffmpeg playback, serialized per-guild so replies don't overlap.

## Known limitations (v1)

- Wake-word matching is a simple case-insensitive substring check — no
  fuzzy matching for STT mishearing "Solen" as something else yet.
- Requires the `discord-ext-voice-recv` package and `ffmpeg` on PATH.
- One utterance in flight at a time per channel — if two people address you
  in the same second, the second reply waits for the first to finish
  speaking.
