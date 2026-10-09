import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent

# Settings that are the same for every server Ray serves. Everything
# server-shaped (channels, prayer hours, timezone, controllers) lives in the
# guilds table via pastor_ray.guild_config.GuildConfig.
GLOBAL_KEYS = ("ollama_url", "model", "sermon_model", "review_model",
               "fish_voice_id", "fish_model", "volume", "owner_id")


def load_config():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    url = urlparse(cfg["ollama_url"])
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Pastor Ray requires a loopback Ollama endpoint")
    if not cfg["owner_id"] or not cfg["guild_id"]:
        raise ValueError("Owner and guild must be configured")
    return cfg


def load_globals(raw=None):
    """Global (non-guild) settings. Accepts the raw config dict so the guild
    seed path and tests can reuse one file read."""
    cfg = raw if raw is not None else load_config()
    url = urlparse(cfg["ollama_url"])
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Pastor Ray requires a loopback Ollama endpoint")
    if not cfg.get("owner_id"):
        raise ValueError("Owner must be configured")
    return {k: cfg[k] for k in GLOBAL_KEYS if k in cfg}
