"""Timestamped Guru action logs."""
from datetime import datetime, timezone

from guru.paths import LOGS_DIR


def log_action(action: str, detail: str = "", *, level: str = "info") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] [{level}] {action}"
    if detail:
        line += f" | {detail}"
    path = LOGS_DIR / f"guru_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
