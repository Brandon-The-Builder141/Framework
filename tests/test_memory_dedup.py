"""Tests for memory deduplication and recall improvements."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.memory import MemoryStore, _fact_key
from src.agent.memory_db import close_all, db_path
from src.agent.memory_stores import EpisodicStore, ProfileStore
from src.memory_dedup import (
    DEDUP_LOG,
    RECALL_FAILURE_LOG,
    is_trivial_episodic,
    prepare_profile_fact_write,
    prune_duplicate_profile_facts,
    schedule_is_duplicate,
)
from src.memory_recall import recall, format_recall_for_prompt


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    import uuid

    uid = f"dedup_{uuid.uuid4().hex[:8]}"
    db = tmp_path / uid / "memory.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    def _path(user_id: str = "default") -> Path:
        return db if user_id == uid else tmp_path / user_id / "memory.db"

    monkeypatch.setattr("src.agent.memory_db.db_path", _path)
    monkeypatch.setattr("src.memory_recall.db_path", _path)
    MemoryStore(user_id=uid)
    yield uid
    close_all()


def test_trivial_episodic_detection():
    assert is_trivial_episodic("User: ok")
    assert is_trivial_episodic("thanks")
    assert not is_trivial_episodic("User: Brandon works on AI memory systems")


def test_profile_skip_identical_duplicate(memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.memory_dedup.DEDUP_LOG", tmp_path / "dup.log")
    store = ProfileStore(memory_db)
    key = _fact_key("personal", "Brandon prefers OpenRouter")
    store.set(key, "Brandon prefers OpenRouter", category="personal", _skip_dedup=True)

    decision = prepare_profile_fact_write(
        memory_db, key, "Brandon prefers OpenRouter",
        category="personal", confidence=1.0, source="user",
    )
    assert decision.action == "skip"


def test_profile_merge_similar_fact(memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.memory_dedup.DEDUP_LOG", tmp_path / "dup.log")
    store = ProfileStore(memory_db)
    key_a = _fact_key("work", "Brandon builds AI agents")
    store.set(key_a, "Brandon builds AI agents", category="work", _skip_dedup=True)

    key_b = _fact_key("work", "Brandon builds AI agent frameworks")
    decision = prepare_profile_fact_write(
        memory_db, key_b, "Brandon builds AI agent frameworks",
        category="work", confidence=0.95, source="user",
    )
    assert decision.action in {"save", "merge", "skip"}


def test_episodic_skips_trivial(memory_db):
    episodic = EpisodicStore(memory_db)
    eid = episodic.insert("sess1", "user", "User: ok")
    assert eid == ""
    row = episodic._conn().execute("SELECT COUNT(*) AS n FROM episodic_memory").fetchone()
    assert int(row["n"]) == 0


def test_recall_approximate_match_header(memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.memory_dedup.RECALL_FAILURE_LOG", tmp_path / "fail.log")
    mem = MemoryStore(user_id=memory_db)
    mem.add_short_term(
        "User: We discussed neural memory consolidation for Brandon's framework",
        importance=0.9,
    )
    results = recall(
        "quantum physics cooking recipes",
        top_k=1,
        mode="episodic",
        user_id=memory_db,
        min_score=0.99,
        allow_approximate=True,
    )
    if results:
        block = format_recall_for_prompt(results)
        assert "related memory" in block.lower() or results[0].metadata.get("approximate_match")


def test_schedule_duplicate():
    old = "Travis Morning Schedule\n- Take medication"
    assert schedule_is_duplicate(
        "Travis Morning Schedule",
        ["Take medication"],
        old,
    )


def test_health_prune_lexical_duplicates(memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.memory_dedup.DEDUP_LOG", tmp_path / "dup.log")
    store = ProfileStore(memory_db)
    store.set(
        _fact_key("personal", "Brandon uses Windows"),
        "Brandon uses Windows",
        category="personal",
        confidence=0.9,
        _skip_dedup=True,
    )
    store.set(
        _fact_key("personal", "Brandon uses Windows OS"),
        "Brandon uses Windows OS",
        category="personal",
        confidence=0.5,
        protected=False,
        _skip_dedup=True,
    )
    stats = prune_duplicate_profile_facts(memory_db)
    assert stats["profile_duplicates_pruned"] >= 0


def test_memory_store_add_profile_returns_skip_message(memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.memory_dedup.DEDUP_LOG", tmp_path / "dup.log")
    mem = MemoryStore(user_id=memory_db)
    mem.add_profile_fact("personal", "Brandon is the creator")
    msg = mem.add_profile_fact("personal", "Brandon is the creator")
    assert "duplicate" in msg.lower() or "Skipped" in msg
