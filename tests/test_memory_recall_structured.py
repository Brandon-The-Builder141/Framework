"""Tests for the structured recall() API and format_recall_for_prompt()."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from config.settings import USER_PROFILES_DIR
from src.agent.memory_db import close_all, get_connection
from src.agent.memory_stores import EpisodicStore, ProfileStore, SessionStore, _utcnow
from src.memory_recall import RecallResult, format_recall_for_prompt, recall


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def user_id() -> str:  # type: ignore[override]
    uid = f"recall_{uuid.uuid4().hex[:10]}"
    yield uid
    close_all()
    shutil.rmtree(USER_PROFILES_DIR / uid, ignore_errors=True)


@pytest.fixture()
def populated(user_id: str) -> tuple[str, str, str]:
    """Insert known episodic + profile data and return (user_id, session_id, turn_id)."""
    sess = SessionStore(user_id).create("test")
    es = EpisodicStore(user_id)
    # High-importance turn about the project
    tid = es.insert(sess.id, "user", "We decided to use SQLite for the memory backend", importance=0.85)
    # Low-importance noise
    es.insert(sess.id, "user", "Sure sounds good", importance=0.2)
    # Profile fact
    ProfileStore(user_id).set(
        "personal::lives in alabama",
        "Lives in Alabama",
        category="personal",
        confidence=0.9,
        source="user",
    )
    return user_id, sess.id, tid


# ── recall() — basic ──────────────────────────────────────────────────────────


def test_recall_returns_list_of_recall_result(populated: tuple) -> None:
    uid, *_ = populated
    results = recall("SQLite memory backend", user_id=uid, top_k=5)
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, RecallResult)


def test_recall_finds_relevant_episodic_turn(populated: tuple) -> None:
    uid, *_ = populated
    results = recall("SQLite memory backend", user_id=uid, top_k=5)
    sources = [r.source for r in results]
    assert "episodic" in sources
    contents = " ".join(r.content for r in results)
    assert "SQLite" in contents


def test_recall_respects_top_k(populated: tuple) -> None:
    uid, *_ = populated
    for k in (1, 2, 5):
        results = recall("SQLite memory backend", user_id=uid, top_k=k)
        assert len(results) <= k


def test_recall_results_sorted_by_score_descending(populated: tuple) -> None:
    uid, *_ = populated
    results = recall("SQLite memory", user_id=uid, top_k=10)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_recall_scores_in_unit_range(populated: tuple) -> None:
    uid, *_ = populated
    results = recall("SQLite", user_id=uid, top_k=10)
    for r in results:
        assert 0.0 <= r.score <= 1.0, f"score out of range: {r.score}"


def test_recall_returns_empty_for_unmatched_query(populated: tuple) -> None:
    uid, *_ = populated
    results = recall("xyzzyplugh_never_matches_anything", user_id=uid, top_k=5)
    assert results == []


def test_recall_returns_empty_for_missing_db(tmp_path: Path) -> None:
    """No crash when the database file doesn't exist."""
    import src.memory_recall as mr
    fake_uid = f"ghost_{uuid.uuid4().hex[:8]}"
    results = recall("anything", user_id=fake_uid, top_k=5)
    assert results == []


# ── recall() — profile facts ──────────────────────────────────────────────────


def test_recall_finds_profile_facts(populated: tuple) -> None:
    uid, *_ = populated
    results = recall("Alabama", user_id=uid, top_k=5)
    profile_hits = [r for r in results if r.source == "profile"]
    assert profile_hits, "expected at least one profile hit for 'Alabama'"
    assert any("Alabama" in r.content for r in profile_hits)


# ── recall() — mode="semantic" fallback ───────────────────────────────────────


def test_recall_semantic_mode_falls_back_gracefully(populated: tuple) -> None:
    """semantic mode should not raise even without a real embedding service."""
    uid, *_ = populated
    results = recall("SQLite memory backend", user_id=uid, top_k=5, mode="semantic")
    # Either got semantic hits or fell back to episodic — both are valid
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, RecallResult)


def test_recall_unknown_mode_defaults_to_episodic(populated: tuple) -> None:
    """An unrecognised mode should not raise — it goes through the episodic path."""
    uid, *_ = populated
    results = recall("SQLite", user_id=uid, top_k=5, mode="foobar")
    # foobar != "semantic" so it falls into the episodic branch
    assert isinstance(results, list)


# ── format_recall_for_prompt() ────────────────────────────────────────────────


