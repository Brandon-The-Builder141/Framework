from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from ._embeddings import cosine_similarity

logger = logging.getLogger("decision_layer")

# ── Tunable scoring weights ───────────────────────────────────────────────────
WEIGHT_SEMANTIC_SIMILARITY: float = 0.40
WEIGHT_SUCCESS_RATE: float = 0.25
WEIGHT_RECENCY: float = 0.10
WEIGHT_FAILURE_PENALTY: float = 0.25

# ── Decision thresholds ───────────────────────────────────────────────────────
THRESHOLD_HIGH: float = 0.65    # score >= this → use_tool / high
THRESHOLD_MEDIUM: float = 0.40  # score >= this → use_tool / medium; below → no_tool

# ── Retrieval ─────────────────────────────────────────────────────────────────
TOPK_NEIGHBORS: int = 10
RECENCY_DECAY_DAYS: float = 7.0

# ── Loop avoidance ────────────────────────────────────────────────────────────
LOOP_WINDOW: int = 3
LOOP_PENALTY: float = 0.50
# ─────────────────────────────────────────────────────────────────────────────


def message_hash(normalized: str) -> str:
    """Return a short stable hex hash of a normalised message string.

    Example:
        >>> message_hash("hello world") == message_hash("hello world")
        True
    """
    return hashlib.sha1(normalized.encode()).hexdigest()[:16]


def score_candidates(
    query_embedding: list[float],
    success_mem: list[dict],
    failure_mem: list[dict],
    tool_stats: dict[str, Any],
    available_tools: list[str] | None,
    recent_tool_calls: list[dict],
    current_msg_hash: str,
) -> list[dict]:
    """Score all candidate tools against the query embedding.

    Candidates are tools that have at least one success memory entry.
    If *available_tools* is a non-empty list, only those tools are considered.

    Returns:
        List of dicts sorted descending by score:
        [{"tool": str, "score": float, "components": {...}}, ...]

    Example:
        >>> score_candidates([0.0]*256, [], [], {}, None, [], "abc")
        []
    """
    s_by_tool: dict[str, list[dict]] = defaultdict(list)
    for e in success_mem:
        s_by_tool[e["tool"]].append(e)

    f_by_tool: dict[str, list[dict]] = defaultdict(list)
    for e in failure_mem:
        f_by_tool[e["tool"]].append(e)

    candidate_tools = set(s_by_tool.keys())
    if available_tools:  # non-None AND non-empty
        candidate_tools &= set(available_tools)

    loop_penalties = _build_loop_penalties(recent_tool_calls, current_msg_hash)

    results: list[dict] = []
    for tool in candidate_tools:
        # ── Semantic similarity ───────────────────────────────────────────────
        s_sims = sorted(
            [cosine_similarity(query_embedding, e["embedding"]) for e in s_by_tool[tool]],
            reverse=True,
        )[:TOPK_NEIGHBORS]
        ss = sum(s_sims) / len(s_sims) if s_sims else 0.0

        # ── Success rate ──────────────────────────────────────────────────────
        stats = tool_stats.get(tool, {})
        successes = stats.get("successes", 0)
        failures = stats.get("failures", 0)
        total = successes + failures
        sr = successes / total if total > 0 else 0.5  # uninformed prior

        # ── Recency ───────────────────────────────────────────────────────────
        rc = _recency_score(stats.get("last_used"))

        # ── Failure penalty ───────────────────────────────────────────────────
        f_entries = f_by_tool.get(tool, [])
        if f_entries:
            f_sims = sorted(
                [cosine_similarity(query_embedding, e["embedding"]) for e in f_entries],
                reverse=True,
            )[:TOPK_NEIGHBORS]
            fp = sum(f_sims) / len(f_sims)
        else:
            fp = 0.0

        # ── Loop avoidance ────────────────────────────────────────────────────
        lp = loop_penalties.get(tool, 0.0)

        score = (
            WEIGHT_SEMANTIC_SIMILARITY * ss
            + WEIGHT_SUCCESS_RATE * sr
            + WEIGHT_RECENCY * rc
            - WEIGHT_FAILURE_PENALTY * fp
            - lp
        )

        results.append(
            {
                "tool": tool,
                "score": round(score, 4),
                "components": {
                    "semantic_similarity": round(ss, 4),
                    "success_rate": round(sr, 4),
                    "recency": round(rc, 4),
                    "failure_penalty": round(fp, 4),
                    "loop_penalty": round(lp, 4),
                },
            }
        )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _recency_score(last_used_iso: str | None) -> float:
    if not last_used_iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(last_used_iso)
        delta_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
        return max(0.0, 1.0 - delta_days / RECENCY_DECAY_DAYS)
    except ValueError:
        return 0.0


def _build_loop_penalties(
    recent_tool_calls: list[dict], current_msg_hash: str
) -> dict[str, float]:
    """Penalise tools that failed on this message in the recent call window.

    Matches on message_hash when present; falls back to penalising any recent
    failure for the tool if no hash is recorded.
    """
    window = (
        recent_tool_calls[-LOOP_WINDOW:]
        if len(recent_tool_calls) > LOOP_WINDOW
        else recent_tool_calls
    )
    penalties: dict[str, float] = {}
    for call in window:
        tool = call.get("tool")
        if not tool:
            continue
        if call.get("success", True):
            continue
        entry_hash = call.get("message_hash")
        if entry_hash is None or entry_hash == current_msg_hash:
            penalties[tool] = penalties.get(tool, 0.0) + LOOP_PENALTY
    return penalties
