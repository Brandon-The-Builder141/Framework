"""
General-purpose reminders. Solen (or the Creator) can schedule a one-off
reminder for a specific time; `check_and_fire_reminders()` is polled from
the live background loop (`_background_thoughts_loop` in src/web/app.py)
and delivers anything due.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from config.settings import USER_PROFILES_DIR


def _reminders_path(user_id: str = "default") -> Path:
    return USER_PROFILES_DIR / user_id / "reminders.json"


def _load(user_id: str = "default") -> list[dict]:
    p = _reminders_path(user_id)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save(reminders: list[dict], user_id: str = "default") -> None:
    p = _reminders_path(user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(reminders, f, indent=2)


def create_reminder(text: str, remind_at: str, user_id: str = "default", channel: str = "discord") -> dict:
    """Schedule a one-off reminder.

    remind_at: ISO 8601 datetime, e.g. '2026-07-30T15:00:00'.
    channel: 'discord' (DM the owner) or 'web' (dashboard notification).
    """
    datetime.fromisoformat(remind_at)  # raises ValueError if malformed
    reminders = _load(user_id)
    reminder = {
        "id": str(uuid.uuid4())[:8],
        "text": text,
        "remind_at": remind_at,
        "channel": channel if channel in ("discord", "web") else "discord",
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }
    reminders.append(reminder)
    _save(reminders, user_id)
    return reminder


def list_reminders(user_id: str = "default", include_resolved: bool = False) -> list[dict]:
    reminders = _load(user_id)
    if include_resolved:
        return reminders
    return [r for r in reminders if r["status"] == "pending"]


def cancel_reminder(reminder_id: str, user_id: str = "default") -> bool:
    reminders = _load(user_id)
    for r in reminders:
        if r["id"] == reminder_id and r["status"] == "pending":
            r["status"] = "cancelled"
            _save(reminders, user_id)
            return True
    return False


def get_due_reminders(user_id: str = "default") -> list[dict]:
    now = datetime.now()
    due = []
    for r in _load(user_id):
        if r["status"] != "pending":
            continue
        try:
            when = datetime.fromisoformat(r["remind_at"])
        except ValueError:
            continue
        if when <= now:
            due.append(r)
    return due


def mark_reminder_sent(reminder_id: str, user_id: str = "default") -> None:
    reminders = _load(user_id)
    for r in reminders:
        if r["id"] == reminder_id:
            r["status"] = "sent"
            r["sent_at"] = datetime.now().isoformat()
    _save(reminders, user_id)


def _deliver_reminder(text: str, channel: str, trigger_key: str) -> None:
    content = f"Reminder: {text}"
    if channel == "web":
        from src.notifications import emit_notification

        emit_notification("reminder", "Reminder", content)
        return
    from config.settings import DISCORD_OWNER_ID
    from src.outreach import queue_outreach

    queue_outreach(
        channel="discord",
        content=content,
        target_user_id=DISCORD_OWNER_ID or None,
        source="reminder",
        trigger_key=trigger_key,
        is_direct=True,
    )


def check_and_fire_reminders(user_id: str = "default") -> list[str]:
    """Poll for due reminders and deliver them. Returns fired texts."""
    fired = []
    for r in get_due_reminders(user_id):
        try:
            _deliver_reminder(r["text"], r.get("channel", "discord"), trigger_key=f"reminder:{r['id']}")
            mark_reminder_sent(r["id"], user_id)
            fired.append(r["text"])
        except Exception:
            continue
    return fired