def test_format_recall_for_prompt_empty_returns_empty_string() -> None:
    assert format_recall_for_prompt([]) == ""


def test_format_recall_for_prompt_includes_header() -> None:
    r = RecallResult(source="episodic", title="2026-01-01", content="hello world", score=0.8)
    block = format_recall_for_prompt([r], header="## Context")
    assert block.startswith("## Context")


def test_format_recall_for_prompt_includes_content_and_score() -> None:
    r = RecallResult(source="episodic", title="t", content="important fact here", score=0.75)
    block = format_recall_for_prompt([r])
    assert "important fact here" in block
    assert "0.75" in block


def test_format_recall_for_prompt_truncates_long_content() -> None:
    long_content = "x" * 2000
    r = RecallResult(source="episodic", title="t", content=long_content, score=0.5)
    block = format_recall_for_prompt([r], max_content_chars=400)
    # The x-string in the output should be at most 400 chars
    assert block.count("x") <= 400


def test_format_recall_for_prompt_multiple_results() -> None:
    results = [
        RecallResult(source="episodic", title="t1", content="first memory", score=0.9),
        RecallResult(source="profile", title="personal", content="lives in Alabama", score=0.7),
    ]
    block = format_recall_for_prompt(results)
    assert "first memory" in block
    assert "lives in Alabama" in block


def test_format_recall_for_prompt_includes_timestamp() -> None:
    r = RecallResult(
        source="episodic", title="t", content="msg", score=0.6,
        timestamp="2026-01-15T10:30:00",
    )
    block = format_recall_for_prompt([r])
    assert "2026-01-15T10:30:00" in block


# ── Decision layer bootstrap ──────────────────────────────────────────────────


def test_bootstrap_seed_recall_examples_teaches_recall_routing(tmp_path: Path) -> None:
    from decision_layer import DecisionLayer
    from decision_layer.bootstrap import seed_recall_examples

    dl = DecisionLayer(memory_dir=str(tmp_path / "dl"))
    n = seed_recall_examples(dl)
    assert n > 0
    # After seeding, a memory-query should route to "recall"
    d = dl.predict("do you remember when I mentioned the deadline?")
    assert d.action == "use_tool"
    assert d.tool == "recall"


def test_bootstrap_seed_all_covers_multiple_tools(tmp_path: Path) -> None:
    from decision_layer import DecisionLayer
    from decision_layer.bootstrap import seed_all

    dl = DecisionLayer(memory_dir=str(tmp_path / "dl"))
    n = seed_all(dl)
    assert n > 0
    stats = dl.get_stats()
    tools = stats["summary"]["tools_known"]
    assert "recall" in tools
    assert "search_web" in tools
    assert len(tools) >= 3


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    from decision_layer import DecisionLayer
    from decision_layer.bootstrap import seed_recall_examples
    from decision_layer._memory import load_json

    dl = DecisionLayer(memory_dir=str(tmp_path / "dl"))
    seed_recall_examples(dl)
    seed_recall_examples(dl)  # call twice
    # Should not double the rows, only increment use_count
    mem = load_json(dl._success_path, [])
    recall_entries = [e for e in mem if e["tool"] == "recall"]
    # Exact number of unique seeded messages
    from decision_layer.bootstrap import _RECALL_SEEDS
    assert len(recall_entries) == len(_RECALL_SEEDS)
    # All use_count should be 2 (seeded twice)
    for e in recall_entries:
        assert e["use_count"] == 2


# ── Multi-turn recall: integration smoke test ─────────────────────────────────


def test_multi_turn_recall_accumulates_context(user_id: str) -> None:
    """After several turns that mention a project, recall finds them all."""
    sess = SessionStore(user_id).create("test")
    es = EpisodicStore(user_id)
    turns = [
        "We are building a decision layer for tool routing",
        "The decision layer uses sentence-transformers for embeddings",
        "Travis wants the system to persist state in JSON files",
        "We discussed using SQLite for the memory backend",
    ]
    for t in turns:
        es.insert(sess.id, "user", t, importance=0.8)

    results = recall("decision layer", user_id=user_id, top_k=5)
    # Both the "decision layer" turns should rank at the top
    decision_hits = [r for r in results if "decision" in r.content.lower()]
    assert len(decision_hits) >= 2

    results2 = recall("SQLite memory", user_id=user_id, top_k=3)
    assert any("SQLite" in r.content for r in results2)
