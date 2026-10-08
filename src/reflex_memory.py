"""Reflex approval gate memory — persistent store for tool-call approval patterns.

Every gate decision (approve / deny / redirect) is logged here.
Patterns are keyed on tool + normalised context so similar future
requests can be matched and auto-approved / soft-warned / blocked.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Risk tiers
# ---------------------------------------------------------------------------

SAFE_TOOLS: frozenset[str] = frozenset([
    "read_file", "verify_file_exists", "list_dir", "get_system_info",
    "search_web", "search_huggingface", "search_github",
    "list_artifacts", "get_artifact", "search_memory", "recall",
    "get_contacts", "get_schedule", "list_schedules",
    "read_knowledge", "search_knowledge", "list_knowledge_topics",
    "get_image_usage", "get_recent_images", "get_decision_layer_stats",
    "read_values_vault", "get_website_status", "get_proactive_outreach_status",
    "subagent_status", "get_subagent_output", "get_next_dag_step",
    "is_process_running", "list_processes",
])

HIGH_RISK_TOOLS: frozenset[str] = frozenset([
    "run_command", "spawn_subagent",
    "send_discord_message", "send_discord_attachment", "post_to_channel",
    "send_proactive_message", "generate_image", "stop_all_subagents",
])

# Approval count required before auto-approve engages
AUTO_APPROVE_THRESHOLD: dict[str, int] = {
    "safe": 0,       # never needs a threshold — always safe
    "standard": 2,   # approve twice → auto
    "high": 5,       # approve five times → auto
}

# Denial count before a pattern is soft-blocked (always needs review)
SOFT_BLOCK_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().isoformat()


def _store_path() -> Path:
    try:
        import config.settings
        return config.settings.USER_PROFILES_DIR / "default" / "reflex_memory.json"
    except Exception:
        return Path("data/profiles/default/reflex_memory.json")


def get_risk_tier(tool: str) -> str:
    if tool in SAFE_TOOLS:
        return "safe"
    if tool in HIGH_RISK_TOOLS:
        return "high"
    return "standard"


def build_context_hint(tool: str, args: dict[str, Any]) -> str:
    """Return a short normalised string that groups similar calls together.

    The hint is used as the stable key for pattern matching, so it must be
    broad enough to match a *class* of actions — not a single unique call.
    """
    if tool in ("write_file", "smart_write_file", "edit_artifact_section",
                "rollback_artifact", "read_file", "verify_file_exists"):
        raw = str(args.get("path") or args.get("identifier") or "")
        if raw:
            p = Path(raw.replace("\\", "/"))
            ext = p.suffix.lower() or "noext"
            parents = list(p.parts)
            dir_hint = "/".join(parents[-3:-1]) if len(parents) >= 3 else str(p.parent)
            return f"{tool}|ext={ext}|dir={dir_hint[-60:]}"
        return tool

    if tool == "run_command":
        cmd = str(args.get("cmd") or "").strip()
        tokens = cmd.split()[:2]
        return f"{tool}|{' '.join(tokens)[:50]}"

    if tool in ("send_discord_message", "send_discord_attachment",
                "post_to_channel", "send_proactive_message"):
        target = (
            args.get("target_channel_id")
            or args.get("target_user_id")
            or args.get("channel")
            or "any"
        )
        return f"{tool}|{str(target)[:24]}"

    if tool == "spawn_subagent":
        task = str(args.get("task") or "").strip()
        tokens = task.split()[:3]
        return f"{tool}|{' '.join(tokens)[:40]}"

    if tool == "generate_image":
        prompt = str(args.get("prompt") or "").strip()
        tokens = prompt.split()[:4]
        return f"{tool}|{' '.join(tokens)[:40]}"

    if tool in ("search_web", "search_huggingface", "search_github"):
        query = str(args.get("query") or "").strip()
        tokens = query.split()[:3]
        return f"{tool}|{' '.join(tokens)[:40]}"

    return tool


def _pattern_key(tool: str, context_hint: str) -> str:
    sig = f"{tool}::{context_hint[:150].lower()}"
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReflexDecision:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    gate_id: str = ""
    tool: str = ""
    context_hint: str = ""
    reason: str = ""
    decision: str = ""        # approve | deny | redirect
    redirect_text: str = ""
    auto: bool = False
    pattern_key: str = ""
    timestamp: str = field(default_factory=_now)


@dataclass
class ReflexPattern:
    key: str = ""
    tool: str = ""
    context_hint: str = ""
    tier: str = "standard"
    approvals: int = 0
    denials: int = 0
    redirects: int = 0
    last_decision: str = ""
    last_redirect_text: str = ""
    auto_approved: bool = False
    soft_blocked: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load() -> dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"patterns": {}, "decisions": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"patterns": {}, "decisions": []}


def _save(data: dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data["_updated"] = _now()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def should_auto_approve(tool: str, context_hint: str) -> tuple[bool, str]:
    """Return (can_auto_approve, reason_string)."""
    tier = get_risk_tier(tool)
    if tier == "safe":
        return True, "safe tool — no gate needed"

    pkey = _pattern_key(tool, context_hint)
    data = _load()
    raw = data["patterns"].get(pkey)
    if not raw:
        return False, "first time seeing this action"

    pattern = ReflexPattern(**raw)

    if pattern.soft_blocked:
        return False, f"soft-blocked after {pattern.denials} denial(s)"

    threshold = AUTO_APPROVE_THRESHOLD.get(tier, 2)
    if pattern.auto_approved and pattern.denials == 0:
        return True, f"auto-approved ({pattern.approvals}/{threshold} approvals)"

    remaining = max(0, threshold - pattern.approvals)
    return False, f"needs {remaining} more approval(s) before auto-approve"


def get_soft_warning(tool: str, context_hint: str) -> str | None:
    """Return a warning string if this pattern has prior denials/redirects."""
    pkey = _pattern_key(tool, context_hint)
    data = _load()
    raw = data["patterns"].get(pkey)
    if not raw:
        return None
    p = ReflexPattern(**raw)
    parts: list[str] = []
    if p.denials:
        parts.append(f"{p.denials} prior denial(s)")
    if p.redirects:
        parts.append(f"{p.redirects} prior redirect(s)")
        if p.last_redirect_text:
            parts.append(f'last note: "{p.last_redirect_text[:80]}"')
    return ("⚠ " + "; ".join(parts)) if parts else None


def record_decision(
    *,
    gate_id: str,
    tool: str,
    context_hint: str,
    reason: str,
    decision: str,
    redirect_text: str = "",
    auto: bool = False,
) -> ReflexPattern:
    tier = get_risk_tier(tool)
    pkey = _pattern_key(tool, context_hint)
    data = _load()
    raw = data["patterns"].get(pkey, {})

    if raw:
        pattern = ReflexPattern(**raw)
    else:
        pattern = ReflexPattern(
            key=pkey,
            tool=tool,
            context_hint=context_hint[:200],
            tier=tier,
            created_at=_now(),
        )

    now = _now()
    if decision == "approve":
        pattern.approvals += 1
    elif decision == "deny":
        pattern.denials += 1
    elif decision == "redirect":
        pattern.redirects += 1
        if redirect_text:
            pattern.last_redirect_text = redirect_text[:200]

    pattern.last_decision = decision
    pattern.updated_at = now

    threshold = AUTO_APPROVE_THRESHOLD.get(tier, 2)
    pattern.auto_approved = (pattern.approvals >= threshold and pattern.denials == 0)
    pattern.soft_blocked = (pattern.denials >= SOFT_BLOCK_THRESHOLD)

    data["patterns"][pkey] = asdict(pattern)

    dec = ReflexDecision(
        gate_id=gate_id,
        tool=tool,
        context_hint=context_hint[:200],
        reason=reason[:500],
        decision=decision,
        redirect_text=redirect_text[:400],
        auto=auto,
        pattern_key=pkey,
    )
    decisions: list[dict] = data.get("decisions", [])
    decisions.append(asdict(dec))
    if len(decisions) > 500:
        decisions = decisions[-500:]
    data["decisions"] = decisions

    _save(data)
    return pattern


def get_recent_decisions(limit: int = 50) -> list[dict]:
    data = _load()
    return list(reversed(data.get("decisions", [])[-limit:]))


def get_all_patterns() -> list[dict]:
    data = _load()
    return sorted(
        data.get("patterns", {}).values(),
        key=lambda p: p.get("updated_at", ""),
        reverse=True,
    )


def reset_pattern(pattern_key: str) -> bool:
    data = _load()
    if pattern_key in data.get("patterns", {}):
        del data["patterns"][pattern_key]
        _save(data)
        return True
    return False
