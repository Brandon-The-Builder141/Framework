from pathlib import Path
import pytest
from src import artifact_memory


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(artifact_memory, "ARTIFACTS_PATH", tmp_path / "artifacts.json")


def test_record_artifact_tracks_verified_file(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    target = tmp_path / "andrew's projects" / "ideas" / "My_Ideas.txt"
    target.parent.mkdir(parents=True)
    target.write_text("ideas", encoding="utf-8")

    artifact = artifact_memory.record_artifact(str(target), summary="Idea list")
    loaded = artifact_memory.get_artifact("My_Ideas")

    assert artifact.exists is True
    assert artifact.size_bytes == 5
    assert artifact.category == "ideas"
    assert loaded is not None
    assert loaded.path == str(target.resolve())
    assert "Idea list" in artifact_memory.format_artifact(loaded)


def test_list_artifacts_filters_category(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    schedule = tmp_path / "schedule.txt"
    journal = tmp_path / "journal.txt"
    schedule.write_text("schedule", encoding="utf-8")
    journal.write_text("journal", encoding="utf-8")

    artifact_memory.record_artifact(str(schedule), category="schedule")
    artifact_memory.record_artifact(str(journal), category="journal")

    assert [a.category for a in artifact_memory.list_artifacts("schedule")] == ["schedule"]
    assert len(artifact_memory.list_artifacts()) == 2


def test_search_artifacts_matches_title_summary_and_path(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    target = tmp_path / "proactive_outreach_prompt.txt"
    target.write_text("prompt", encoding="utf-8")
    artifact_memory.record_artifact(str(target), summary="Proactive outreach build prompt")

    hits = artifact_memory.search_artifacts("outreach")

    assert len(hits) == 1
    assert hits[0].title == "proactive_outreach_prompt.txt"


def test_markdown_section_parsing_and_reassembly(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    content = """# Title
Some text here.

## Subsection
More text.

### Subsubsection
Even more text.
"""
    target = tmp_path / "doc.md"
    target.write_text(content, encoding="utf-8")
    
    art = artifact_memory.record_artifact(str(target))
    assert art.content_type == "document"
    assert len(art.sections) == 3
    assert art.sections[0]["id"] == "h1-title"
    assert art.sections[0]["title"] == "Title"
    
    # Reassembly check
    reassembled = "".join(s["content"] for s in art.sections)
    assert reassembled == content


def test_section_level_update_and_history(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    content = """# Section A
Content A
# Section B
Content B
"""
    target = tmp_path / "doc.md"
    target.write_text(content, encoding="utf-8")
    
    art = artifact_memory.record_artifact(str(target))
    assert len(art.sections) == 2
    assert art.sections[1]["id"] == "h1-section-b"
    assert art.sections[1]["version"] == 1
    
    # Edit Section B
    msg = artifact_memory.update_artifact_section(str(target), "h1-section-b", "# Section B\nNew Content B\n")
    assert "Successfully updated" in msg
    
    # Reload and verify
    loaded = artifact_memory.get_artifact(str(target))
    assert loaded.sections[1]["content"] == "# Section B\nNew Content B\n"
    assert loaded.sections[1]["version"] == 2
    assert len(loaded.history) == 2  # create, edit_section
    assert loaded.history[-1]["action"] == "edit_section"
    
    # Verify file on disk
    disk_content = target.read_text(encoding="utf-8")
    assert disk_content == "# Section A\nContent A\n# Section B\nNew Content B\n"


def test_tags_and_querying_and_audit_logs(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    
    # Set the audit log path dynamically
    audit_file = tmp_path / "artifacts_audit.jsonl"
    monkeypatch.setattr(artifact_memory, "get_audit_log_path", lambda: audit_file)
    
    target = tmp_path / "tests" / "test_module.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_dummy(): pass\n", encoding="utf-8")
    
    # Record with custom tags
    art = artifact_memory.record_artifact(
        str(target),
        tags=["custom", "dummy-test"],
        source="unit_test_suite"
    )
    
    # Verify auto-inferred and custom tags
    assert "py" in art.tags
    assert "code" in art.tags
    assert "custom" in art.tags
    assert "dummy-test" in art.tags
    assert "tests" in art.tags
    
    # Verify audit log was written
    assert audit_file.exists()
    audit_lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) == 1
    import json
    log_entry = json.loads(audit_lines[0])
    assert log_entry["action"] == "create"
    assert log_entry["artifact_id"] == art.id
    assert "dummy-test" in log_entry["details"]["tags"]
    
    # Verify query_artifacts filters
    # Match by single tag
    results = artifact_memory.query_artifacts(tag="custom")
    assert len(results) == 1
    assert results[0].id == art.id
    
    # Match by multiple tags
    results2 = artifact_memory.query_artifacts(tags=["custom", "py", "tests"])
    assert len(results2) == 1
    
    # Mismatch by tags
    results3 = artifact_memory.query_artifacts(tags=["custom", "nonexistent"])
    assert len(results3) == 0
    
    # Match by name
    results4 = artifact_memory.query_artifacts(name="test_module")
    assert len(results4) == 1
    
    # Match by type
    results5 = artifact_memory.query_artifacts(content_type="code")
    assert len(results5) == 1
    
    # Search artifacts matching tags
    hits = artifact_memory.search_artifacts("dummy-test")
    assert len(hits) == 1
    assert hits[0].id == art.id
