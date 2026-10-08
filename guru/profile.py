"""guru_profile.json — preferences, vibes, ratings."""
import json
from typing import Any

from guru.paths import PROFILE_PATH


def _default_profile() -> dict[str, Any]:
    return {
        "preferred_length": "medium",
        "favorite_vibes": ["earthy", "calm"],
        "banter_lines": ["Alright, let's get cozy, Brandon!"],
        "mood": "calm",
        "sessions": [],
        "notes": [],
    }


def load_profile(user_id: str) -> dict[str, Any]:
    root: dict[str, Any] = _default_profile()
    if PROFILE_PATH.exists():
        try:
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if "users" in data and isinstance(data["users"], dict):
                    root = {**_default_profile(), **data.get("users", {}).get(str(user_id), {})}
                else:
                    root = {**_default_profile(), **data}
        except (json.JSONDecodeError, OSError):
            pass
    return root


def save_profile(user_id: str, profile: dict[str, Any]) -> None:
    data: dict[str, Any] = {"users": {}}
    if PROFILE_PATH.exists():
        try:
            existing = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and "users" in existing:
                data = existing
            elif isinstance(existing, dict):
                data["users"]["default"] = existing
        except (json.JSONDecodeError, OSError):
            pass
    if "users" not in data or not isinstance(data["users"], dict):
        data["users"] = {}
    data["users"][str(user_id)] = profile
    PROFILE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_session_rating(
    user_id: str,
    *,
    script_name: str,
    rating: int,
    feedback: str = "",
) -> dict[str, Any]:
    profile = load_profile(user_id)
    rating = max(1, min(5, int(rating)))
    sessions = list(profile.get("sessions") or [])
    sessions.append(
        {
            "script": script_name,
            "rating": rating,
            "feedback": (feedback or "").strip()[:500],
        }
    )
    profile["sessions"] = sessions[-50:]
    if rating >= 4:
        profile["preferred_length"] = profile.get("preferred_length") or "medium"
    elif rating <= 2:
        profile["preferred_length"] = "short"
    save_profile(user_id, profile)
    return profile


def pick_script_for_profile(available: list[str], profile: dict[str, Any]) -> str:
    import random

    from guru.scripts_loader import auto_selectable_scripts

    # Only auto-pick from scripts that aren't explicit-only (e.g. sleep ones
    # never surface unless the user names them directly).
    selectable = set(auto_selectable_scripts())
    pool = [s for s in available if s in selectable]
    if not pool:
        return ""
    pref = (profile.get("preferred_length") or "medium").lower()
    by_len = {
        "box_breathing": "short",
        "loving_kindness": "medium",
        "body_scan": "long",
    }
    if pref == "short":
        short = [s for s in pool if by_len.get(s) == "short"]
        if short:
            return random.choice(short)
    if pref == "long":
        long = [s for s in pool if by_len.get(s) == "long"]
        if long:
            return random.choice(long)
    return random.choice(pool)


def banter_line(profile: dict[str, Any], mood: str) -> str:
    lines = list(profile.get("banter_lines") or [])
    if mood == "playful" and lines:
        import random
        return random.choice(lines)
    vibes = ", ".join(profile.get("favorite_vibes") or ["calm"])
    return f"Settle in — leaning into a {vibes} vibe today."
