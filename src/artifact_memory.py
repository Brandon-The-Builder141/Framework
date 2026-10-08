"""Durable memory for files and documents Andrew creates or verifies."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import USER_PROFILES_DIR

ARTIFACTS_PATH = USER_PROFILES_DIR / "default" / "artifacts.json"


def get_artifacts_path() -> Path:
    """Resolve artifacts registry path. Honors monkeypatched ARTIFACTS_PATH for tests."""
    import config.settings
    default_expected = config.settings.USER_PROFILES_DIR / "default" / "artifacts.json"
    if "ARTIFACTS_PATH" in globals() and ARTIFACTS_PATH != default_expected:
        return ARTIFACTS_PATH
    return config.settings.USER_PROFILES_DIR / "default" / "artifacts.json"


def get_audit_log_path() -> Path:
    """Resolve artifacts audit log path."""
    import config.settings
    return config.settings.USER_PROFILES_DIR / "default" / "artifacts_audit.jsonl"


def _log_audit_event(action: str, path: str, artifact_id: str, details: dict[str, Any]) -> None:
    """Write an audit log event for artifact operations."""
    event = {
        "timestamp": _now(),
        "action": action,
        "path": path,
        "artifact_id": artifact_id,
        "details": details
    }
    p = get_audit_log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _now() -> str:
    return datetime.now().isoformat()


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return value or "artifact"


def infer_category(path: str, title: str = "") -> str:
    blob = f"{path} {title}".lower()
    if "schedule" in blob:
        return "schedule"
    if "journal" in blob:
        return "journal"
    if "build_prompt" in blob or "build-prompt" in blob or "prompt" in blob:
        return "build_prompt"
    if "idea" in blob:
        return "ideas"
    if "contact" in blob:
        return "contacts"
    if "journey" in blob or "genesis" in blob:
        return "story"
    return "document"


def infer_content_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in (".py", ".js", ".ts", ".go", ".c", ".cpp", ".java", ".html", ".css", ".sh", ".ps1", ".bat"):
        return "code"
    if ext in (".md", ".txt", ".json", ".xml", ".yaml", ".yml", ".csv"):
        return "document"
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        return "image"
    return "file"


def parse_sections(content: str, path: str) -> list[dict[str, Any]]:
    """Parse text contents of a file into a list of logical sections.
    
    Guarantees byte-perfect reconstruction via "".join(sec["content"] for sec in sections).
    """
    if not content:
        return [{"id": "main", "title": "Main Content", "content": "", "version": 1, "updated_at": _now()}]

    ext = Path(path).suffix.lower()
    sections: list[dict[str, Any]] = []

    if ext == ".md":
        lines = content.splitlines(keepends=True)
        current_sec_id = "preamble"
        current_sec_title = "Preamble"
        current_sec_lines: list[str] = []

        for line in lines:
            match = re.match(r"^(#+)\s+(.*)$", line)
            if match:
                if current_sec_lines or current_sec_id != "preamble":
                    sections.append({
                        "id": current_sec_id,
                        "title": current_sec_title,
                        "content": "".join(current_sec_lines)
                    })
                header_level = len(match.group(1))
                title = match.group(2).strip()
                current_sec_id = _slug(f"h{header_level}-{title}")
                current_sec_title = title
                current_sec_lines = [line]
            else:
                current_sec_lines.append(line)

        if current_sec_lines or current_sec_id != "preamble":
            sections.append({
                "id": current_sec_id,
                "title": current_sec_title,
                "content": "".join(current_sec_lines)
            })

    elif ext in (".py", ".js", ".ts", ".html", ".css", ".go", ".c", ".cpp", ".java"):
        lines = content.splitlines(keepends=True)
        has_markers = any(re.search(r"(?:#|//|/\*)\s*SECTION:\s*", line, re.IGNORECASE) for line in lines)

        if has_markers:
            current_sec_id = "preamble"
            current_sec_title = "Preamble"
            current_sec_lines = []
            for line in lines:
                match = re.search(r"(?:#|//|/\*)\s*SECTION:\s*(.+?)(?:\s*\*\/)?$", line, re.IGNORECASE)
                if match:
                    if current_sec_lines or current_sec_id != "preamble":
                        sections.append({
                            "id": current_sec_id,
                            "title": current_sec_title,
                            "content": "".join(current_sec_lines)
                        })
                    title = match.group(1).strip()
                    current_sec_id = _slug(title)
                    current_sec_title = title
                    current_sec_lines = [line]
                else:
                    current_sec_lines.append(line)
            if current_sec_lines or current_sec_id != "preamble":
                sections.append({
                    "id": current_sec_id,
                    "title": current_sec_title,
                    "content": "".join(current_sec_lines)
                })
        else:
            if ext == ".py":
                current_sec_id = "preamble"
                current_sec_title = "Preamble"
                current_sec_lines = []
                for line in lines:
                    match = re.match(r"^(class|def)\s+([a-zA-Z0-9_]+)", line)
                    if match:
                        if current_sec_lines or current_sec_id != "preamble":
                            sections.append({
                                "id": current_sec_id,
                                "title": current_sec_title,
                                "content": "".join(current_sec_lines)
                            })
                        kind = match.group(1)
                        name = match.group(2)
                        current_sec_id = _slug(f"{kind}-{name}")
                        current_sec_title = f"{kind.capitalize()}: {name}"
                        current_sec_lines = [line]
                    else:
                        current_sec_lines.append(line)
                if current_sec_lines or current_sec_id != "preamble":
                    sections.append({
                        "id": current_sec_id,
                        "title": current_sec_title,
                        "content": "".join(current_sec_lines)
                    })
            elif ext in (".js", ".ts"):
                current_sec_id = "preamble"
                current_sec_title = "Preamble"
                current_sec_lines = []
                for line in lines:
                    match = re.match(r"^(class|function|async\s+function|const|let|var)\s+([a-zA-Z0-9_]+)", line)
                    is_sec = False
                    if match:
                        kind = match.group(1)
                        name = match.group(2)
                        if kind in ("class", "function", "async function"):
                            is_sec = True
                        elif "=>" in line or "function" in line:
                            is_sec = True
                    if is_sec:
                        if current_sec_lines or current_sec_id != "preamble":
                            sections.append({
                                "id": current_sec_id,
                                "title": current_sec_title,
                                "content": "".join(current_sec_lines)
                            })
                        current_sec_id = _slug(f"{kind}-{name}")
                        current_sec_title = f"{kind.capitalize()}: {name}"
                        current_sec_lines = [line]
                    else:
                        current_sec_lines.append(line)
                if current_sec_lines or current_sec_id != "preamble":
                    sections.append({
                        "id": current_sec_id,
                        "title": current_sec_title,
                        "content": "".join(current_sec_lines)
                    })
            else:
                sections.append({
                    "id": "main",
                    "title": "Main Content",
                    "content": content
                })
    else:
        sections.append({
            "id": "main",
            "title": "Main Content",
            "content": content
        })

    # Hydrate versions and timestamps
    for s in sections:
        s.setdefault("version", 1)
        s.setdefault("updated_at", _now())

    return sections


@dataclass
class Artifact:
    id: str
    path: str
    title: str
    category: str = "document"
    content_type: str = "file"
    summary: str = ""
    exists: bool = True
    size_bytes: int = 0
    source: str = "agent"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    verified_at: str = field(default_factory=_now)
    sections: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifact":
        return cls(
            id=str(data.get("id") or ""),
            path=str(data.get("path") or ""),
            title=str(data.get("title") or ""),
            category=str(data.get("category") or "document"),
            content_type=str(data.get("content_type") or "file"),
            summary=str(data.get("summary") or ""),
            exists=bool(data.get("exists", True)),
            size_bytes=int(data.get("size_bytes") or 0),
            source=str(data.get("source") or "agent"),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
            verified_at=str(data.get("verified_at") or _now()),
            sections=list(data.get("sections") or []),
            history=list(data.get("history") or []),
            tags=list(data.get("tags") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load() -> dict[str, Any]:
    path = get_artifacts_path()
    if not path.exists():
        return {"artifacts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("artifacts"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"artifacts": {}}


def _save(data: dict[str, Any]) -> None:
    path = get_artifacts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["_updated"] = _now()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _artifact_id(path: str) -> str:
    return _slug(str(Path(path).expanduser().resolve(strict=False)))


def record_artifact(
    path: str,
    *,
    title: str = "",
    category: str = "",
    summary: str = "",
    source: str = "agent",
    tags: list[str] | None = None,
) -> Artifact:
    abs_path = Path(path).expanduser().resolve(strict=False)
    exists = abs_path.is_file()
    size = abs_path.stat().st_size if exists else 0
    title = title or abs_path.name
    category = category or infer_category(str(abs_path), title)
    content_type = infer_content_type(str(abs_path))
    aid = _artifact_id(str(abs_path))
    now = _now()
    
    data = _load()
    existing = data["artifacts"].get(aid, {})
    
    # Check sections & history
    parsed_secs: list[dict[str, Any]] = []
    history = list(existing.get("history") or [])
    
    if exists and content_type in ("code", "document"):
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            parsed_secs = parse_sections(content, str(abs_path))
        except OSError:
            pass

    # Compile tags
    final_tags = set(tags or [])
    
    # Auto-infer tags based on extension, category, and directory
    ext = abs_path.suffix.lower().lstrip(".")
    if ext:
        final_tags.add(ext)
    if content_type:
        final_tags.add(content_type)
    if category:
        final_tags.add(category)
    if source:
        final_tags.add(source)
        
    # Check folder directories for special tags
    for part in abs_path.parts:
        part_low = part.lower()
        if part_low in ("tests", "scripts", "src", "config", "data", "research_output"):
            final_tags.add(part_low)
            
    # Clean and sort tags
    sorted_tags = sorted(list({t.strip().lower() for t in final_tags if t.strip()}))

    # If it is an update, align new sections with old to preserve versions/timestamps
    action = "create"
    description = "Artifact registered in system registry."
    
    if existing:
        action = "update"
        description = "Artifact updated."
        if parsed_secs:
            old_secs = {s["id"]: s for s in existing.get("sections", [])}
            aligned_secs: list[dict[str, Any]] = []
            changed_sections = []
            
            for new_s in parsed_secs:
                old_s = old_secs.get(new_s["id"])
                if old_s:
                    if old_s.get("content") == new_s["content"]:
                        new_s["version"] = old_s.get("version", 1)
                        new_s["updated_at"] = old_s.get("updated_at", now)
                    else:
                        new_s["version"] = old_s.get("version", 1) + 1
                        new_s["updated_at"] = now
                        changed_sections.append(new_s["id"])
                else:
                    new_s["version"] = 1
                    new_s["updated_at"] = now
                    changed_sections.append(new_s["id"])
                aligned_secs.append(new_s)
            
            parsed_secs = aligned_secs
            if changed_sections:
                action = "edit_sections"
                description = f"Sections modified: {', '.join(changed_sections)}"
        
        # Merge with existing tags
        merged_tags = set(sorted_tags)
        merged_tags.update(existing.get("tags") or [])
        sorted_tags = sorted(list({t.strip().lower() for t in merged_tags if t.strip()}))

    # Update history log — include snapshot of old sections for rollback
    history_entry: dict[str, Any] = {
        "timestamp": now,
        "action": action,
        "description": description,
    }
    if existing and action in ("update", "edit_sections"):
        old_secs = existing.get("sections", [])
        if old_secs:
            history_entry["snapshot_sections"] = old_secs
    history.append(history_entry)
        
    artifact = Artifact(
        id=aid,
        path=str(abs_path),
        title=title,
        category=category,
        content_type=content_type,
        summary=summary or existing.get("summary", ""),
        exists=exists,
        size_bytes=size,
        source=source,
        created_at=existing.get("created_at") or now,
        updated_at=now,
        verified_at=now if exists else existing.get("verified_at") or "",
        sections=parsed_secs,
        history=history,
        tags=sorted_tags
    )
    
    data["artifacts"][aid] = artifact.to_dict()
    _save(data)
    
    # Audit log entry
    _log_audit_event(
        action=action,
        path=str(abs_path),
        artifact_id=aid,
        details={
            "title": title,
            "category": category,
            "content_type": content_type,
            "size_bytes": size,
            "source": source,
            "tags": sorted_tags,
            "description": description
        }
    )
    
    return artifact


def get_artifact(identifier: str) -> Artifact | None:
    ident = (identifier or "").strip()
    if not ident:
        return None
    data = _load().get("artifacts", {})
    if ident in data:
        return Artifact.from_dict(data[ident])
    ident_low = ident.lower()
    for raw in data.values():
        art = Artifact.from_dict(raw)
        if ident_low in art.path.lower() or ident_low in art.title.lower():
            return art
    return None


def list_artifacts(category: str = "", include_missing: bool = False) -> list[Artifact]:
    rows = [Artifact.from_dict(a) for a in _load().get("artifacts", {}).values()]
    if category:
        rows = [a for a in rows if a.category == category]
    if not include_missing:
        rows = [a for a in rows if a.exists]
    rows.sort(key=lambda a: a.updated_at, reverse=True)
    return rows


def search_artifacts(query: str, limit: int = 10) -> list[Artifact]:
    q_words = {w for w in re.findall(r"[a-zA-Z0-9']{3,}", (query or "").lower())}
    rows = list_artifacts(include_missing=True)
    if not q_words:
        return rows[:limit]

    scored: list[tuple[int, Artifact]] = []
    for art in rows:
        sections_text = " ".join(f"{s.get('title', '')} {s.get('content', '')}" for s in art.sections)
        tags_text = " ".join(art.tags)
        blob = f"{art.title} {art.category} {art.content_type} {art.summary} {art.path} {sections_text} {tags_text}".lower()
        score = sum(1 for w in q_words if w in blob)
        for w in q_words:
            if any(w == t.lower() for t in art.tags):
                score += 2
        if score:
            scored.append((score, art))
    scored.sort(key=lambda x: (x[0], x[1].updated_at), reverse=True)
    return [a for _, a in scored[:limit]]


def query_artifacts(
    *,
    name: str | None = None,
    category: str | None = None,
    content_type: str | None = None,
    tag: str | None = None,
    tags: list[str] | None = None,
    date_after: str | None = None,
    date_before: str | None = None,
    include_missing: bool = False,
) -> list[Artifact]:
    """Retrieve artifacts matching various filter criteria.
    
    Supports filtering by name/substring, category, content_type, specific tags,
    and update date ranges.
    """
    artifacts = list_artifacts(include_missing=include_missing)
    filtered = []
    
    for art in artifacts:
        if name:
            nl = name.lower()
            if nl not in art.title.lower() and nl not in art.path.lower():
                continue
                
        if category and art.category.lower() != category.lower():
            continue
            
        if content_type and art.content_type.lower() != content_type.lower():
            continue
            
        if tag:
            tl = tag.lower()
            if not any(t.lower() == tl for t in art.tags):
                continue
                
        if tags:
            match_all = True
            art_tags_low = [t.lower() for t in art.tags]
            for req_t in tags:
                if req_t.lower() not in art_tags_low:
                    match_all = False
                    break
            if not match_all:
                continue
                
        if date_after:
            try:
                if art.updated_at < date_after:
                    continue
            except Exception:
                pass
                
        if date_before:
            try:
                if art.updated_at > date_before:
                    continue
            except Exception:
                pass
                
        filtered.append(art)
        
    return filtered


def format_artifact(artifact: Artifact) -> str:
    status = "exists" if artifact.exists else "missing"
    lines = [
        f"{artifact.title} [{artifact.category} / {artifact.content_type}] ({status}, {artifact.size_bytes} bytes)",
        f"ID: {artifact.id}",
        f"Path: {artifact.path}",
    ]
    if artifact.tags:
        lines.append(f"Tags: {', '.join(artifact.tags)}")
    if artifact.summary:
        lines.append(f"Summary: {artifact.summary}")
    if artifact.sections:
        lines.append("Sections:")
        for s in artifact.sections:
            lines.append(f"  - [{s.get('id')}] {s.get('title')} (v{s.get('version')})")
    lines.append(f"Verified: {artifact.verified_at or 'never'}")
    return "\n".join(lines)


def format_for_context(limit: int = 8) -> str:
    artifacts = list_artifacts(include_missing=False)[:limit]
    if not artifacts:
        return ""
    lines = ["## Saved Files / Artifacts (durable memory)"]
    for art in artifacts:
        lines.append(f"- {art.title} [{art.category} / {art.content_type}] (ID: {art.id}) -> {art.path}")
    return "\n".join(lines)


def update_artifact_section(identifier: str, section_id: str, new_content: str) -> str:
    """Update a specific section of an artifact independently and write back to disk."""
    artifact = get_artifact(identifier)
    if not artifact:
        return f"Error: Artifact '{identifier}' not found."
    
    if not artifact.exists:
        return f"Error: File does not exist on disk at {artifact.path}."
    
    sections = artifact.sections
    if not sections:
        sections = [{"id": "main", "title": "Main Content", "content": "", "version": 1, "updated_at": _now()}]
        
    target_idx = -1
    for idx, s in enumerate(sections):
        if s.get("id") == section_id:
            target_idx = idx
            break
            
    if target_idx == -1:
        return f"Error: Section '{section_id}' not found in artifact '{artifact.title}'."
        
    now = _now()
    old_content = sections[target_idx].get("content", "")
    if old_content == new_content:
        return f"No changes to section '{section_id}' in artifact '{artifact.title}'."

    # Snapshot all sections before modifying (enables rollback)
    sections_snapshot = [dict(s) for s in sections]

    # Update section
    sections[target_idx]["content"] = new_content
    sections[target_idx]["version"] = sections[target_idx].get("version", 1) + 1
    sections[target_idx]["updated_at"] = now
    
    # Reassemble file
    full_content = "".join(sec.get("content", "") for sec in sections)
    abs_path = Path(artifact.path)
    
    # Safe/atomic write to disk
    tmp_path = None
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{abs_path.name}.", suffix=".tmp", dir=str(abs_path.parent)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(full_content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, abs_path)
        tmp_path = None  # ownership transferred
    except Exception as e:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return f"Error: failed to write section update to disk at {abs_path}: {e}"
        
    # Record metadata update
    data = _load()
    artifact.size_bytes = abs_path.stat().st_size
    artifact.updated_at = now
    artifact.verified_at = now
    artifact.sections = sections
    
    action = "edit_section"
    description = f"Section '{section_id}' content updated independently."
    
    artifact.history.append({
        "timestamp": now,
        "action": action,
        "section_id": section_id,
        "description": description,
        "snapshot_sections": sections_snapshot,
    })
    
    data["artifacts"][artifact.id] = artifact.to_dict()
    _save(data)
    
    # Audit log entry
    _log_audit_event(
        action=action,
        path=str(abs_path),
        artifact_id=artifact.id,
        details={
            "title": artifact.title,
            "category": artifact.category,
            "content_type": artifact.content_type,
            "size_bytes": artifact.size_bytes,
            "source": artifact.source,
            "tags": artifact.tags,
            "section_id": section_id,
            "description": description
        }
    )
    
    return f"Successfully updated section '{section_id}' in artifact '{artifact.title}' and verified write to disk."


def rollback_artifact(identifier: str, steps: int = 1) -> str:
    """Restore an artifact's file on disk to a prior version using history snapshots.

    Each call to update_artifact_section or record_artifact (update) stores a
    snapshot_sections entry in history.  steps=1 restores the most recent snapshot,
    steps=2 restores the one before that, etc.
    """
    artifact = get_artifact(identifier)
    if not artifact:
        return f"Error: Artifact '{identifier}' not found."
    if not artifact.exists:
        return f"Error: File does not exist on disk at {artifact.path}."

    snapshots = [h for h in reversed(artifact.history) if "snapshot_sections" in h]
    if not snapshots:
        return f"Error: No rollback snapshots available for '{artifact.title}'."

    steps = max(1, min(steps, len(snapshots)))
    target = snapshots[steps - 1]
    old_sections: list[dict[str, Any]] = target["snapshot_sections"]

    full_content = "".join(sec.get("content", "") for sec in old_sections)
    abs_path = Path(artifact.path)

    tmp_path: Path | None = None
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{abs_path.name}.", suffix=".tmp", dir=str(abs_path.parent)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(full_content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, abs_path)
        tmp_path = None
    except Exception as e:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return f"Error: rollback write failed for {abs_path}: {e}"

    now = _now()
    restored_secs = [{**s, "updated_at": now} for s in old_sections]
    data = _load()
    artifact.sections = restored_secs
    artifact.size_bytes = abs_path.stat().st_size
    artifact.updated_at = now
    artifact.verified_at = now
    artifact.history.append({
        "timestamp": now,
        "action": "rollback",
        "description": f"Rolled back {steps} step(s) to state from {target['timestamp']}.",
    })
    data["artifacts"][artifact.id] = artifact.to_dict()
    _save(data)

    _log_audit_event(
        action="rollback",
        path=str(abs_path),
        artifact_id=artifact.id,
        details={
            "steps": steps,
            "restored_from": target["timestamp"],
            "size_bytes": artifact.size_bytes,
        },
    )

    return (
        f"Rolled back '{artifact.title}' {steps} step(s) to state from "
        f"{target['timestamp']}. {artifact.size_bytes} bytes restored to {abs_path}."
    )
