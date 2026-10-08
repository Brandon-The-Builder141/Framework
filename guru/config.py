"""Load and validate guru_config.json."""
import json
from typing import Any

from guru.logger import log_action
from guru.paths import CONFIG_PATH


def _default_config() -> dict[str, Any]:
    return {
        "guild_id": "",
        "category_name": "Relaxing Spot",
        "voice_channel_name": "Meditation Vibes",
        "text_channel_name": "Inspirational Vibes",
        "voice_channel_id": "",
        "text_channel_id": "",
        "owner_discord_id": "",
        "trusted_user_ids": [],
        "youtube_urls": [],
        "youtube_playlist_id": "",
        "fallback_audio_dir": "audio",
        "background_volume": 0.15,
        "quote_interval_hours": 6,
        "default_mood": "calm",
        "tts_voice": "en-US-AriaNeural",
    }


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        cfg = _default_config()
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("config must be a JSON object")
        merged = _default_config()
        merged.update(data)
        if not (merged.get("owner_discord_id") or "").strip():
            from guru.env import GURU_OWNER_ID

            if GURU_OWNER_ID:
                merged["owner_discord_id"] = GURU_OWNER_ID
        return merged
    except Exception as e:
        log_action("config_load_error", str(e), level="error")
        return _default_config()


def normalize_discord_id(raw: str) -> str:
    """Strip suffix noise (e.g. owner id stored as 123_id)."""
    s = str(raw or "").strip()
    digits = "".join(c for c in s if c.isdigit())
    return digits or s
