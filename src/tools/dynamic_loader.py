"""
Load dynamic tools from src/tools/dynamic/.
Each .py file must define TOOL_DEF and async def run(**kwargs).
"""
import importlib.util
import sys
from pathlib import Path

from src.tools import dynamic_loader as _this

DYNAMIC_DIR = Path(_this.__file__).resolve().parent / "dynamic"

# (filename, reason) for files in DYNAMIC_DIR that failed to load as a tool
# on the most recent load_dynamic_tools() call. Surfaced via get_tool_queue
# / doctor mode so broken self-authored tools don't fail silently.
_last_broken: list[tuple[str, str]] = []


def load_dynamic_tools() -> tuple[list[dict], dict[str, callable]]:
    """
    Load all tools from dynamic/. Returns (tool_definitions, runners).
    runners: {tool_name: async_run_function}
    """
    global _last_broken
    definitions = []
    runners = {}
    broken: list[tuple[str, str]] = []

    if not DYNAMIC_DIR.exists():
        _last_broken = broken
        return definitions, runners

    for path in DYNAMIC_DIR.glob("*.py"):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"dynamic_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)

            if not hasattr(mod, "TOOL_DEF") or not hasattr(mod, "run"):
                broken.append((path.name, "missing TOOL_DEF and/or run()"))
                continue

            td = mod.TOOL_DEF
            name = td.get("name") or path.stem
            definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": td.get("description", ""),
                    "parameters": td.get("parameters", {"type": "object", "properties": {}}),
                },
            })
            runners[name] = mod.run
        except Exception as e:
            broken.append((path.name, f"{type(e).__name__}: {e}"))
            continue

    if broken:
        from src.logging_config import log_error

        for filename, reason in broken:
            log_error("dynamic_tool_load", f"{filename}: {reason}")

    _last_broken = broken
    return definitions, runners


def get_broken_dynamic_tools() -> list[tuple[str, str]]:
    """(filename, reason) pairs for dynamic tool files that failed to load, from the last load_dynamic_tools() call."""
    return list(_last_broken)
