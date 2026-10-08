"""Tests for decision_layer — all 7 required cases plus extras."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import decision_layer._embeddings as emb_mod
from decision_layer import DecisionLayer, Decision
from decision_layer._scoring import message_hash


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def dl(tmp_path):
    """Fresh DecisionLayer backed by a temp directory."""
    return DecisionLayer(memory_dir=str(tmp_path / "dl"))


@pytest.fixture(autouse=True)
def _reset_embedding_cache():
    """Snapshot and restore the embedding model cache around each test."""
    original = dict(emb_mod._model_cache)
    yield
    emb_mod._model_cache.clear()
    emb_mod._model_cache.update(original)


def _norm(msg: str) -> str:
    return re.sub(r"\s+", " ", msg.strip().lower())


# ── 1. Cold start ─────────────────────────────────────────────────────────────


def test_cold_start_returns_no_tool(dl):
    """Empty memory → no_tool with low confidence and cold-start reason."""
    d = dl.predict("search the web for AI news")
    assert d.action == "no_tool"
    assert d.tool is None
    assert d.confidence == 0.0
    assert d.confidence_label == "low"
    assert "cold start" in d.reason


# ── 2. Single example learning ────────────────────────────────────────────────


def test_single_example_learning(dl):
    """After one success a semantically similar message returns the same tool."""
    dl.record_success("search for the latest AI news articles", "web_search")
    d = dl.predict("look up recent news about artificial intelligence")
    assert d.action == "use_tool"
    assert d.tool == "web_search"
    assert d.confidence_label in ("medium", "high")
    assert d.confidence >= 0.40


def test_exact_message_returns_high_confidence(dl):
    """The exact trained message should hit high confidence."""
    msg = "fetch the current weather forecast"
    dl.record_success(msg, "weather_tool")
    d = dl.predict(msg)
    assert d.action == "use_tool"
    assert d.tool == "weather_tool"
    assert d.confidence_label == "high"


# ── 3. Failure suppression ────────────────────────────────────────────────────


def test_failure_suppression(tmp_path):
    """After many failures the tool's score drops below the threshold."""
    dl = DecisionLayer(memory_dir=str(tmp_path / "dl"))
    msg = "send an email to alice"

    # One success puts the tool in the candidate pool.
    dl.record_success(msg, "email_tool")
    # Three failures on the same message overwhelm it.
    for _ in range(3):
        dl.record_failure(msg, "email_tool", "wrong tool: email_tool not applicable")

    d = dl.predict("send a message to alice via email")
    # email_tool should either be absent or scored below threshold.
    if d.action == "use_tool":
        assert d.tool != "email_tool", "suppressed tool must not be chosen"
    # Most likely outcome: no_tool because the only candidate is suppressed.


# ── 4. Loop avoidance ─────────────────────────────────────────────────────────


def test_loop_avoidance(dl):
    """Tool that failed 3× for this message in recent_tool_calls is suppressed."""
    msg = "run the build pipeline"
    normalized = _norm(msg)
    mhash = message_hash(normalized)

    dl.record_success(msg, "build_tool")

    recent = [
        {"tool": "build_tool", "success": False, "message_hash": mhash},
        {"tool": "build_tool", "success": False, "message_hash": mhash},
        {"tool": "build_tool", "success": False, "message_hash": mhash},
    ]
    d = dl.predict(msg, context={"recent_tool_calls": recent})
    if d.action == "use_tool":
        assert d.tool != "build_tool", "loop-avoided tool must not be chosen"


def test_loop_avoidance_different_message_no_penalty(dl):
    """Loop penalty must not apply when the failed message hash differs."""
    msg = "run the build pipeline"
    dl.record_success(msg, "build_tool")

    # Failures are for a *different* message hash.
    other_hash = message_hash(_norm("deploy to production"))
    recent = [
        {"tool": "build_tool", "success": False, "message_hash": other_hash},
        {"tool": "build_tool", "success": False, "message_hash": other_hash},
        {"tool": "build_tool", "success": False, "message_hash": other_hash},
    ]
    d = dl.predict(msg, context={"recent_tool_calls": recent})
    assert d.action == "use_tool"
    assert d.tool == "build_tool"


# ── 5. available_tools filter ─────────────────────────────────────────────────


def test_available_tools_excludes_unknown_tool(dl):
    """Tool not in available_tools is never returned."""
    dl.record_success("search the web", "web_search")
    d = dl.predict("search the web", context={"available_tools": ["other_tool"]})
    assert d.action == "no_tool"


def test_available_tools_allows_known_tool(dl):
    """Tool present in available_tools is returned normally."""
    dl.record_success("search the web", "web_search")
    d = dl.predict("search the web", context={"available_tools": ["web_search", "other"]})
    assert d.action == "use_tool"
    assert d.tool == "web_search"


def test_available_tools_none_uses_all(dl):
    """available_tools=None allows all known tools."""
    dl.record_success("search the web", "web_search")
    d = dl.predict("search the web", context={"available_tools": None})
    assert d.action == "use_tool"
    assert d.tool == "web_search"


def test_available_tools_empty_uses_all(dl):
    """available_tools=[] (empty) falls back to all known tools per spec."""
    dl.record_success("search the web", "web_search")
    d = dl.predict("search the web", context={"available_tools": []})
    assert d.action == "use_tool"
    assert d.tool == "web_search"


# ── 6. Persistence round-trip ─────────────────────────────────────────────────


