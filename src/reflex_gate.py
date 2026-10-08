"""Reflex Gate — intercepts tool calls and gates them on user approval.

Flow:
  1. _run_tool_inner() calls check_gate(tool, args, reason) before execution.
  2. If safe/auto-approved: returns immediately (allowed=True).
  3. Otherwise: emits an "approval_request" SSE event to the UI,
     then awaits an asyncio.Event until the user responds via
     POST /api/reflex/respond or the timeout fires.
  4. resolve_gate(gate_id, decision, redirect_text) is called by the web
     handler to unblock the awaiting gate.

Interrupt:
  The user may call trigger_interrupt(text) at any point.  The next
  gate check (or the guard in _run_tool_inner) will see the flag and
  return an allowed=False result with the interrupt text so the agent
  can feed it back into its context.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from src import reflex_memory as _mem
from src.notifications import emit_notification


# ---------------------------------------------------------------------------
# Pending gate registry  {gate_id: (event, result_dict)}
# ---------------------------------------------------------------------------

_pending: dict[str, tuple[asyncio.Event, dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Interrupt state (module-level; single-agent deployment is fine)
# ---------------------------------------------------------------------------

_interrupt_event: asyncio.Event | None = None
_interrupt_text: str = ""


def _get_interrupt_event() -> asyncio.Event:
    global _interrupt_event
    if _interrupt_event is None:
        _interrupt_event = asyncio.Event()
    return _interrupt_event


def trigger_interrupt(text: str = "") -> None:
    """Signal mid-process interrupt from the UI or any caller."""
    global _interrupt_text
    _interrupt_text = text or ""
    _get_interrupt_event().set()


def reset_interrupt() -> None:
    global _interrupt_text
    _interrupt_text = ""
    _get_interrupt_event().clear()


def is_interrupted() -> bool:
    try:
        return _get_interrupt_event().is_set()
    except RuntimeError:
        return False


def get_interrupt_text() -> str:
    return _interrupt_text


# ---------------------------------------------------------------------------
# Gate check
# ---------------------------------------------------------------------------

# Timeout per risk tier (seconds)
_GATE_TIMEOUT: dict[str, float] = {
    "standard": 90.0,
    "high": 120.0,
}

# On timeout: auto-approve standard, auto-deny high-risk
_TIMEOUT_FALLBACK: dict[str, str] = {
    "standard": "approve",
    "high": "deny",
}


async def check_gate(
    tool: str,
    args: dict[str, Any],
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Decide whether a tool call is allowed to proceed.

    Returns a dict:
        allowed       bool   — proceed with the call
        auto          bool   — true if no user interaction was needed
        redirect_text str    — non-empty when user redirected
        warning       str|None — soft-warning from prior denials
        timed_out     bool
    """
    tier = _mem.get_risk_tier(tool)
    context_hint = _mem.build_context_hint(tool, args)
    gate_id = str(uuid.uuid4())[:12]

    # --- Interrupt check first ---
    if is_interrupted():
        txt = get_interrupt_text()
        reset_interrupt()
        return {
            "allowed": False,
            "auto": False,
            "redirect_text": txt,
            "warning": None,
            "timed_out": False,
            "interrupted": True,
        }

    # --- Auto-approve check ---
    auto_ok, auto_reason = _mem.should_auto_approve(tool, context_hint)
    soft_warn = _mem.get_soft_warning(tool, context_hint)

    if auto_ok:
        _mem.record_decision(
            gate_id=gate_id,
            tool=tool,
            context_hint=context_hint,
            reason=reason,
            decision="approve",
            auto=True,
        )
        return {
            "allowed": True,
            "auto": True,
            "redirect_text": "",
            "warning": soft_warn,
            "timed_out": False,
        }

    # --- Needs user review ---
    timeout = _GATE_TIMEOUT.get(tier, 90.0)
    event: asyncio.Event = asyncio.Event()
    result: dict[str, Any] = {}
    _pending[gate_id] = (event, result)

    args_preview = _args_preview(args)
    emit_notification(
        "approval_request",
        f"Approval needed: {tool}",
        reason or f"Agent wants to call {tool}",
        meta={
            "gate_id": gate_id,
            "tool": tool,
            "args_preview": args_preview,
            "reason": reason or f"Agent intends to call {tool}",
            "context_hint": context_hint,
            "tier": tier,
            "soft_warning": soft_warn,
            "auto_reason": auto_reason,
        },
    )

    timed_out = False
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        fallback = _TIMEOUT_FALLBACK.get(tier, "deny")
        result["decision"] = fallback
        result["redirect_text"] = ""
        # Notify UI that the gate timed out
        emit_notification(
            "gate_resolved",
            f"Gate timed out: {tool}",
            f"Auto-{fallback} after {int(timeout)}s timeout.",
            meta={"gate_id": gate_id, "decision": fallback, "timed_out": True},
        )
    finally:
        _pending.pop(gate_id, None)

    decision = result.get("decision", "deny")
    redirect_text = result.get("redirect_text", "")

    _mem.record_decision(
        gate_id=gate_id,
        tool=tool,
        context_hint=context_hint,
        reason=reason,
        decision=decision,
        redirect_text=redirect_text,
        auto=False,
    )

    if not timed_out:
        emit_notification(
            "gate_resolved",
            f"Gate resolved: {tool}",
            f"Decision: {decision}",
            meta={"gate_id": gate_id, "decision": decision, "timed_out": False},
        )

    return {
        "allowed": decision == "approve",
        "auto": False,
        "redirect_text": redirect_text,
        "warning": soft_warn,
        "timed_out": timed_out,
    }


def resolve_gate(gate_id: str, decision: str, redirect_text: str = "") -> bool:
    """Called by the API endpoint when the user submits a decision."""
    entry = _pending.get(gate_id)
    if not entry:
        return False
    event, result = entry
    result["decision"] = decision
    result["redirect_text"] = redirect_text or ""
    event.set()
    return True


def get_pending_gates() -> list[dict[str, Any]]:
    """Return gate IDs currently waiting for a decision."""
    return [{"gate_id": gid} for gid in _pending]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _args_preview(args: dict[str, Any]) -> dict[str, str]:
    preview: dict[str, str] = {}
    for k, v in args.items():
        if v is None:
            continue
        s = str(v)
        if k == "content" and len(s) > 140:
            s = s[:140] + f"… ({len(str(v))} chars total)"
        elif len(s) > 220:
            s = s[:220] + "…"
        preview[k] = s
    return preview
