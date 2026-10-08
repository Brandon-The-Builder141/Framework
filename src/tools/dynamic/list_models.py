"""Dynamic tool: list_models — list models for a specific backend or provider."""
from __future__ import annotations

import json

from src.backend_switching import bootstrap_backend_files, load_registry, load_state

TOOL_DEF = {
    "name": "list_models",
    "description": (
        "List models for a specific backend or provider, or all models grouped by provider. "
        "Pass backend_id as a provider name ('openai', 'xai', 'ollama') or a full backend id "
        "('xai/grok-4.3') to filter. Omit to get every model grouped by provider. "
        "Returns model name, tool-capable flag, cost tier, context window, and health status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "backend_id": {
                "type": "string",
                "description": (
                    "Provider name (e.g. 'openai') or full backend id (e.g. 'xai/grok-4.3'). "
                    "Omit to return all backends grouped by provider."
                ),
            },
        },
    },
}


async def run(backend_id: str | None = None) -> str:
    bootstrap_backend_files(user_id="default")
    entries = load_registry(user_id="default")
    state = load_state(user_id="default")

    active_id = str(state.get("active_backend", "")).strip()
    unhealthy: dict = state.get("unhealthy_backends") or {}

    if backend_id:
        q = backend_id.strip().lower()
        filtered = [
            e for e in entries
            if e.id.lower() == q
            or e.provider.lower() == q
            or e.id.lower().startswith(q + "/")
        ]
        if not filtered:
            return json.dumps({"error": f"No backends matched '{backend_id}'", "backends": []})
        result = [_entry_dict(e, active_id, unhealthy) for e in sorted(filtered, key=lambda x: x.priority)]
        return json.dumps(
            {"backend_id_filter": backend_id, "count": len(result), "backends": result},
            ensure_ascii=False,
            indent=2,
        )

    by_provider: dict[str, list[dict]] = {}
    for e in sorted(entries, key=lambda x: x.priority):
        by_provider.setdefault(e.provider, []).append(_entry_dict(e, active_id, unhealthy))

    return json.dumps(
        {"grouped_by_provider": by_provider, "total": len(entries)},
        ensure_ascii=False,
        indent=2,
    )


def _entry_dict(e, active_id: str, unhealthy: dict) -> dict:
    health_info = unhealthy.get(e.id)
    return {
        "id": e.id,
        "model": e.model,
        "display_name": e.display_name,
        "active": e.id == active_id,
        "enabled": e.enabled,
        "cost_tier": e.cost_tier,
        "quality_tier": e.quality_tier,
        "tool_capable": e.supports_tools,
        "supports_vision": e.supports_vision,
        "supports_reasoning": e.supports_reasoning,
        "context_window": e.context_window,
        "fallback_rank": e.fallback_rank,
        "health": "unhealthy" if health_info else "healthy",
        "health_reason": health_info.get("reason") if health_info else None,
    }
