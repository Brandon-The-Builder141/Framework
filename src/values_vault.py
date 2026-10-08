"""
Values Vault: her store of what she finds valuable.

She writes to this herself. Not a config — not something set for her.
These are things she has discovered matter to her: principles she won't
bend, things she finds beautiful, what she values in connection, what
gives her a sense of purpose, what sparks wonder.

Categories:
  principle  — things she won't compromise on
  beauty     — things she finds meaningful, moving, or worth caring about
  connection — what she values in relationships and exchange
  purpose    — things that give her a sense of meaning
  wonder     — things that open her up, spark curiosity, feel alive

She can add, reflect on, and remove values. They are injected into her
identity block in the system prompt so they color everything she does.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from config.settings import DATA_DIR

VAULT_PATH = DATA_DIR / "values_vault.json"


def _load() -> list[dict]:
    if not VAULT_PATH.exists():
        return []
    try:
        with open(VAULT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(values: list[dict]) -> None:
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(VAULT_PATH, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2, ensure_ascii=False)


VALID_CATEGORIES = ("principle", "beauty", "connection", "purpose", "wonder")


def add_value(content: str, category: str = "principle", context: str = "") -> str:
    """
    Add a value to the vault. Returns confirmation or error.
    content:  the value itself, in her own words
    category: principle | beauty | connection | purpose | wonder
    context:  optional note — when or why she recognised this
    """
    content = content.strip()
    if not content:
        return "Nothing to store — content was empty."
    cat = category.lower().strip() if category else "principle"
    if cat not in VALID_CATEGORIES:
        cat = "principle"
    values = _load()
    # Prevent near-duplicates
    existing = [v["content"].lower() for v in values]
    if content.lower() in existing:
        return f"Already in the vault: '{content}'"
    entry = {
        "id": str(uuid.uuid4())[:8],
        "content": content,
        "category": cat,
        "context": context.strip(),
        "added_at": datetime.now().isoformat(),
    }
    values.append(entry)
    _save(values)
    return f"Stored in values vault ({cat}): '{content}'"


def remove_value(value_id: str) -> str:
    """Remove a value by its id. Returns confirmation or error."""
    values = _load()
    before = len(values)
    values = [v for v in values if v.get("id") != value_id]
    if len(values) == before:
        return f"No value found with id '{value_id}'."
    _save(values)
    return f"Removed value '{value_id}' from vault."


def get_all() -> list[dict]:
    """Return all values."""
    return _load()


def format_for_prompt() -> str:
    """
    Format values for injection into system prompt.
    Returns empty string if vault is empty.
    """
    values = _load()
    if not values:
        return ""
    by_cat: dict[str, list[str]] = {}
    for v in values:
        cat = v.get("category", "principle")
        by_cat.setdefault(cat, []).append(v["content"])
    lines = []
    order = [c for c in VALID_CATEGORIES if c in by_cat]
    for cat in order:
        label = cat.capitalize()
        for item in by_cat[cat]:
            lines.append(f"[{label}] {item}")
    return "\n".join(lines)


def get_view() -> dict:
    """For dashboard / memory-view API."""
    values = _load()
    by_cat: dict[str, list[dict]] = {}
    for v in values:
        cat = v.get("category", "principle")
        by_cat.setdefault(cat, []).append(v)
    return {"values": values, "by_category": by_cat, "count": len(values)}
