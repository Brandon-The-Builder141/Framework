from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def due_slot(now, cfg):
    local = now.astimezone(ZoneInfo(cfg["timezone"]))
    # Five-minute startup/reconnect grace, no backlog of old prayers.
    if local.hour in cfg["prayer_hours"] and local.minute < 5:
        return f"{local.date().isoformat()}T{local.hour:02}:00"
    return None


def next_prayer(now, cfg):
    local = now.astimezone(ZoneInfo(cfg["timezone"]))
    candidates = [local.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(days=d)
                  for d in (0, 1) for h in cfg["prayer_hours"]]
    return min(x for x in candidates if x > local)
