"""Pre-save deduplication, recall failure logging, and memory health maintenance."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Literal

from config.settings import LOGS_DIR
from src.agent.memory_db import get_connection
from src.agent.memory_stores import ProfileStore, _now_iso

DEDUP_LOG = LOGS_DIR / "memory_duplicates.log"
RECALL_FAILURE_LOG = LOGS_DIR / "memory_recall_failures.log"

PROFILE_DEDUP_THRESHOLD = float(os.getenv("MEMORY_PROFILE_DEDUP_THRESHOLD", "0.90"))
EPISODIC_DEDUP_THRESHOLD = float(os.getenv("MEMORY_EPISODIC_DEDUP_THRESHOLD", "0.92"))
RECALL_MIN_SCORE = float(os.getenv("MEMORY_RECALL_MIN_SCORE", "0.35"))
RECALL_APPROX_MIN_SCORE = float(os.getenv("MEMORY_RECALL_APPROX_MIN_SCORE", "0.18"))

TRIVIAL_EPISODIC_PHRASES = frozenset({
    "ok", "okay", "k", "kk", "yes", "no", "yep", "nope", "thanks", "thank you",
    "ty", "cool", "nice", "got it", "sure", "lol", "haha", "hi", "hey", "hello",
    "bye", "goodbye", "nm", "nothing", "n/a", "na", "test", "testing",
})

Action = Literal["save", "skip", "merge"]


@dataclass
class ProfileSaveDecision:
    action: Action
    key: str
    value: str
    confidence: float
    existing_id: str | None = None
    similarity: float = 0.0
    message: str = ""


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _extract_message_body(content: str) -> str:
    c = (content or "").strip()
    if ":" in c[:40]:
        prefix, _, rest = c.partition(":")
        if prefix.lower() in {"user", "assistant", "andrew", "system"}:
            return rest.strip()
    return c


def is_trivial_episodic(content: str) -> bool:
    """True for low-signal turns (ok, thanks, bare User:)."""
    body = _normalize_text(_extract_message_body(content))
    if not body or len(body) <= 2:
        return True
    if body in TRIVIAL_EPISODIC_PHRASES:
        return True
    if re.fullmatch(r"[.!?,]+", body):
        return True
    return False


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def log_duplicate(
    *,
    memory_type: str,
    action: str,
    content: str,
    duplicate_of: str | None = None,
    similarity: float = 0.0,
    user_id: str = "default",
    extra: dict[str, Any] | None = None,
) -> None:
    _append_log(
        DEDUP_LOG,
        {
            "user_id": user_id,
            "memory_type": memory_type,
            "action": action,
            "content_preview": (content or "")[:240],
            "duplicate_of": duplicate_of,
            "similarity": round(similarity, 4),
            **(extra or {}),
        },
    )


def log_recall_failure(
    *,
    query: str,
    user_id: str = "default",
    mode: str = "episodic",
    note: str = "",
    closest: dict[str, Any] | None = None,
) -> None:
    _append_log(
        RECALL_FAILURE_LOG,
        {
            "user_id": user_id,
            "query": query[:500],
            "mode": mode,
            "note": note,
            "closest": closest,
        },
    )


def _merge_fact_text(existing: str, new: str) -> str:
    a = _normalize_text(existing)
    b = _normalize_text(new)
    if a == b:
        return existing
    if a in b:
        return new.strip()
    if b in a:
        return existing.strip()
    return f"{existing.rstrip('.')}. {new.strip()}"


def _lexical_similarity(a: str, b: str) -> float:
    wa = {w for w in re.findall(r"[a-zA-Z0-9']{3,}", _normalize_text(a))}
    wb = {w for w in re.findall(r"[a-zA-Z0-9']{3,}", _normalize_text(b))}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def find_profile_duplicate(
    user_id: str,
    category: str,
    fact: str,
    *,
    threshold: float = PROFILE_DEDUP_THRESHOLD,
) -> tuple[Any | None, float]:
    """Return (ProfileFact|None, similarity) for the closest semantic duplicate."""
    from src.agent.memory_stores import _row_to_fact

    text = f"{category}: {fact}"
    store = ProfileStore(user_id)
    idx = None
    try:
        from src.agent.memory_embeddings import SemanticIndex

        idx = SemanticIndex(user_id)
        if idx.service.is_available:
            hits = idx.find_similar_text(
                text,
                limit=3,
                source_table="profile_facts",
                min_score=threshold - 0.15,
            )
            for hit in hits:
                row = store._conn().execute(
                    "SELECT * FROM profile_facts WHERE id = ? AND deleted_at IS NULL",
                    (hit.source_id,),
                ).fetchone()
                if row:
                    return _row_to_fact(row), float(hit.score)
    except Exception:
        pass

    best = None
    best_score = 0.0
    probe = _normalize_text(fact)
    for pf in store.get_all(category=category):
        score = _lexical_similarity(probe, pf.value)
        if score > best_score:
            best_score = score
            best = pf
    if best_score >= threshold - 0.05:
        return best, best_score
    return None, 0.0


def prepare_profile_fact_write(
    user_id: str,
    key: str,
    value: str,
    *,
    category: str,
    confidence: float,
    source: str,
) -> ProfileSaveDecision:
    """Decide whether to save, skip, or merge a profile fact before persistence."""
    value = (value or "").strip()
    if not value:
        return ProfileSaveDecision("skip", key, value, confidence, message="empty fact")

    store = ProfileStore(user_id)
    exact = store.get(key)
    if exact and _normalize_text(exact.value) == _normalize_text(value):
        log_duplicate(
            memory_type="profile",
            action="skip_identical",
            content=value,
            duplicate_of=exact.id,
            user_id=user_id,
            extra={"key": key, "category": category},
        )
        return ProfileSaveDecision(
            "skip", key, value, confidence,
            existing_id=exact.id,
            message="Skipped duplicate.",
        )

    dup, sim = find_profile_duplicate(user_id, category, value)
    if dup and sim >= PROFILE_DEDUP_THRESHOLD:
        if _normalize_text(dup.value) == _normalize_text(value):
            log_duplicate(
                memory_type="profile",
                action="skip_semantic",
                content=value,
                duplicate_of=dup.id,
                similarity=sim,
                user_id=user_id,
                extra={"key": dup.key},
            )
            return ProfileSaveDecision(
                "skip", dup.key, dup.value, dup.confidence,
                existing_id=dup.id,
                similarity=sim,
                message="Skipped duplicate.",
            )

        merged = _merge_fact_text(dup.value, value)
        new_conf = max(float(dup.confidence), float(confidence))
        if new_conf <= float(dup.confidence) and _normalize_text(merged) == _normalize_text(dup.value):
            log_duplicate(
                memory_type="profile",
                action="skip_lower_confidence",
                content=value,
                duplicate_of=dup.id,
                similarity=sim,
                user_id=user_id,
            )
            return ProfileSaveDecision(
                "skip", dup.key, dup.value, dup.confidence,
                existing_id=dup.id,
                similarity=sim,
                message="Skipped duplicate.",
            )

        log_duplicate(
            memory_type="profile",
            action="merge",
            content=value,
            duplicate_of=dup.id,
            similarity=sim,
            user_id=user_id,
            extra={"merged_preview": merged[:200]},
        )
        return ProfileSaveDecision(
            "merge", dup.key, merged, new_conf,
            existing_id=dup.id,
            similarity=sim,
            message="Merged with existing fact.",
        )

    return ProfileSaveDecision("save", key, value, confidence, message="Saved new fact.")


def index_profile_fact(user_id: str, fact_id: str, category: str, value: str) -> None:
    try:
        from src.agent.memory_embeddings import SemanticIndex

        SemanticIndex(user_id).add("profile_facts", fact_id, f"{category}: {value}")
    except Exception:
        pass


def should_skip_episodic_duplicate(user_id: str, content: str) -> bool:
    if is_trivial_episodic(content):
        return True
    body = _extract_message_body(content)
    try:
        from src.agent.memory_embeddings import SemanticIndex

        idx = SemanticIndex(user_id)
        if not idx.service.is_available:
            return False
        hits = idx.find_similar_text(
            body,
            limit=1,
            source_table="episodic_memory",
            min_score=EPISODIC_DEDUP_THRESHOLD,
        )
        if hits:
            log_duplicate(
                memory_type="episodic",
                action="skip",
                content=content,
                duplicate_of=hits[0].source_id,
                similarity=hits[0].score,
                user_id=user_id,
            )
            return True
    except Exception:
        pass
    return False


def index_episodic_turn(user_id: str, entry_id: str, content: str) -> None:
    try:
        from src.agent.memory_embeddings import SemanticIndex

        SemanticIndex(user_id).add("episodic_memory", entry_id, _extract_message_body(content))
    except Exception:
        pass


def schedule_is_duplicate(title: str, items: list[Any], existing_text: str) -> bool:
    new_blob = _normalize_text(f"{title} {' '.join(str(i) for i in (items or []))}")
    if _normalize_text(existing_text) == new_blob:
        return True
    return _lexical_similarity(new_blob, existing_text) >= 0.95


def prune_duplicate_profile_facts(user_id: str = "default") -> dict[str, int]:
    """Weekly health: soft-delete lower-confidence semantic duplicates."""
    store = ProfileStore(user_id)
    facts = store.get_all(min_confidence=0.0)
    removed = 0
    deleted_ids: set[str] = set()

    for i, a in enumerate(facts):
        if a.id in deleted_ids:
            continue
        for b in facts[i + 1:]:
            if b.id in deleted_ids or a.category != b.category:
                continue
            sim = _lexical_similarity(a.value, b.value)
            if sim < PROFILE_DEDUP_THRESHOLD:
                continue
            winner, loser = (a, b) if (a.confidence, a.updated_at) >= (b.confidence, b.updated_at) else (b, a)
            if loser.protected:
                continue
            now = _now_iso()
            store._conn().execute(
                "UPDATE profile_facts SET deleted_at = ? WHERE id = ?",
                (now, loser.id),
            )
            deleted_ids.add(loser.id)
            removed += 1
            log_duplicate(
                memory_type="profile",
                action="health_prune",
                content=loser.value,
                duplicate_of=winner.id,
                similarity=sim,
                user_id=user_id,
            )
    return {"profile_duplicates_pruned": removed}


def archive_trivial_episodic(user_id: str = "default", *, days: int = 14) -> dict[str, int]:
    """Soft-delete old trivial episodic turns."""
    from datetime import timedelta
    from src.agent.memory_stores import _utcnow

    cutoff = (_utcnow() - timedelta(days=days)).isoformat(sep=" ", timespec="microseconds")
    conn = get_connection(user_id)
    rows = conn.execute(
        "SELECT id, content, importance FROM episodic_memory "
        "WHERE deleted_at IS NULL AND created_at < ? AND importance < 0.55",
        (cutoff,),
    ).fetchall()
    archived = 0
    now = _now_iso()
    for row in rows:
        if not is_trivial_episodic(row["content"] or ""):
            continue
        conn.execute(
            "UPDATE episodic_memory SET deleted_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        archived += 1
    return {"trivial_episodic_archived": archived}


def reindex_profile_embeddings(user_id: str = "default", *, limit: int = 500) -> dict[str, int]:
    """Ensure profile facts have semantic embeddings for dedup/recall."""
    from src.agent.memory_embeddings import SemanticIndex

    store = ProfileStore(user_id)
    idx = SemanticIndex(user_id)
    if not idx.service.is_available:
        return {"profile_indexed": 0}
    rows = store._conn().execute(
        "SELECT id, category, value FROM profile_facts "
        "WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    existing = {
        r["source_id"]
        for r in idx._conn().execute(
            "SELECT source_id FROM semantic_embeddings WHERE source_table = 'profile_facts'"
        ).fetchall()
    }
    batch = [
        ("profile_facts", r["id"], f"{r['category']}: {r['value']}")
        for r in rows
        if r["id"] not in existing
    ]
    inserted = len(idx.add_many(batch)) if batch else 0
    return {"profile_indexed": inserted}


def run_memory_health(user_id: str = "default") -> dict[str, Any]:
    """Full weekly memory health pass."""
    stats: dict[str, Any] = {"user_id": user_id}
    stats.update(reindex_profile_embeddings(user_id))
    stats.update(prune_duplicate_profile_facts(user_id))
    stats.update(archive_trivial_episodic(user_id))
    _append_log(DEDUP_LOG, {"event": "health_pass_complete", **stats})
    return stats
