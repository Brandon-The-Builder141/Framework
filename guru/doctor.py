"""Preflight checks before running Guru."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent


def run_doctor() -> int:
    ok = True
    print("=== Guru doctor ===\n")

    if sys.version_info < (3, 11):
        print("[WARN] Python 3.11+ recommended")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        print(f"[OK] ffmpeg: {ffmpeg}")
    else:
        print("[FAIL] ffmpeg not on PATH — install ffmpeg for voice")
        ok = False

    imports = [
        ("discord", "discord.py[voice]"),
        ("yt_dlp", "yt-dlp"),
        ("edge_tts", "edge-tts"),
        ("httpx", "httpx"),
        ("dotenv", "python-dotenv"),
    ]
    for mod, pkg in imports:
        try:
            __import__(mod)
            print(f"[OK] import {mod}")
        except ImportError:
            print(f"[FAIL] missing {pkg} — pip install -r guru/requirements.txt")
            ok = False

    from guru.env import GURU_DISCORD_BOT_TOKEN, GURU_OWNER_ID, OPENAI_API_KEY, OPENAI_MODEL

    if GURU_DISCORD_BOT_TOKEN:
        print(f"[OK] GURU_DISCORD_BOT_TOKEN set ({len(GURU_DISCORD_BOT_TOKEN)} chars)")
        try:
            client_id = GURU_DISCORD_BOT_TOKEN.split(".", 1)[0]
            perms = 36700160 + 1048576 + 2097152  # manage ch, connect, speak, send, view
            url = (
                f"https://discord.com/api/oauth2/authorize?client_id={client_id}"
                f"&permissions={perms}&scope=bot%20applications.commands"
            )
            print(f"[INFO] Invite URL:\n{url}")
        except Exception:
            pass
    else:
        print("[FAIL] GURU_DISCORD_BOT_TOKEN missing - copy guru/.env.example to guru/.env")
        ok = False

    if GURU_OWNER_ID:
        print(f"[OK] GURU_OWNER_ID={GURU_OWNER_ID}")
    else:
        print("[WARN] GURU_OWNER_ID unset — add your Discord user id to guru/.env")

    if OPENAI_API_KEY:
        print(f"[OK] LLM key set, model={OPENAI_MODEL}")
    else:
        print("[WARN] No OPENROUTER_API_KEY — Garth can only use /guru commands, not chat")

    from guru.config import load_config
    from guru.scripts_loader import list_scripts

    cfg = load_config()
    scripts = list_scripts()
    print(f"[OK] scripts: {', '.join(scripts) or '(none)'}")
    if cfg.get("voice_channel_id"):
        print(f"[OK] voice_channel_id={cfg['voice_channel_id']}")
    else:
        print("[INFO] voice_channel_id empty — run !guru setup in Discord")

    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print(f"[INFO] Create {env_path} from .env.example")

    print()
    if ok:
        print("Ready. Start with: python guru/main.py")
        return 0
    print("Fix failures above, then retry.")
    return 1


if __name__ == "__main__":
    if str(AGENT_ROOT) not in sys.path:
        sys.path.insert(0, str(AGENT_ROOT))
    raise SystemExit(run_doctor())
