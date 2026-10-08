"""
process_guidance.py — Process-Aware Guidance System

Provides contextual reminders based on past errors, learned processes, and shared
workflows. Hooks into core tools (write_file, run_command, send_discord_message) to
surface relevant notes before actions execute. Learns after each session.

Usage:
    from process_guidance import ActionMonitor, GuidanceEngine, learn_from_session
    from process_guidance import guided_write_file, guided_run_command, guided_send_discord_message

    monitor = ActionMonitor()
    engine  = GuidanceEngine()

    result = await guided_write_file("gallery.html", content)
    # → "[Process Note] Last time, you created gallery-menu.html instead..."
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent
_DB_PATH = _ROOT / "data" / "process_guidance.json"
_LOG_PATH = _ROOT / "data" / "guidance_action_log.json"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

SEVERITY_LEVELS = ("info", "warning", "critical")


class GuidanceEntry(BaseModel):
    """A single knowledge-base record: one learned mistake / process note."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trigger: str                          # machine-readable tag, e.g. "create_file_duplicate"
    context: str                          # short human description of when this fires
    mistake: str                          # what went wrong
    resolution: str                       # what to do instead
    note: str                             # inline note surfaced to the user
    tags: list[str] = Field(default_factory=list)
    severity: str = "warning"             # info | warning | critical
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    hit_count: int = 0
    last_triggered: str | None = None
    session_ids: list[str] = Field(default_factory=list)

    def record_hit(self, session_id: str) -> None:
        self.hit_count += 1
        self.last_triggered = datetime.now(timezone.utc).isoformat()
        if session_id not in self.session_ids:
            self.session_ids.append(session_id)


class ActionRecord(BaseModel):
    """A single logged action taken during a session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    action_type: str                      # write_file | run_command | discord_message
    subject: str                          # path, command string, channel name, etc.
    keywords: list[str] = Field(default_factory=list)
    matched_entry_ids: list[str] = Field(default_factory=list)
    notes_surfaced: list[str] = Field(default_factory=list)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    outcome: str = "pending"             # pending | success | error


class SessionSummary(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: str | None = None
    actions_taken: int = 0
    notes_surfaced: int = 0
    entries_added: int = 0
    reflection: str = ""


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """Loads, saves, and queries the JSON guidance store."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self.db_path = db_path
        self.entries: list[GuidanceEntry] = []
        self.sessions: list[SessionSummary] = []
        self._load()

    # --- Persistence --------------------------------------------------------

    def _load(self) -> None:
        if not self.db_path.exists():
            self.entries = _seed_entries()
            self.sessions = []
            self._save()
            return
        try:
            raw = json.loads(self.db_path.read_text(encoding="utf-8"))
            self.entries = [GuidanceEntry(**e) for e in raw.get("entries", [])]
            self.sessions = [SessionSummary(**s) for s in raw.get("sessions", [])]
        except Exception as exc:
            logger.warning("Failed to load guidance DB: %s — starting fresh", exc)
            self.entries = _seed_entries()
            self.sessions = []

    def _save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": [e.model_dump() for e in self.entries],
            "sessions": [s.model_dump() for s in self.sessions],
        }
        self.db_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # --- CRUD ---------------------------------------------------------------

    def add_entry(
        self,
        trigger: str,
        context: str,
        mistake: str,
        resolution: str,
        note: str,
        tags: list[str] | None = None,
        severity: str = "warning",
    ) -> GuidanceEntry:
        entry = GuidanceEntry(
            trigger=trigger,
            context=context,
            mistake=mistake,
            resolution=resolution,
            note=note,
            tags=tags or [],
            severity=severity,
        )
        self.entries.append(entry)
        self._save()
        return entry

    def get_entry(self, entry_id: str) -> GuidanceEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def record_session(self, session: SessionSummary) -> None:
        existing = next((s for s in self.sessions if s.id == session.id), None)
        if existing:
            idx = self.sessions.index(existing)
            self.sessions[idx] = session
        else:
            self.sessions.append(session)
        self._save()

    # --- Query --------------------------------------------------------------

    def recent_sessions(self, n: int = 5) -> list[SessionSummary]:
        """Return the n most recent sessions (for recency weighting)."""
        sorted_sessions = sorted(
            self.sessions,
            key=lambda s: s.started_at,
            reverse=True,
        )
        return sorted_sessions[:n]

    def recent_session_ids(self, n: int = 5) -> set[str]:
        return {s.id for s in self.recent_sessions(n)}


