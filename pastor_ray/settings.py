import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


def load_config():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    url = urlparse(cfg["ollama_url"])
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Pastor Ray requires a loopback Ollama endpoint")
    if not cfg["owner_id"] or not cfg["guild_id"]:
        raise ValueError("Owner and guild must be configured")
    return cfg
