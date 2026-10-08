from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from ._embeddings import embed
from ._memory import atomic_write_json, load_json, append_jsonl, now_iso
from ._scoring import (
    score_candidates,
    message_hash,
    THRESHOLD_HIGH,
    THRESHOLD_MEDIUM,
)
from ._types import Decision

logger = logging.getLogger("decision_layer")

# Error string → category, evaluated in order (first match wins).
_ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"wrong.?tool|not.?a.?valid.?tool|no.?such.?tool|invalid.?tool", "wrong_tool"),
    (r"director|path|no.?such.?file|not.?found|does.?not.?exist", "wrong_directory"),
    (r"param|argument|missing.?field|invalid.?field|required.?field|bad.?arg", "wrong_param"),
    (r"timeout|timed.?out", "timeout"),
    (r"exception|traceback|error|crash|fail", "exception"),
]


def _categorize_error(error: str) -> str:
    lower = error.lower()
    for pattern, category in _ERROR_PATTERNS:
        if re.search(pattern, lower):
            return category
    return "other"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class DecisionLayer:
    """Learns which tool to call from a user message, improving over time.

    All state is persisted in human-readable JSON files under *memory_dir* so
    every decision can be inspected without running any code.

    Example:
        >>> import tempfile
        >>> dl = DecisionLayer(memory_dir=tempfile.mkdtemp())
        >>> dl.predict("search the web").action  # cold start
        'no_tool'
        >>> dl.record_success("search the web", "web_search")
        >>> dl.predict("look up recent news").tool
        'web_search'
    """

    def __init__(self, memory_dir: str = "data/decision_layer/") -> None:
        self._dir = Path(memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

        self._success_path = self._dir / "success_memory.json"
        self._failure_path = self._dir / "failure_memory.json"
        self._no_tool_path = self._dir / "no_tool_memory.json"
        self._log_path = self._dir / "prediction_log.jsonl"
        self._stats_path = self._dir / "tool_stats.json"

        # Thin in-memory map for linking prediction → outcome in the log.
        # normalized_message → prediction_id of the most recent predict() call.
        self._pending: dict[str, str] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def predict(self, message: str, context: dict | None = None) -> Decision:
        """Return a routing Decision for *message*.

        Args:
            message: Raw user message text.
            context: Optional dict. Recognised keys:
                - available_tools (list[str]): only these tools may be returned.
                - recent_tool_calls (list[dict]): last N calls for loop avoidance.
                - current_project, channel, tier: logged but not used for scoring.

        Returns:
            Decision with action ("use_tool"|"no_tool"), tool name, confidence,
            label ("low"|"medium"|"high"), reason, and top-3 candidates.

        Example:
            >>> import tempfile
            >>> dl = DecisionLayer(tempfile.mkdtemp())
            >>> dl.predict("hi there").action
            'no_tool'
        """
        ctx = context or {}
        available_tools: list[str] | None = ctx.get("available_tools")
        recent_tool_calls: list[dict] = ctx.get("recent_tool_calls", [])

        normalized = _normalize(message)
        msg_hash = message_hash(normalized)
        embedding = embed(normalized)

        success_mem: list[dict] = load_json(self._success_path, [])
        failure_mem: list[dict] = load_json(self._failure_path, [])
        tool_stats: dict[str, Any] = load_json(self._stats_path, {})

        pred_id = str(uuid.uuid4())
        self._pending[normalized] = pred_id

        # ── Cold start ────────────────────────────────────────────────────────
        if not success_mem:
            decision = Decision(
                action="no_tool",
                tool=None,
                confidence=0.0,
                confidence_label="low",
                reason="cold start — no learned examples yet",
                candidates=[],
            )
            self._log_prediction(pred_id, normalized, msg_hash, decision, ctx)
            logger.debug("predict cold-start: '%s'", normalized[:80])
            return decision

        candidates = score_candidates(
            embedding,
            success_mem,
            failure_mem,
            tool_stats,
            available_tools,
            recent_tool_calls,
            msg_hash,
        )

        top3 = candidates[:3]

        # ── No viable candidate ───────────────────────────────────────────────
        if not candidates or candidates[0]["score"] < THRESHOLD_MEDIUM:
            best = (
                f"{candidates[0]['tool']} @ {candidates[0]['score']:.2f}"
                if candidates
                else "none"
            )
            decision = Decision(
                action="no_tool",
                tool=None,
                confidence=max(0.0, candidates[0]["score"]) if candidates else 0.0,
                confidence_label="low",
                reason=f"no tool above threshold (best: {best})",
                candidates=top3,
            )

        # ── Confident routing ─────────────────────────────────────────────────
        else:
            top = candidates[0]
            score = top["score"]
            label = "high" if score >= THRESHOLD_HIGH else "medium"
            c = top["components"]
            decision = Decision(
                action="use_tool",
                tool=top["tool"],
                confidence=min(1.0, max(0.0, score)),
                confidence_label=label,
                reason=(
                    f"{top['tool']} score={score:.2f} "
                    f"ss={c['semantic_similarity']:.2f} "
                    f"sr={c['success_rate']:.2f} "
                    f"fp={c['failure_penalty']:.2f}"
                ),
                candidates=top3,
            )

        self._log_prediction(pred_id, normalized, msg_hash, decision, ctx)
        logger.debug(
            "predict: action=%s tool=%s conf=%.2f msg='%s'",
            decision.action,
            decision.tool,
            decision.confidence,
            normalized[:80],
        )
        return decision

    def record_success(
        self,
        message: str,
        tool: str,
        context: dict | None = None,
    ) -> None:
        """Record that *tool* was correctly called for *message*.

        Increments use_count rather than duplicating entries when the same
        (normalized_message, tool) pair is recorded again.

        Example:
            >>> import tempfile
            >>> dl = DecisionLayer(tempfile.mkdtemp())
            >>> dl.record_success("find articles about AI", "web_search")
        """
        normalized = _normalize(message)
        embedding = embed(normalized)

        mem: list[dict] = load_json(self._success_path, [])
        existing = next(
            (e for e in mem if e["normalized"] == normalized and e["tool"] == tool),
            None,
        )
        if existing:
            existing["use_count"] = existing.get("use_count", 1) + 1
            existing["timestamp"] = now_iso()
        else:
            mem.append(
                {
                    "id": str(uuid.uuid4()),
                    "message": message,
                    "normalized": normalized,
                    "embedding": embedding,
                    "tool": tool,
                    "context_snapshot": context or {},
                    "timestamp": now_iso(),
                    "use_count": 1,
                }
            )
        atomic_write_json(self._success_path, mem)
        self._update_stats(tool, success=True)
        self._log_outcome(normalized, tool, "success", None)
        logger.debug("record_success: tool=%s msg='%s'", tool, normalized[:80])

    def record_failure(
        self,
        message: str,
        tool: str,
        error: str,
        context: dict | None = None,
    ) -> None:
        """Record that *tool* was called incorrectly or raised an error for *message*.

        The error string is auto-categorised (wrong_tool | wrong_directory |
        wrong_param | exception | timeout | other) and used to penalise this
        tool on future similar messages.

        Example:
            >>> import tempfile
            >>> dl = DecisionLayer(tempfile.mkdtemp())
            >>> dl.record_failure("send email", "web_search", "wrong tool: can't send email")
        """
        normalized = _normalize(message)
        embedding = embed(normalized)
        category = _categorize_error(error)

        mem: list[dict] = load_json(self._failure_path, [])
        existing = next(
            (e for e in mem if e["normalized"] == normalized and e["tool"] == tool),
            None,
        )
        if existing:
            existing["occurrence_count"] = existing.get("occurrence_count", 1) + 1
            existing["timestamp"] = now_iso()
        else:
            mem.append(
                {
                    "id": str(uuid.uuid4()),
                    "message": message,
                    "normalized": normalized,
                    "embedding": embedding,
                    "tool": tool,
                    "error": error,
                    "error_category": category,
                    "context_snapshot": context or {},
                    "timestamp": now_iso(),
                    "occurrence_count": 1,
                }
            )
        atomic_write_json(self._failure_path, mem)
        self._update_stats(tool, success=False, error_category=category)
        self._log_outcome(normalized, tool, "failure", error)
        logger.debug(
            "record_failure: tool=%s cat=%s msg='%s'", tool, category, normalized[:80]
        )

    def record_no_tool_success(
        self,
        message: str,
        context: dict | None = None,
    ) -> None:
        """Record that no-tool was the correct response for *message*.

        Example:
            >>> import tempfile
            >>> dl = DecisionLayer(tempfile.mkdtemp())
            >>> dl.record_no_tool_success("hello there")
        """
        normalized = _normalize(message)
        embedding = embed(normalized)

        mem: list[dict] = load_json(self._no_tool_path, [])
        existing = next((e for e in mem if e["normalized"] == normalized), None)
        if existing:
            existing["use_count"] = existing.get("use_count", 1) + 1
            existing["timestamp"] = now_iso()
        else:
            mem.append(
                {
                    "id": str(uuid.uuid4()),
                    "message": message,
                    "normalized": normalized,
                    "embedding": embedding,
                    "context_snapshot": context or {},
                    "timestamp": now_iso(),
                    "use_count": 1,
                }
            )
        atomic_write_json(self._no_tool_path, mem)
        self._log_outcome(normalized, None, "no_tool_success", None)
        logger.debug("record_no_tool_success: msg='%s'", normalized[:80])

    def get_stats(self) -> dict:
        """Return per-tool stats and overall prediction summary.

        Example:
            >>> import tempfile
            >>> dl = DecisionLayer(tempfile.mkdtemp())
            >>> dl.get_stats()["summary"]["total_successes"]
            0
        """
        tool_stats: dict[str, Any] = load_json(self._stats_path, {})
        total_s = sum(v.get("successes", 0) for v in tool_stats.values())
        total_f = sum(v.get("failures", 0) for v in tool_stats.values())
        total = total_s + total_f
        return {
            "tool_stats": tool_stats,
            "summary": {
                "total_successes": total_s,
                "total_failures": total_f,
                "overall_success_rate": total_s / total if total > 0 else None,
                "tools_known": list(tool_stats.keys()),
            },
        }

    def clear_failures(self) -> None:
        """Wipe failure memory and reset failure counts in tool_stats.

        Useful for debugging or resetting after a bad batch of training data.

        Example:
            >>> import tempfile
            >>> dl = DecisionLayer(tempfile.mkdtemp())
            >>> dl.record_failure("task", "tool", "oops")
            >>> dl.clear_failures()
            >>> dl.get_stats()["summary"]["total_failures"]
            0
        """
        atomic_write_json(self._failure_path, [])
        tool_stats: dict[str, Any] = load_json(self._stats_path, {})
        for entry in tool_stats.values():
            entry["failures"] = 0
            entry["top_failure_categories"] = {}
        atomic_write_json(self._stats_path, tool_stats)
        logger.info("clear_failures: failure memory wiped")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _update_stats(
        self,
        tool: str,
        success: bool,
        error_category: str | None = None,
    ) -> None:
        stats: dict[str, Any] = load_json(self._stats_path, {})
        entry = stats.setdefault(
            tool,
            {
                "successes": 0,
                "failures": 0,
                "last_used": None,
                "avg_confidence_when_used": 0.0,
                "top_failure_categories": {},
            },
        )
        if success:
            entry["successes"] = entry.get("successes", 0) + 1
        else:
            entry["failures"] = entry.get("failures", 0) + 1
            if error_category:
                cats: dict[str, int] = entry.setdefault("top_failure_categories", {})
                cats[error_category] = cats.get(error_category, 0) + 1
        entry["last_used"] = now_iso()
        atomic_write_json(self._stats_path, stats)

    def _log_prediction(
        self,
        pred_id: str,
        normalized: str,
        msg_hash: str,
        decision: Decision,
        ctx: dict,
    ) -> None:
        append_jsonl(
            self._log_path,
            {
                "event": "prediction",
                "id": pred_id,
                "normalized_message": normalized,
                "message_hash": msg_hash,
                "action": decision.action,
                "tool": decision.tool,
                "confidence": decision.confidence,
                "confidence_label": decision.confidence_label,
                "reason": decision.reason,
                "candidates": decision.candidates,
                "context": ctx,
                "timestamp": now_iso(),
            },
        )

    def _log_outcome(
        self,
        normalized: str,
        tool: str | None,
        outcome: str,
        error: str | None,
    ) -> None:
        pred_id = self._pending.get(normalized)
        append_jsonl(
            self._log_path,
            {
                "event": "outcome",
                "prediction_id": pred_id,
                "normalized_message": normalized,
                "tool": tool,
                "outcome": outcome,
                "error": error,
                "timestamp": now_iso(),
            },
        )
