"""Per-user chat history for Garth."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guru.paths import GURU_ROOT

MEMORY_DIR = GURU_ROOT / "garth_memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
MAX_MESSAGES = 40


def _path(user_id: str) -> Path:
    return MEMORY_DIR / f"{user_id}.json"


def load_history(user_id: str) -> list[dict[str, str]]:
    p = _path(user_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        msgs = data.get("messages") if isinstance(data, dict) else []
        return [m for m in msgs if isinstance(m, dict) and m.get("role") and m.get("content")][
            -MAX_MESSAGES:
        ]
    except (json.JSONDecodeError, OSError):
        return []


def append_turn(user_id: str, user_text: str, assistant_text: str) -> None:
    msgs = load_history(user_id)
    msgs.append({"role": "user", "content": user_text[:2000]})
    msgs.append({"role": "assistant", "content": assistant_text[:2000]})
    msgs = msgs[-MAX_MESSAGES:]
    p = _path(user_id)
    p.write_text(
        json.dumps(
            {
                "user_id": user_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "messages": msgs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def add_profile_note(user_id: str, note: str) -> None:
    from guru.profile import load_profile, save_profile

    prof = load_profile(user_id)
    notes = list(prof.get("notes") or [])
    notes.append(note.strip()[:300])
    prof["notes"] = notes[-30:]
    save_profile(user_id, prof)
