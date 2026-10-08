from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as pretty-printed JSON to *path* atomically.

    Writes to a sibling `.tmp` file, fsyncs, then renames so a crash
    mid-write cannot leave a corrupt file.

    Example:
        >>> import tempfile, pathlib, json
        >>> p = pathlib.Path(tempfile.mktemp(suffix=".json"))
        >>> atomic_write_json(p, {"ok": True})
        >>> json.loads(p.read_text())
        {'ok': True}
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    """Load JSON from *path*, returning *default* if the file is missing or corrupt.

    Example:
        >>> import pathlib
        >>> load_json(pathlib.Path("nonexistent_file_xyz.json"), [])
        []
    """
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def append_jsonl(path: Path, record: dict) -> None:
    """Append *record* as one JSON line to *path*, creating parent dirs as needed.

    Example:
        >>> import tempfile, pathlib, json
        >>> p = pathlib.Path(tempfile.mktemp(suffix=".jsonl"))
        >>> append_jsonl(p, {"event": "test"})
        >>> json.loads(p.read_text().strip())
        {'event': 'test'}
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
