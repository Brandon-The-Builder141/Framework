"""Guru bot environment — separate from Solen."""
import os
from pathlib import Path

from dotenv import load_dotenv

GURU_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = GURU_ROOT.parent

# guru/.env first, then agent/.env only for missing keys (never Solen's token as default)
load_dotenv(GURU_ROOT / ".env")
load_dotenv(AGENT_ROOT / ".env")

def _digits_only(raw: str) -> str:
    return "".join(c for c in (raw or "") if c.isdigit())


GURU_DISCORD_BOT_TOKEN = (
    os.getenv("GURU_DISCORD_BOT_TOKEN", "").strip()
    or os.getenv("DISCORD_BOT_TOKEN_GURU", "").strip()
)
# Brandon's Discord user id (falls back to Solen DISCORD_OWNER_ID digits only)
GURU_OWNER_ID = _digits_only(
    os.getenv("GURU_OWNER_ID", "").strip()
    or os.getenv("DISCORD_OWNER_ID", "").strip()
)

# LLM (OpenRouter — same key as Solen is fine)
OPENAI_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip() or os.getenv(
    "OPENAI_API_KEY", ""
).strip()
OPENAI_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "").strip() or os.getenv(
    "OPENAI_BASE_URL", "https://openrouter.ai/api/v1"
).strip()
OPENAI_MODEL = os.getenv(
    "GARTH_MODEL",
    os.getenv("OPENAI_MODEL", "openai/gpt-oss-120b:free"),
).strip()

# Fallback chain, tried in order (free-first). On a rate-limit (429) Garth falls
# through to the next model instead of failing. Comma-separated in env.
OPENAI_MODELS = [
    m.strip()
    for m in (os.getenv("GARTH_MODELS", "") or os.getenv("OPENAI_MODELS", "")).split(",")
    if m.strip()
] or [OPENAI_MODEL]
# Guarantee the primary (free) model is attempted first.
if OPENAI_MODEL not in OPENAI_MODELS:
    OPENAI_MODELS.insert(0, OPENAI_MODEL)