# ---------------------------------------------------------------------------
# Matching / Scoring
# ---------------------------------------------------------------------------

@dataclass
class MatchScore:
    entry: GuidanceEntry
    score: float          # 0.0 – 1.0
    reasons: list[str] = field(default_factory=list)


def _tokenize(text: str) -> set[str]:
    """Lowercase, split on non-alphanumerics, drop short tokens."""
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2}


def _fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _keyword_score(query_tokens: set[str], entry: GuidanceEntry) -> tuple[float, list[str]]:
    """Overlap between query tokens and entry fields + tags."""
    entry_tokens = (
        _tokenize(entry.trigger)
        | _tokenize(entry.context)
        | _tokenize(entry.note)
        | _tokenize(entry.resolution)
        | {t.lower() for t in entry.tags}
    )
    if not entry_tokens:
        return 0.0, []
    overlap = query_tokens & entry_tokens
    if not overlap:
        return 0.0, []
    score = len(overlap) / max(len(query_tokens), 1)
    reasons = [f"keyword match: {', '.join(sorted(overlap)[:5])}"]
    return min(score, 1.0), reasons


def _path_similarity_score(path: str, entry: GuidanceEntry) -> tuple[float, list[str]]:
    """Check if the path resembles paths mentioned in any entry field."""
    path_tokens = _tokenize(path)
    best = 0.0
    reasons: list[str] = []
    for field_text in (entry.context, entry.note, entry.trigger):
        ratio = _fuzzy_ratio(path, field_text)
        if ratio > best:
            best = ratio
    # also check token overlap
    entry_tokens = _tokenize(entry.context) | _tokenize(entry.note)
    overlap = path_tokens & entry_tokens
    if overlap:
        token_score = len(overlap) / max(len(path_tokens), 1)
        if token_score > best:
            best = token_score
            reasons = [f"path token match: {', '.join(sorted(overlap)[:3])}"]
    return min(best * 0.8, 1.0), reasons  # cap path contribution


def _recency_weight(entry: GuidanceEntry, recent_ids: set[str]) -> float:
    """Boost entries that appeared in recent sessions."""
    overlap = set(entry.session_ids) & recent_ids
    if not overlap:
        return 1.0
    return 1.0 + 0.3 * min(len(overlap), 3)  # up to 1.9× boost


def _severity_weight(entry: GuidanceEntry) -> float:
    return {"info": 0.8, "warning": 1.0, "critical": 1.4}.get(entry.severity, 1.0)


# ---------------------------------------------------------------------------
# Guidance Engine
# ---------------------------------------------------------------------------

