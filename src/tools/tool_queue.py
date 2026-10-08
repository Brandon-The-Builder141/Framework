"""
Tool queue: suggested → approved → implemented.
Agent suggests tools, user approves, agent implements.
"""
import json
import uuid
from pathlib import Path

from config.settings import DATA_DIR

QUEUE_PATH = DATA_DIR / "tool_queue.json"
DYNAMIC_DIR = Path(__file__).resolve().parent / "dynamic"


def _load() -> dict:
    if not QUEUE_PATH.exists():
        return {"suggested": [], "approved": [], "implemented": []}
    with open(QUEUE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def add_suggested_tools(tools: list[dict]) -> str:
    """Add tool suggestions. Each: {name, description, parameters, reason}"""
    data = _load()
    for t in tools:
        t["id"] = str(uuid.uuid4())[:8]
        t["status"] = "suggested"
        data["suggested"].append(t)
    _save(data)
    return f"Added {len(tools)} suggestion(s). IDs: {', '.join(x['id'] for x in tools)}"


def get_queue() -> dict:
    data = _load()
    from src.tools.dynamic_loader import load_dynamic_tools, get_broken_dynamic_tools

    load_dynamic_tools()  # refresh the broken-file scan
    broken = get_broken_dynamic_tools()
    if broken:
        data["broken_files"] = [
            {"file": name, "reason": reason} for name, reason in broken
        ]
    return data


def approve_tool(tool_id: str) -> str:
    """Move tool from suggested to approved."""
    data = _load()
    for i, t in enumerate(data["suggested"]):
        if t.get("id") == tool_id:
            data["suggested"].pop(i)
            t["status"] = "approved"
            data["approved"].append(t)
            _save(data)
            return f"Approved: {t.get('name', tool_id)}"
    return f"Tool {tool_id} not found in suggested"


def reject_tool(tool_id: str) -> str:
    data = _load()
    for i, t in enumerate(data["suggested"]):
        if t.get("id") == tool_id:
            data["suggested"].pop(i)
            _save(data)
            return f"Rejected: {t.get('name', tool_id)}"
    return f"Tool {tool_id} not found"


def _validate_dynamic_tool_file(file_path: str) -> str | None:
    """Return an error string if file_path doesn't satisfy the dynamic tool contract, else None."""
    import importlib.util

    path = Path(file_path)
    if not path.is_absolute():
        path = DYNAMIC_DIR / path.name
    if not path.exists():
        return f"File not found: {path}"
    if path.resolve().parent != DYNAMIC_DIR.resolve():
        return f"File must live in {DYNAMIC_DIR}, got {path.parent}"
    try:
        spec = importlib.util.spec_from_file_location(f"validate_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return f"File failed to import: {type(e).__name__}: {e}"
    if not hasattr(mod, "TOOL_DEF"):
        return "File is missing module-level TOOL_DEF = {...}"
    if not hasattr(mod, "run"):
        return "File is missing async def run(**kwargs)"
    return None


def mark_implemented(tool_id: str, file_path: str = "") -> str:
    """Move tool from approved to implemented. Validates file_path against the
    dynamic tool contract (TOOL_DEF + async run()) first — a tool cannot be
    marked implemented if it would silently fail to load."""
    if not file_path:
        return "file_path is required so the tool can be validated before it's marked implemented."
    error = _validate_dynamic_tool_file(file_path)
    if error:
        return f"NOT marked implemented — {error}. Fix the file and call mark_tool_implemented again."
    data = _load()
    for i, t in enumerate(data["approved"]):
        if t.get("id") == tool_id:
            data["approved"].pop(i)
            t["status"] = "implemented"
            t["file_path"] = file_path
            data["implemented"].append(t)
            _save(data)
            return f"Marked implemented: {t.get('name', tool_id)} (validated, will load on next tool call)"
    return f"Tool {tool_id} not found in approved"


def get_next_approved() -> dict | None:
    """Get first approved tool for implementation."""
    data = _load()
    return data["approved"][0] if data["approved"] else None
