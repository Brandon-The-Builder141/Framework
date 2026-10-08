"""Tests for process_guidance.py — covers KnowledgeBase, GuidanceEngine, ActionMonitor."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from process_guidance import (
    ActionMonitor,
    GuidanceEngine,
    GuidanceEntry,
    KnowledgeBase,
    NoteFormatter,
    SessionSummary,
    _detect_high_risk_command,
    _fuzzy_ratio,
    _keyword_score,
    _tokenize,
    add_guidance_note,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_kb() -> tuple[KnowledgeBase, Path]:
    """Return a KnowledgeBase backed by a temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    kb = KnowledgeBase(db_path=Path(tmp.name))
    return kb, Path(tmp.name)


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------

class TestKnowledgeBase:
    def test_seeds_on_empty_db(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "fresh.json")
        assert len(kb.entries) >= 6, "should seed with built-in entries"

    def test_add_entry(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        before = len(kb.entries)
        entry = kb.add_entry(
            trigger="test_trigger",
            context="ctx",
            mistake="mistake",
            resolution="resolution",
            note="test note",
            tags=["a", "b"],
            severity="info",
        )
        assert len(kb.entries) == before + 1
        assert entry.trigger == "test_trigger"
        assert entry.severity == "info"

    def test_persistence(self, tmp_path):
        path = tmp_path / "kb.json"
        kb1 = KnowledgeBase(db_path=path)
        kb1.add_entry("t", "c", "m", "r", "note", ["tag"])
        count1 = len(kb1.entries)

        kb2 = KnowledgeBase(db_path=path)
        assert len(kb2.entries) == count1

    def test_recent_session_ids(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        for i in range(7):
            s = SessionSummary(id=f"session-{i}")
            kb.record_session(s)
        recent = kb.recent_session_ids(5)
        assert len(recent) == 5

    def test_get_entry(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        entry = kb.add_entry("t2", "c", "m", "r", "note2")
        found = kb.get_entry(entry.id)
        assert found is not None
        assert found.note == "note2"


# ---------------------------------------------------------------------------
# Matching utilities
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("write_file gallery.html")
        assert "write" in tokens or "write_file" in tokens or "gallery" in tokens

    def test_drops_short(self):
        tokens = _tokenize("a bb ccc dddd")
        assert "a" not in tokens
        assert "bb" not in tokens
        assert "ccc" in tokens
        assert "dddd" in tokens


class TestFuzzyRatio:
    def test_identical(self):
        assert _fuzzy_ratio("gallery", "gallery") == pytest.approx(1.0)

    def test_similar(self):
        ratio = _fuzzy_ratio("gallery", "gallery-menu")
        assert 0.6 < ratio < 1.0

    def test_dissimilar(self):
        assert _fuzzy_ratio("gallery", "completely_different") < 0.5


class TestKeywordScore:
    def test_matches_tags(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        entry = kb.entries[0]  # seed entry with tags
        tokens = set(entry.tags) | {"extra_token"}
        score, reasons = _keyword_score(tokens, entry)
        assert score > 0

    def test_no_match(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        entry = kb.entries[0]
        tokens = {"zzz", "yyy", "xxx"}
        score, _ = _keyword_score(tokens, entry)
        assert score == 0.0


# ---------------------------------------------------------------------------
# GuidanceEngine
# ---------------------------------------------------------------------------

class TestGuidanceEngine:
    def _engine(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        return GuidanceEngine(kb), kb

    @pytest.mark.asyncio
    async def test_gallery_write_fires_notes(self, tmp_path):
        engine, _ = self._engine(tmp_path)
        matches = await engine.match("write_file", "gallery.html", "updating gallery")
        assert len(matches) > 0
        triggers = {m.entry.trigger for m in matches}
        assert "gallery_scene_link" in triggers or "create_file_duplicate" in triggers

    @pytest.mark.asyncio
    async def test_git_push_main_fires_critical(self, tmp_path):
        engine, _ = self._engine(tmp_path)
        matches = await engine.match("run_command", "git push origin main")
        critical = [m for m in matches if m.entry.severity == "critical"]
        assert len(critical) > 0, "git push main should surface at least one critical note"

    @pytest.mark.asyncio
    async def test_discord_message_fires_tone_note(self, tmp_path):
        engine, _ = self._engine(tmp_path)
        matches = await engine.match("discord_message", "general: update")
        triggers = {m.entry.trigger for m in matches}
        assert "discord_message_tone" in triggers

    @pytest.mark.asyncio
    async def test_threshold_filters_noise(self, tmp_path):
        engine, _ = self._engine(tmp_path)
        matches = await engine.match("run_command", "echo hello world", threshold=0.15)
        for m in matches:
            assert m.score >= 0.15

    @pytest.mark.asyncio
    async def test_top_n_respected(self, tmp_path):
        engine, _ = self._engine(tmp_path)
        matches = await engine.match("write_file", "gallery.html", top_n=2)
        assert len(matches) <= 2

    @pytest.mark.asyncio
    async def test_custom_entry_matches(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        kb.add_entry(
            trigger="my_custom_trigger",
            context="when running deploy script",
            mistake="forgot to set env",
            resolution="set DEPLOY_ENV first",
            note="Set DEPLOY_ENV before running deploy!",
            tags=["deploy", "env"],
        )
        engine = GuidanceEngine(kb)
        matches = await engine.match("run_command", "deploy.sh", "deploy environment")
        triggers = {m.entry.trigger for m in matches}
        assert "my_custom_trigger" in triggers


# ---------------------------------------------------------------------------
# NoteFormatter
# ---------------------------------------------------------------------------

class TestNoteFormatter:
    @pytest.mark.asyncio
    async def test_format_inline_nonempty(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        engine = GuidanceEngine(kb)
        matches = await engine.match("write_file", "gallery.html")
        result = NoteFormatter.format_inline(matches)
        assert "[Process" in result

    def test_format_inline_empty(self):
        result = NoteFormatter.format_inline([])
        assert result == ""

    def test_format_block_empty(self):
        result = NoteFormatter.format_block([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_unicode_arrows(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        engine = GuidanceEngine(kb)
        matches = await engine.match("write_file", "gallery.html")
        result = NoteFormatter.format_inline(matches)
        assert "→" not in result, "Unicode arrow should not appear in output"


# ---------------------------------------------------------------------------
# ActionMonitor
# ---------------------------------------------------------------------------

class TestActionMonitor:
    def test_detect_duplicate_risk_positive(self, tmp_path):
        # Create a sibling file to trigger detection
        sibling = tmp_path / "gallery.html"
        sibling.write_text("<html></html>")
        target = tmp_path / "gallery-menu.html"

        monitor = ActionMonitor()
        assert monitor.detect_duplicate_risk(str(target)) is True

    def test_detect_duplicate_risk_negative(self, tmp_path):
        monitor = ActionMonitor()
        unique = tmp_path / "completely_unique_xyz999.html"
        assert monitor.detect_duplicate_risk(str(unique)) is False

    def test_file_exists(self, tmp_path):
        f = tmp_path / "exists.txt"
        f.write_text("hi")
        monitor = ActionMonitor()
        assert monitor.file_exists(str(f)) is True
        assert monitor.file_exists(str(tmp_path / "nope.txt")) is False

    @pytest.mark.asyncio
    async def test_check_logs_action(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        monitor = ActionMonitor(kb=kb)
        matches, note = await monitor.check("write_file", "gallery.html")
        assert monitor._session.actions_taken == 1
        if matches:
            assert monitor._session.notes_surfaced >= 1

    def test_end_session_saves(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        monitor = ActionMonitor(kb=kb)
        session = monitor.end_session()
        assert session.ended_at is not None
        # Verify it was persisted
        kb2 = KnowledgeBase(db_path=tmp_path / "kb.json")
        assert any(s.id == session.id for s in kb2.sessions)


# ---------------------------------------------------------------------------
# High-risk command detection
# ---------------------------------------------------------------------------

class TestHighRiskDetection:
    def test_force_push(self):
        result = _detect_high_risk_command("git push --force origin main")
        assert "CRITICAL" in result
        assert "force" in result.lower()

    def test_force_push_short_flag(self):
        result = _detect_high_risk_command("git push -f origin main")
        assert "CRITICAL" in result

    def test_rm_rf(self):
        result = _detect_high_risk_command("rm -rf /some/path")
        assert "Warning" in result or "Destructive" in result

    def test_push_main(self):
        result = _detect_high_risk_command("git push origin main")
        assert result != ""
        assert "main" in result.lower() or "master" in result.lower()

    def test_safe_command(self):
        result = _detect_high_risk_command("ls -la")
        assert result == ""

    def test_drop_table(self):
        result = _detect_high_risk_command("DROP TABLE users")
        assert "CRITICAL" in result


# ---------------------------------------------------------------------------
# add_guidance_note API
# ---------------------------------------------------------------------------

class TestAddGuidanceNote:
    def test_adds_entry(self, tmp_path):
        kb = KnowledgeBase(db_path=tmp_path / "kb.json")
        before = len(kb.entries)
        entry = add_guidance_note(
            trigger="api_test",
            context="test context",
            mistake="test mistake",
            resolution="test resolution",
            note="test note",
            tags=["test"],
            severity="info",
            kb=kb,
        )
        kb2 = KnowledgeBase(db_path=tmp_path / "kb.json")
        assert len(kb2.entries) == before + 1
        assert entry.trigger == "api_test"
