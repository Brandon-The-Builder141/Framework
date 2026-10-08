"""Remove blank user input entries from memory files."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "profiles" / "default"


def is_blank_user(content: str) -> bool:
    c = (content or "").strip()
    if not c or c in ("User:", "User"):
        return True
    if c.startswith("User:") and not c[5:].strip():
        return True
    return False


def clean_episodic():
    path = DATA / "episodic.jsonl"
    if not path.exists():
        return 0, 0
    with open(path, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f]
    kept = []
    for line in lines:
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if is_blank_user(d.get("content", "")):
                continue
            kept.append(line)
        except json.JSONDecodeError:
            kept.append(line)
    with open(path, "w", encoding="utf-8") as f:
        for line in kept:
            f.write(line + "\n")
    return len(lines), len(kept)


def clean_short_term():
    path = DATA / "short_term.jsonl"
    if not path.exists():
        return 0, 0
    with open(path, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f]
    kept = []
    for line in lines:
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if is_blank_user(d.get("content", "")):
                continue
            kept.append(line)
        except json.JSONDecodeError:
            kept.append(line)
    with open(path, "w", encoding="utf-8") as f:
        for line in kept:
            f.write(line + "\n")
    return len(lines), len(kept)


if __name__ == "__main__":
    e_before, e_after = clean_episodic()
    s_before, s_after = clean_short_term()
    print(f"Episodic: {e_before} -> {e_after} (removed {e_before - e_after} blank)")
    print(f"Short-term: {s_before} -> {s_after} (removed {s_before - s_after} blank)")
