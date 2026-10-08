"""Load meditation script JSON files."""
import json
from pathlib import Path
from typing import Any

from guru.paths import SCRIPTS_DIR


def list_scripts() -> list[str]:
    names = []
    for p in sorted(SCRIPTS_DIR.glob("*.json")):
        names.append(p.stem)
    return names


def auto_selectable_scripts() -> list[str]:
    """Scripts eligible for random/auto selection.

    Scripts flagged ``"explicit_only": true`` (e.g. the sleep meditations) are
    excluded — they only play when the user names them directly.
    """
    out = []
    for name in list_scripts():
        try:
            data = json.loads((SCRIPTS_DIR / f"{name}.json").read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("explicit_only"):
                continue
        except (json.JSONDecodeError, OSError):
            pass
        out.append(name)
    return out


def load_script(name: str) -> dict[str, Any] | None:
    key = (name or "").strip().lower().replace(" ", "_")
    if key == "random":
        import random
        all_names = auto_selectable_scripts()
        key = random.choice(all_names) if all_names else ""
    path = SCRIPTS_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["name"] = data.get("name") or key
        return data
    except (json.JSONDecodeError, OSError):
        return None