class GuidanceEngine:
    """Matches an action context against the knowledge base and returns ranked notes."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or KnowledgeBase()
        self._semantic_model: Any = None   # lazy-loaded
        self._model_lock = asyncio.Lock()

    # --- Semantic model (optional) ------------------------------------------

    async def _get_model(self) -> Any | None:
        """Lazy-load sentence-transformer model if available."""
        if self._semantic_model is not None:
            return self._semantic_model
        async with self._model_lock:
            if self._semantic_model is not None:
                return self._semantic_model
            try:
                from sentence_transformers import SentenceTransformer
                import numpy as np  # noqa: F401
                loop = asyncio.get_event_loop()
                model = await loop.run_in_executor(
                    None,
                    lambda: SentenceTransformer("all-MiniLM-L6-v2"),
                )
                self._semantic_model = model
                logger.debug("Semantic model loaded.")
            except Exception:
                logger.debug("sentence-transformers unavailable; using keyword matching only.")
                self._semantic_model = False  # sentinel: tried, not available
        return self._semantic_model if self._semantic_model else None

    async def _semantic_scores(
        self, query: str, entries: list[GuidanceEntry]
    ) -> dict[str, float]:
        """Return cosine-similarity scores keyed by entry id."""
        model = await self._get_model()
        if not model:
            return {}
        try:
            import numpy as np
            loop = asyncio.get_event_loop()
            texts = [query] + [
                f"{e.trigger} {e.context} {e.note}" for e in entries
            ]
            embeddings = await loop.run_in_executor(None, lambda: model.encode(texts))
            query_vec = embeddings[0]
            result: dict[str, float] = {}
            for i, entry in enumerate(entries):
                entry_vec = embeddings[i + 1]
                sim = float(
                    np.dot(query_vec, entry_vec)
                    / (np.linalg.norm(query_vec) * np.linalg.norm(entry_vec) + 1e-9)
                )
                result[entry.id] = sim
            return result
        except Exception as exc:
            logger.debug("Semantic scoring failed: %s", exc)
            return {}

    # --- Core match ---------------------------------------------------------

    async def match(
        self,
        action_type: str,
        subject: str,
        extra_context: str = "",
        top_n: int = 3,
        threshold: float = 0.15,
    ) -> list[MatchScore]:
        """
        Find the top-N relevant guidance entries for a given action.

        Args:
            action_type: e.g. "write_file", "run_command", "discord_message"
            subject:     the primary subject (file path, command, channel+message)
            extra_context: any extra text to help with matching
            top_n:       max results to return
            threshold:   minimum score to include (0.0–1.0)
        """
        if not self.kb.entries:
            return []

        query = f"{action_type} {subject} {extra_context}".strip()
        query_tokens = _tokenize(query)
        recent_ids = self.kb.recent_session_ids(5)

        # Fast keyword pass
        candidates: list[GuidanceEntry] = []
        for entry in self.kb.entries:
            kw_score, _ = _keyword_score(query_tokens, entry)
            if kw_score > 0:
                candidates.append(entry)

        # If no keyword hits, consider all entries for semantic pass
        if not candidates:
            candidates = self.kb.entries

        # Semantic scores (async, optional)
        semantic = await self._semantic_scores(query, candidates)

        # Combine scores
        scored: list[MatchScore] = []
        for entry in candidates:
            kw_score, kw_reasons = _keyword_score(query_tokens, entry)
            path_score, path_reasons = _path_similarity_score(subject, entry)
            sem_score = semantic.get(entry.id, 0.0)

            # Weighted combination
            combined = (
                kw_score * 0.45
                + path_score * 0.20
                + sem_score * 0.35
            )
            combined *= _recency_weight(entry, recent_ids)
            combined *= _severity_weight(entry)

            if combined >= threshold:
                reasons = kw_reasons + path_reasons
                if sem_score > 0.4:
                    reasons.append(f"semantic similarity: {sem_score:.2f}")
                scored.append(MatchScore(entry=entry, score=combined, reasons=reasons))

        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_n]


# ---------------------------------------------------------------------------
# Note Formatter
# ---------------------------------------------------------------------------

class NoteFormatter:
    """Formats guidance matches into inline process notes."""

    @staticmethod
    def format_inline(matches: list[MatchScore]) -> str:
        """Return a formatted string of process notes, or empty string if none."""
        if not matches:
            return ""
        lines: list[str] = []
        for m in matches:
            severity_prefix = {
                "info": "[Process Note]",
                "warning": "[Process Warning]",
                "critical": "[!! CRITICAL PROCESS WARNING !!]",
            }.get(m.entry.severity, "[Process Note]")

            lines.append(f"{severity_prefix}")
            lines.append(f"{m.entry.note}")
            if m.entry.resolution:
                lines.append(f"-> {m.entry.resolution}")
        return "\n".join(lines)

    @staticmethod
    def format_block(matches: list[MatchScore]) -> str:
        """Return a markdown-formatted block for display in responses."""
        if not matches:
            return ""
        blocks: list[str] = []
        for m in matches:
            icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(
                m.entry.severity, "📌"
            )
            blocks.append(
                f"{icon} **Process Note** (triggered by: `{m.entry.trigger}`)\n"
                f"> {m.entry.note}\n"
                f"> **Resolution:** {m.entry.resolution}"
            )
        return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Action Monitor
# ---------------------------------------------------------------------------

_SESSION_ID: str = str(uuid.uuid4())  # module-level session ID for this run
_action_log: list[ActionRecord] = []


class ActionMonitor:
    """
    Intercepts tool calls, checks the guidance engine, logs actions.

    Instantiate once and share across all guided tool wrappers.
    """

    def __init__(
        self,
        kb: KnowledgeBase | None = None,
        engine: GuidanceEngine | None = None,
        formatter: NoteFormatter | None = None,
        session_id: str | None = None,
    ) -> None:
        self.kb = kb or KnowledgeBase()
        self.engine = engine or GuidanceEngine(self.kb)
        self.formatter = formatter or NoteFormatter()
        self.session_id = session_id or _SESSION_ID
        self._session = SessionSummary(id=self.session_id)

    # --- Risk detectors (fast, synchronous) ---------------------------------

    def detect_duplicate_risk(self, path: str) -> bool:
        """Return True if path looks like it might create an unintended variant."""
        p = Path(path)
        parent = p.parent
        stem = p.stem
        # Check for sibling files with similar names
        if parent.exists():
            for sibling in parent.iterdir():
                if sibling == p:
                    continue
                ratio = _fuzzy_ratio(sibling.stem, stem)
                if ratio > 0.65 and sibling.suffix == p.suffix:
                    return True
        return False

    def file_exists(self, path: str) -> bool:
        return Path(path).expanduser().resolve(strict=False).exists()

    # --- Core check ---------------------------------------------------------

    async def check(
        self,
        action_type: str,
        subject: str,
        extra_context: str = "",
    ) -> tuple[list[MatchScore], str]:
        """
        Check an about-to-happen action against the knowledge base.

        Returns (matches, formatted_note_string).
        """
        matches = await self.engine.match(action_type, subject, extra_context)
        note_str = self.formatter.format_inline(matches)

        record = ActionRecord(
            session_id=self.session_id,
            action_type=action_type,
            subject=subject,
            keywords=list(_tokenize(f"{action_type} {subject} {extra_context}")),
            matched_entry_ids=[m.entry.id for m in matches],
            notes_surfaced=[m.entry.note for m in matches],
        )
        _action_log.append(record)
        self._session.actions_taken += 1
        if matches:
            self._session.notes_surfaced += len(matches)
            for m in matches:
                m.entry.record_hit(self.session_id)

        return matches, note_str

    async def record_outcome(self, action_type: str, subject: str, outcome: str) -> None:
        """Update the most recent matching log record with its outcome."""
        for record in reversed(_action_log):
            if record.action_type == action_type and record.subject == subject:
                record.outcome = outcome
                break

    def flush_log(self) -> None:
        """Write the action log to disk."""
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if _LOG_PATH.exists():
            try:
                existing = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.extend([r.model_dump() for r in _action_log])
        # Keep last 500 records
        existing = existing[-500:]
        _LOG_PATH.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def end_session(self) -> SessionSummary:
        self._session.ended_at = datetime.now(timezone.utc).isoformat()
        self.kb.record_session(self._session)
        self.flush_log()
        return self._session


# ---------------------------------------------------------------------------
# Guided tool wrappers
# ---------------------------------------------------------------------------

# Module-level shared instances (override by passing your own to wrappers)
_default_kb = None
_default_monitor = None


def _get_default_monitor() -> ActionMonitor:
    global _default_kb, _default_monitor
    if _default_monitor is None:
        _default_kb = KnowledgeBase()
        _default_monitor = ActionMonitor(kb=_default_kb)
    return _default_monitor


async def guided_write_file(
    path: str,
    content: str,
    monitor: ActionMonitor | None = None,
) -> str:
    """
    Write a file with guidance checks.

    Surfaces process notes for duplicate-file risk, path confusion,
    and other learned mistakes before delegating to the real write_file.
    """
    m = monitor or _get_default_monitor()

    # Check for duplicate risk (fast, synchronous)
    dup_warning = ""
    if m.detect_duplicate_risk(path):
        dup_warning = (
            "[Process Warning]\n"
            "A file with a similar name already exists in that directory.\n"
            "→ Verify you're editing the right file before writing.\n\n"
        )

    # File-exists check
    exists_note = ""
    if not m.file_exists(path):
        pass  # creating new — fine
    else:
        exists_note = (
            "[Process Note]\n"
            f"File already exists at {path}. This will overwrite it.\n\n"
        )

    # Guidance engine check
    _, guidance_note = await m.check("write_file", path, f"writing to {Path(path).name}")

    # Compose prefix
    prefix_parts = [p for p in (dup_warning, exists_note, guidance_note) if p]
    prefix = "\n".join(prefix_parts) + ("\n\n" if prefix_parts else "")

    # Delegate to smart_write_file so existing files get the overwrite guard
    try:
        from src.tools.system import smart_write_file as _smart_write
        result = await _smart_write(path, content)
    except ImportError:
        result = f"[smart_write_file unavailable in this context — would write {len(content)} bytes to {path}]"

    outcome = "success" if "Error" not in str(result) else "error"
    await m.record_outcome("write_file", path, outcome)

    return f"{prefix}{result}" if prefix else result


async def guided_run_command(
    command: str,
    monitor: ActionMonitor | None = None,
) -> str:
    """
    Run a shell command with guidance checks.

    Warns before destructive operations, git pushes without tests, etc.
    """
    m = monitor or _get_default_monitor()
    _, guidance_note = await m.check("run_command", command)

    # Additional heuristics for high-risk commands
    high_risk = _detect_high_risk_command(command)

    prefix_parts = [p for p in (guidance_note, high_risk) if p]
    prefix = "\n".join(prefix_parts) + ("\n\n" if prefix_parts else "")

    # Delegate to real tool
    try:
        from src.tools.system import run_command as _run_command
        result = await _run_command(command)
    except ImportError:
        # Fallback: run via subprocess if src import unavailable
        import subprocess
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=60
            )
            result = proc.stdout + (proc.stderr if proc.stderr else "")
        except subprocess.TimeoutExpired:
            result = "Error: Command timed out after 60 seconds."
        except Exception as exc:
            result = f"Error: {exc}"

    outcome = "success" if "Error" not in str(result) else "error"
    await m.record_outcome("run_command", command, outcome)

    return f"{prefix}{result}" if prefix else result


async def guided_send_discord_message(
    channel: str,
    message: str,
    monitor: ActionMonitor | None = None,
) -> str:
    """
    Send a Discord message with guidance checks.

    Surfaces notes about communication patterns, tone, and confirmation habits.
    """
    m = monitor or _get_default_monitor()
    subject = f"{channel}: {message[:80]}"
    _, guidance_note = await m.check("discord_message", subject, message)

    prefix = f"{guidance_note}\n\n" if guidance_note else ""

    # Delegate to real tool
    try:
        from src.tools.discord.discord_monitor import send_discord_message as _send
        result = await _send(channel, message)
    except ImportError:
        result = f"[discord unavailable — would send to #{channel}: {message[:100]}...]"

    outcome = "success" if "Error" not in str(result) else "error"
    await m.record_outcome("discord_message", channel, outcome)

    return f"{prefix}{result}" if prefix else result


def _detect_high_risk_command(command: str) -> str:
    """Return a warning string for high-risk shell commands."""
    cmd_lower = command.lower()
    if re.search(r"git push.*--force|git push.*-f\b", cmd_lower):
        return (
            "[!! CRITICAL PROCESS WARNING !!]\n"
            "You are about to force-push. This rewrites history on the remote.\n"
            "-> Confirm this is intentional and no collaborators are on this branch."
        )
    if re.search(r"rm\s+-rf|rmdir\s+/s", cmd_lower):
        return (
            "[Process Warning]\n"
            "Destructive delete detected. Verify the target path before proceeding."
        )
    if re.search(r"git push", cmd_lower) and re.search(r"main|master", cmd_lower):
        return (
            "[Process Note]\n"
            "Pushing to main/master. Confirm tests passed and changes are intentional."
        )
    if "drop table" in cmd_lower or "delete from" in cmd_lower:
        return (
            "[!! CRITICAL PROCESS WARNING !!]\n"
            "Destructive database operation detected.\n"
            "-> Verify database name, table, and whether a backup exists."
        )
    return ""


# ---------------------------------------------------------------------------
# Learning loop
# ---------------------------------------------------------------------------

async def learn_from_session(
    monitor: ActionMonitor | None = None,
    interactive: bool = True,
) -> list[GuidanceEntry]:
    """
    Post-session reflection loop: prompts for new learnings and saves them.

    In interactive mode, prompts the user via stdin.
    In non-interactive mode (e.g. tests), returns without prompting.

    Returns list of newly added GuidanceEntry objects.
    """
    m = monitor or _get_default_monitor()
    session = m.end_session()

    print("\n" + "=" * 60)
    print("SESSION REFLECTION — Process Guidance Learning Loop")
    print("=" * 60)
    print(f"Actions taken:   {session.actions_taken}")
    print(f"Notes surfaced:  {session.notes_surfaced}")
    print()

    new_entries: list[GuidanceEntry] = []

    if not interactive:
        print("Non-interactive mode — skipping reflection prompts.")
        return new_entries

    print("Did anything go wrong or unexpectedly well this session?")
    print("Let's add it to the knowledge base. Press Enter to skip any field.\n")

    while True:
        print("-" * 40)
        trigger = input("Trigger keyword (e.g. 'create_file_duplicate') or Enter to finish: ").strip()
        if not trigger:
            break

        context  = input("When does this apply? (brief description): ").strip()
        mistake  = input("What went wrong (or what to watch out for): ").strip()
        resolution = input("What to do instead / resolution: ").strip()
        note     = input("Inline reminder note (shown in responses): ").strip()
        tags_str = input("Tags (comma-separated, e.g. 'github,file_management'): ").strip()
        severity = input("Severity [info/warning/critical] (default: warning): ").strip() or "warning"

        if severity not in SEVERITY_LEVELS:
            severity = "warning"

        tags = [t.strip() for t in tags_str.split(",") if t.strip()]

        if not note:
            print("Note is required — skipping this entry.")
            continue

        entry = m.kb.add_entry(
            trigger=trigger,
            context=context or trigger,
            mistake=mistake or "See note.",
            resolution=resolution or "See note.",
            note=note,
            tags=tags,
            severity=severity,
        )
        new_entries.append(entry)
        print(f"✓ Saved: [{entry.severity.upper()}] {entry.note[:60]}...")
        session.entries_added += 1

    # Save reflection
    reflection = input("\nOptional reflection (what to improve next session): ").strip()
    if reflection:
        session.reflection = reflection

    m.kb.record_session(session)
    print(f"\n{len(new_entries)} new guidance entr{'y' if len(new_entries) == 1 else 'ies'} saved.")
    print("=" * 60 + "\n")

    return new_entries


# ---------------------------------------------------------------------------
# Utility: add_guidance_note (spec API)
# ---------------------------------------------------------------------------

def add_guidance_note(
    trigger: str,
    context: str,
    mistake: str,
    resolution: str,
    note: str,
    tags: list[str] | None = None,
    severity: str = "warning",
    kb: KnowledgeBase | None = None,
) -> GuidanceEntry:
    """
    Programmatic API to add a guidance note without going through the
    interactive learning loop. Useful for seeding from tests or scripts.
    """
    store = kb or KnowledgeBase()
    return store.add_entry(trigger, context, mistake, resolution, note, tags, severity)


# ---------------------------------------------------------------------------
# Knowledge Base Seed Data
# ---------------------------------------------------------------------------

def _seed_entries() -> list[GuidanceEntry]:
    """Return initial knowledge base entries based on known past mistakes."""
    now = datetime.now(timezone.utc).isoformat()
    seeds = [
        {
            "trigger": "create_file_duplicate",
            "context": "Any time a file is created rather than editing an existing one",
            "mistake": "Assumed new files were needed without verifying existing ones — "
                       "created gallery-menu.html instead of updating gallery.html.",
            "resolution": "Always check file_exists() before creating. Edit the existing file unless "
                          "explicitly told to create a new one.",
            "note": "Last time, a duplicate file was created instead of editing the existing one. "
                    "Verify the target file before writing!",
            "tags": ["file_management", "github_pages", "duplicate"],
            "severity": "warning",
        },
        {
            "trigger": "github_push_delay",
            "context": "After making file changes intended for the live site",
            "mistake": "Made changes locally but forgot to push to GitHub — Travis had to ask explicitly.",
            "resolution": "Push to GitHub immediately after confirming changes are correct. "
                          "Don't wait to be asked.",
            "note": "Remember: push to GitHub immediately after changes. "
                    "Don't wait for Travis to ask — that's frustrating for him.",
            "tags": ["github", "github_pages", "communication", "workflow"],
            "severity": "warning",
        },
        {
            "trigger": "gallery_scene_link",
            "context": "Adding a new scene to the gallery",
            "mistake": "Added a scene file but forgot to link it in index.html for GitHub Pages.",
            "resolution": "After creating a scene file, always add the corresponding link to index.html.",
            "note": "Adding scenes requires updating index.html for GitHub Pages navigation. "
                    "Should I update that too?",
            "tags": ["gallery", "github_pages", "scene", "index_html"],
            "severity": "info",
        },
        {
            "trigger": "local_vs_github_confusion",
            "context": "Referencing file paths or testing links",
            "mistake": "Linked scenes locally instead of via GitHub Pages URL — "
                       "links worked locally but broke on the live site.",
            "resolution": "Use GitHub Pages URLs for all cross-scene links, not local relative paths.",
            "note": "Last time, scenes were linked locally and broke on the live site. "
                    "Use GitHub Pages URLs, not local paths.",
            "tags": ["github_pages", "file_management", "links", "scene"],
            "severity": "warning",
        },
        {
            "trigger": "untested_push_to_main",
            "context": "Pushing changes directly to main/master branch",
            "mistake": "Pushed untested changes to main — broke the live site.",
            "resolution": "Confirm that changes were tested (or explicitly acknowledged as untested) "
                          "before pushing to main.",
            "note": "You're about to push to main. Confirm this was tested or that Travis "
                    "has acknowledged the risk.",
            "tags": ["github", "testing", "deployment"],
            "severity": "critical",
        },
        {
            "trigger": "goal_not_confirmed",
            "context": "Starting a task without confirming what success looks like",
            "mistake": "Began implementation without aligning on the goal — "
                       "spent time on the wrong thing.",
            "resolution": "Before starting complex tasks, restate the goal and confirm with Travis.",
            "note": "Before diving in — is the goal confirmed? "
                    "Restate what success looks like to avoid rework.",
            "tags": ["communication", "workflow", "planning"],
            "severity": "info",
        },
        {
            "trigger": "discord_message_tone",
            "context": "Sending Discord messages on behalf of Andrew",
            "mistake": "Message tone was too formal / didn't match Andrew's voice.",
            "resolution": "Match Andrew's casual, direct tone. Read back the draft before sending.",
            "note": "Check the tone of this message matches Andrew's voice — "
                    "casual and direct, not formal.",
            "tags": ["discord", "communication", "tone"],
            "severity": "info",
        },
        {
            "trigger": "force_push_history_rewrite",
            "context": "git push --force on a shared branch",
            "mistake": "Force-pushed and overwrote a collaborator's commits.",
            "resolution": "Never force-push to shared branches without explicit confirmation. "
                          "Use --force-with-lease if truly necessary.",
            "note": "Force push detected! This rewrites history. "
                    "Confirm no collaborators are on this branch before proceeding.",
            "tags": ["github", "git", "destructive"],
            "severity": "critical",
        },
    ]
    entries = []
    for s in seeds:
        e = GuidanceEntry(**s, created_at=now)
        entries.append(e)
    return entries


# ---------------------------------------------------------------------------
# CLI entry point (quick test / manual check)
# ---------------------------------------------------------------------------

async def _demo() -> None:
    """Quick demo showing the system in action."""
    monitor = ActionMonitor()

    print("=== Process Guidance System — Demo ===\n")

    # Simulate: about to write gallery-menu.html
    result = await guided_write_file(
        "C:/projects/eve-site/gallery-menu.html",
        "<html>new gallery menu</html>",
        monitor=monitor,
    )
    print("guided_write_file result:")
    print(result[:400])
    print()

    # Simulate: about to git push to main
    result = await guided_run_command("git push origin main", monitor=monitor)
    print("guided_run_command (git push) result:")
    print(result[:400])
    print()

    # Simulate: Discord message
    result = await guided_send_discord_message(
        "general",
        "Hey just pushed some updates to the gallery scene",
        monitor=monitor,
    )
    print("guided_send_discord_message result:")
    print(result[:400])
    print()

    monitor.end_session()
    print("Demo complete. Run learn_from_session() to add new learnings.")


if __name__ == "__main__":
    asyncio.run(_demo())
