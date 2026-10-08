"""Dynamic tool: list_backends — enumerate all configured backend providers."""
from __future__ import annotations

import json

from src.backend_switching import bootstrap_backend_files, load_registry, load_state

TOOL_DEF = {
    "name": "list_backends",
    "description": (
        "List all configured backend providers and models with their current status. "
        "Returns provider, model, tool-capable flag, health status, active/fallback role, "
        "cost tier, and context window for every entry in the backend registry. "
        "Use when asked to 'pull up your providers', 'list backends', 'show available models', "
        "'what providers do you have', or whenever choosing which backend to switch to."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["json", "table"],
                "description": "Output format: 'json' (default) or 'table' (markdown).",
            },
            "enabled_only": {
                "type": "boolean",
                "description": "When true, omit disabled backends. Default: false.",
            },
        },
    },
}


async def run(format: str = "json", enabled_only: bool = False) -> str:
    bootstrap_backend_files(user_id="default")
    entries = load_registry(user_id="default")
    state = load_state(user_id="default")

    active_id = str(state.get("active_backend", "")).strip()
    life_support_id = str(state.get("life_support_backend", "")).strip()
    local_fallback_id = str(state.get("local_fallback_backend", "")).strip()
    unhealthy: dict = state.get("unhealthy_backends") or {}

    if enabled_only:
        entries = [e for e in entries if e.enabled]

    backends = []
    for e in sorted(entries, key=lambda x: x.priority):
        health_info = unhealthy.get(e.id)
        backends.append({
            "id": e.id,
            "provider": e.provider,
            "model": e.model,
            "display_name": e.display_name,
            "active": e.id == active_id,
            "enabled": e.enabled,
            "is_life_support": e.id == life_support_id,
            "is_local_fallback": e.id == local_fallback_id,
            "cost_tier": e.cost_tier,
            "quality_tier": e.quality_tier,
            "tool_capable": e.supports_tools,
            "supports_vision": e.supports_vision,
            "supports_reasoning": e.supports_reasoning,
            "context_window": e.context_window,
            "fallback_rank": e.fallback_rank,
            "health": "unhealthy" if health_info else "healthy",
            "health_reason": health_info.get("reason") if health_info else None,
        })

    result = {
        "summary": {
            "total": len(entries),
            "enabled": sum(1 for e in entries if e.enabled),
            "active": active_id,
            "life_support": life_support_id,
            "local_fallback": local_fallback_id,
        },
        "backends": backends,
    }

    if format == "table":
        return _render_table(result)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _render_table(data: dict) -> str:
    s = data["summary"]
    lines = [
        f"Active: `{s['active']}` | Life-support: `{s['life_support']}` | "
        f"Local fallback: `{s['local_fallback']}` | "
        f"Total: {s['total']} ({s['enabled']} enabled)",
        "",
        "| ID | Provider | Model | Role | Tools | Vision | Cost | Quality | Ctx | Rank | Health |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in data["backends"]:
        roles = []
        if b["active"]:
            roles.append("ACTIVE")
        if b["is_life_support"]:
            roles.append("LS")
        if b["is_local_fallback"]:
            roles.append("LOCAL")
        role_str = ",".join(roles) if roles else "-"
        ctx_str = f"{b['context_window'] // 1000}K" if b["context_window"] else "?"
        health_str = "DOWN" if b["health"] == "unhealthy" else "ok"
        lines.append(
            f"| `{b['id']}` | {b['provider']} | {b['model']} | {role_str} "
            f"| {'Y' if b['tool_capable'] else 'N'} "
            f"| {'Y' if b['supports_vision'] else 'N'} "
            f"| {b['cost_tier']} | {b['quality_tier']} | {ctx_str} "
            f"| {b['fallback_rank']} | {health_str} |"
        )
    return "\n".join(lines)