def test_persistence_roundtrip(tmp_path):
    """Write memory with instance A, reload with instance B, predict same result."""
    mem_dir = str(tmp_path / "dl_persist")
    dl1 = DecisionLayer(memory_dir=mem_dir)
    dl1.record_success("fetch me the weather forecast", "weather_tool")
    dl1.record_success("what is the weather today", "weather_tool")

    dl2 = DecisionLayer(memory_dir=mem_dir)
    d = dl2.predict("what's the weather like right now?")
    assert d.action == "use_tool"
    assert d.tool == "weather_tool"


def test_failure_memory_persists(tmp_path):
    """Failure memory is reloaded correctly by a new instance."""
    mem_dir = str(tmp_path / "dl_fp")
    dl1 = DecisionLayer(memory_dir=mem_dir)
    dl1.record_success("send email", "email_tool")
    for _ in range(3):
        dl1.record_failure("send email", "email_tool", "wrong tool")

    dl2 = DecisionLayer(memory_dir=mem_dir)
    d = dl2.predict("send email to bob")
    if d.action == "use_tool":
        assert d.tool != "email_tool"


# ── 7. Embedding fallback ─────────────────────────────────────────────────────


def test_embedding_fallback_module_still_works(tmp_path):
    """Module remains functional when sentence-transformers is unavailable."""
    emb_mod.reset_model_cache()

    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None  # noqa

    def _blocking_import(name, *args, **kwargs):
        if "sentence_transformers" in name:
            raise ImportError(f"mocked unavailable: {name}")
        return real_import(name, *args, **kwargs)

    import builtins
    real_import = builtins.__import__

    with patch("builtins.__import__", side_effect=_blocking_import):
        emb_mod.reset_model_cache()
        dl = DecisionLayer(memory_dir=str(tmp_path / "dl_fallback"))
        dl.record_success("search for AI news", "web_search")
        d = dl.predict("look up recent AI developments")

    assert isinstance(d, Decision)
    assert d.action in ("use_tool", "no_tool")


# ── Extras ────────────────────────────────────────────────────────────────────


def test_get_stats_reflects_records(dl):
    """Stats accurately count successes and failures."""
    dl.record_success("do a search", "search_tool")
    dl.record_failure("do a search", "wrong_tool", "wrong tool error")

    stats = dl.get_stats()
    assert stats["summary"]["total_successes"] == 1
    assert stats["summary"]["total_failures"] == 1
    assert "search_tool" in stats["tool_stats"]
    assert "wrong_tool" in stats["tool_stats"]


def test_clear_failures(dl):
    """clear_failures wipes failure memory and resets failure counts in stats."""
    dl.record_success("task", "tool_a")
    dl.record_failure("task", "tool_a", "it broke")

    assert dl.get_stats()["summary"]["total_failures"] == 1

    dl.clear_failures()

    assert dl.get_stats()["summary"]["total_failures"] == 0
    from decision_layer._memory import load_json

    assert load_json(dl._failure_path, []) == []


def test_use_count_deduplication(dl):
    """Repeated (message, tool) successes increment use_count, not row count."""
    msg = "run the script"
    for _ in range(3):
        dl.record_success(msg, "run_tool")

    from decision_layer._memory import load_json

    mem = load_json(dl._success_path, [])
    entries = [e for e in mem if e["tool"] == "run_tool"]
    assert len(entries) == 1
    assert entries[0]["use_count"] == 3


def test_error_auto_categorization(dl):
    """Errors are categorised correctly by heuristic pattern matching."""
    dl.record_failure("open file", "file_tool", "No such file or directory: /tmp/x")
    dl.record_failure("web call", "web_tool", "Connection timed out after 30s")
    dl.record_failure("api call", "api_tool", "Missing required parameter: api_key")
    dl.record_failure("run", "run_tool", "this is the wrong tool for the job")

    from decision_layer._memory import load_json

    mem = load_json(dl._failure_path, [])
    cats = {e["tool"]: e["error_category"] for e in mem}
    assert cats["file_tool"] == "wrong_directory"
    assert cats["web_tool"] == "timeout"
    assert cats["api_tool"] == "wrong_param"
    assert cats["run_tool"] == "wrong_tool"


def test_multi_tool_disambiguation(tmp_path):
    """The tool with more and closer success examples wins over a weaker one."""
    dl = DecisionLayer(memory_dir=str(tmp_path / "dl_multi"))

    for _ in range(5):
        dl.record_success("search the web for news", "web_search")
    dl.record_success("play some music", "music_player")

    d = dl.predict("find the latest news headlines online")
    assert d.tool == "web_search"


def test_no_tool_success_persisted(dl):
    """record_no_tool_success is written to no_tool_memory.json."""
    dl.record_no_tool_success("just saying hello")
    from decision_layer._memory import load_json

    mem = load_json(dl._no_tool_path, [])
    assert len(mem) == 1
    assert "just saying hello" in mem[0]["message"]


def test_prediction_log_written(dl):
    """predict() appends an entry to prediction_log.jsonl."""
    import json

    dl.predict("some message")
    lines = dl._log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    entry = json.loads(lines[0])
    assert entry["event"] == "prediction"
    assert "id" in entry


def test_candidates_in_decision(dl):
    """Returned Decision.candidates contains scored tool dicts."""
    dl.record_success("run tests", "test_runner")
    dl.record_success("deploy app", "deploy_tool")

    d = dl.predict("execute the test suite")
    assert isinstance(d.candidates, list)
    if d.candidates:
        assert "tool" in d.candidates[0]
        assert "score" in d.candidates[0]
