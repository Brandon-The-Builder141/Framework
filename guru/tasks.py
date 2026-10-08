"""Pending Guru actions in tasks.json (hardening / audit)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from guru.logger import log_action
from guru.paths import TASKS_PATH


def _load() -> dict[str, Any]:
    if not TASKS_PATH.exists():
        return {"pending": [], "completed": []}
    try:
        data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"pending": [], "completed": []}


def _save(data: dict[str, Any]) -> None:
    TASKS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_pending(
    *,
    user_id: str,
    action: str,
    detail: str = "",
    notify_on_complete: bool = True,
) -> str:
    data = _load()
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    entry = {
        "id": task_id,
        "user_id": str(user_id),
        "action": action,
        "detail": detail,
        "notify_on_complete": notify_on_complete,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    pending = list(data.get("pending") or [])
    pending.append(entry)
    data["pending"] = pending
    _save(data)
    log_action("task_pending", f"{task_id} {action}")
    return task_id


def complete_pending(task_id: str, result: str = "ok") -> dict[str, Any] | None:
    data = _load()
    pending = list(data.get("pending") or [])
    found = None
    rest = []
    for t in pending:
        if t.get("id") == task_id:
            found = t
        else:
            rest.append(t)
    if not found:
        return None
    found["completed_at"] = datetime.now(timezone.utc).isoformat()
    found["result"] = result
    data["pending"] = rest
    completed = list(data.get("completed") or [])
    completed.append(found)
    data["completed"] = completed[-200:]
    _save(data)
    log_action("task_complete", f"{task_id} {result}")
    return found


async def notify_task_complete(bot: "Any", task: dict[str, Any], message: str) -> None:
    if not task.get("notify_on_complete"):
        return
    uid = task.get("user_id")
    if not uid:
        return
    try:
        user = await bot.fetch_user(int(uid))
        await user.send(message[:1900])
    except Exception as e:
        log_action("task_notify_failed", str(e), level="error")
