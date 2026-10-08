"""Configuration for the assistive operating agent."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("AGENT_DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
MEMORY_DIR = DATA_DIR / "memory"
USER_PROFILES_DIR = DATA_DIR / "profiles"
LOGS_DIR = PROJECT_ROOT / "logs"

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
RESEARCH_OUTPUT_DIR = DATA_DIR / "research_output"
TRAINING_DATA_DIR = DATA_DIR / "training_data"
SOUL_TRAINING_DIR = DATA_DIR / "soul_training"
VOICES_DIR = DATA_DIR / "voices"

# Generated images (gitignored). Override with IMAGE_OUTPUT_DIR env (e.g. ~/Pictures/Adam).
IMAGE_OUTPUT_DIR = Path(
    os.getenv("IMAGE_OUTPUT_DIR", str(PROJECT_ROOT / "generated_images"))
).expanduser().resolve()

for d in (DATA_DIR, MEMORY_DIR, USER_PROFILES_DIR, LOGS_DIR, KNOWLEDGE_DIR, RESEARCH_OUTPUT_DIR, TRAINING_DATA_DIR, SOUL_TRAINING_DIR, VOICES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# LLM provider (xAI is default for backward compatibility)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "xai").strip().lower()

# xAI Grok
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE_URL = "https://api.x.ai/v1"
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")

# Mistral AI (OpenAI-compatible API)
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_BASE_URL = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-medium-latest")
MISTRAL_IMAGE_MODEL = os.getenv("MISTRAL_IMAGE_MODEL", "")

# Google Gemini (OpenAI-compatible API)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

# Ollama local models (OpenAI-compatible API at /v1)
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:12b")

# OpenRouter (OpenAI-compatible meta-router — access every provider via one API)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

# xAI image model
XAI_IMAGE_MODEL = os.getenv("XAI_IMAGE_MODEL", "grok-imagine-image")


def get_llm_provider() -> str:
    """Return normalized provider name: 'xai', 'openai', 'mistral', 'gemini', 'ollama', 'anthropic', or 'openrouter'."""
    if LLM_PROVIDER in {"openai", "mistral", "gemini", "ollama", "anthropic", "openrouter"}:
        return LLM_PROVIDER
    return "xai"


def get_chat_model() -> str:
    """Return active chat model for the selected provider."""
    provider = get_llm_provider()
    if provider == "openai":
        return OPENAI_MODEL
    if provider == "mistral":
        return MISTRAL_MODEL
    if provider == "gemini":
        return GEMINI_MODEL
    if provider == "ollama":
        return OLLAMA_MODEL
    if provider == "anthropic":
        return ANTHROPIC_MODEL
    if provider == "openrouter":
        return OPENROUTER_MODEL
    return XAI_MODEL


def get_api_key() -> str:
    """Return active API key for the selected provider."""
    provider = get_llm_provider()
    if provider == "openai":
        return OPENAI_API_KEY
    if provider == "mistral":
        return MISTRAL_API_KEY
    if provider == "gemini":
        return GEMINI_API_KEY
    if provider == "ollama":
        return OLLAMA_API_KEY
    if provider == "anthropic":
        return ANTHROPIC_API_KEY
    if provider == "openrouter":
        return OPENROUTER_API_KEY
    return XAI_API_KEY


def get_base_url() -> str:
    """Return active base URL for the selected provider."""
    provider = get_llm_provider()
    if provider == "openai":
        return OPENAI_BASE_URL
    if provider == "mistral":
        return MISTRAL_BASE_URL
    if provider == "gemini":
        return GEMINI_BASE_URL
    if provider == "ollama":
        return OLLAMA_BASE_URL
    if provider == "anthropic":
        return ANTHROPIC_BASE_URL
    if provider == "openrouter":
        return OPENROUTER_BASE_URL
    return XAI_BASE_URL


def get_api_key_env_name() -> str:
    """Return env var name for selected provider API key."""
    provider = get_llm_provider()
    if provider == "openai":
        return "OPENAI_API_KEY"
    if provider == "mistral":
        return "MISTRAL_API_KEY"
    if provider == "gemini":
        return "GEMINI_API_KEY"
    if provider == "ollama":
        return "OLLAMA_API_KEY"
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider == "openrouter":
        return "OPENROUTER_API_KEY"
    return "XAI_API_KEY"


def get_image_model() -> str:
    """Return active image model for the selected provider."""
    provider = get_llm_provider()
    if provider == "openai":
        return OPENAI_IMAGE_MODEL
    if provider == "mistral":
        return MISTRAL_IMAGE_MODEL
    return XAI_IMAGE_MODEL

# Voice
EDGE_TTS_VOICE = "en-GB-RyanNeural"  # British male - Ryan (fallback)
TTS_ENGINE = os.getenv("TTS_ENGINE", "edge").strip().lower()  # "lux" | "edge"
LUX_VOICE_REF = os.getenv("LUX_VOICE_REF", "edward").strip()  # name in data/voices/ or full path
LUX_DEVICE = os.getenv("LUX_DEVICE", "cpu").strip().lower()  # "cpu" | "cuda" (ROCm shim)
LUX_NUM_STEPS = int(os.getenv("LUX_NUM_STEPS", "4"))  # 3-4 best speed/quality tradeoff

# Web (0.0.0.0 = accessible from phone on local network)
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8765"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


# HTTPS for mic/camera on LAN IPs (browsers require secure context off localhost)
WEB_SSL = _env_bool("WEB_SSL", False)
WEB_SSL_CERT = Path(os.getenv("WEB_SSL_CERT", str(DATA_DIR / "certs" / "dev.crt"))).resolve()
WEB_SSL_KEY = Path(os.getenv("WEB_SSL_KEY", str(DATA_DIR / "certs" / "dev.key"))).resolve()

# Cursor CLI (escalation when Doctor Mode exhausts attempts)
CURSOR_CLI_CMD = os.getenv("CURSOR_CLI_CMD", "agent")
# Pass --trust on headless agent invocations (avoids interactive workspace trust prompt)
CURSOR_CLI_TRUST = _env_bool("CURSOR_CLI_TRUST", True)
CURSOR_API_KEY = os.getenv("CURSOR_API_KEY", "")

# Discord (bot + proactive outreach)
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
def normalize_discord_id(raw: str) -> str:
    """Strip non-digits (e.g. accidental ``531896743063846943_id`` in .env)."""
    return "".join(c for c in (raw or "") if c.isdigit())


DISCORD_OWNER_ID = normalize_discord_id(os.getenv("DISCORD_OWNER_ID", ""))

# Soul training base model (Hugging Face)
SOUL_BASE_MODEL = os.getenv("SOUL_BASE_MODEL", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")

