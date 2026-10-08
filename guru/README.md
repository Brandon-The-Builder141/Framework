# Guru — standalone Discord meditation bot

**Separate bot from Solen.** Own Discord application, own token, own process.

| | **Solen** | **Guru** |
|---|-----------|----------|
| Start | `python main.py` | `python guru/main.py` or `.\start-guru.ps1` |
| Token | `DISCORD_BOT_TOKEN` in `agent/.env` | `GURU_DISCORD_BOT_TOKEN` in `guru/.env` |
| Role | Assistive agent / dashboard | Meditation voice + quotes |

## Setup

1. [Discord Developer Portal](https://discord.com/developers/applications) → **New Application** (e.g. “Guru”) → Bot → copy token.

2. Enable intents (Bot tab → Privileged Gateway Intents): **Message Content Intent** (required).

3. Invite bot to your server (OAuth2 → bot scopes: `bot`, permissions: Connect, Speak, Send Messages, Manage Channels).

4. Create `guru/.env`:

   ```env
   GURU_DISCORD_BOT_TOKEN=your_guru_bot_token
   GURU_OWNER_ID=your_discord_user_id
   ```

5. Install deps (from `agent/`):

   ```powershell
   pip install -r requirements.txt
   ```

   Requires **ffmpeg** on PATH.

6. Run Guru (keep Solen separate):

   ```powershell
   cd agent
   python guru/main.py
   ```

## Talk to Garth (natural language)

**DM Garth** or say his name in a message:

- *"Hey Garth, join the voice channel and let's meditate"*
- *"Let's chill to some relaxing music"*
- *"Set up the Relaxing Spot category if it's not there"*
- *"Create a category called Zen Lounge with a voice channel called Chill Pad"*

He remembers you (`guru/guru_profile.json` + `guru/garth_memory/`).

Slash shortcuts still work: `/guru setup`, `/guru start`, `/guru stop`.

Edit `guru/guru_config.json` for `trusted_user_ids` (Travis), YouTube URLs.
Add `OPENROUTER_API_KEY` to `guru/.env` (or uses `agent/.env` via fallback).

## Files

- `guru/.env` — **Guru token only** (do not reuse Solen’s token)
- `guru_config.json`, `guru_profile.json`, `tasks.json`, `guru_logs/`, `scripts/`, `audio/`

## Tests

```powershell
python guru/run_demo.py
```

See `artifacts/guru_project_overview.md` for product vision.
