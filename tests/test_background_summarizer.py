import asyncio
import os
import shutil
import pytest
from pathlib import Path
from datetime import datetime

from config.settings import RESEARCH_OUTPUT_DIR
from src.agent.memory_db import close_all, get_connection
from src.tools.subagents import SubAgentManager


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    """Isolate all database and file operations under a temp data directory."""
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy live backend configuration files to the isolated profile directory
    # so that the subagent subprocess knows which LLM to query and has the API key.
    live_profile_dir = Path("data/profiles/default")
    test_profile_dir = test_data_dir / "profiles" / "default"
    test_profile_dir.mkdir(parents=True, exist_ok=True)
    
    for f in ["backend_registry.json", "backend_state.json"]:
        src_file = live_profile_dir / f
        if src_file.exists():
            shutil.copy2(src_file, test_profile_dir / f)
            
    # 2. Update config settings in parent process
    import config.settings
    monkeypatch.setattr(config.settings, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(config.settings, "MEMORY_DIR", test_data_dir / "memory")
    monkeypatch.setattr(config.settings, "USER_PROFILES_DIR", test_data_dir / "profiles")
    monkeypatch.setattr(config.settings, "RESEARCH_OUTPUT_DIR", test_data_dir / "research_output")
    
    # Recreate subdirectories in the test temp directory
    for d in [test_data_dir / "memory", test_data_dir / "profiles", test_data_dir / "research_output"]:
        d.mkdir(parents=True, exist_ok=True)
        
    # 3. Update paths in memory_db
    import src.agent.memory_db
    monkeypatch.setattr(src.agent.memory_db, "USER_PROFILES_DIR", test_data_dir / "profiles")
    
    # Ensure any previous connection is closed and cleared
    close_all()
    
    # 4. Set the AGENT_DATA_DIR env variable so the subagent child subprocess inherits it
    monkeypatch.setenv("AGENT_DATA_DIR", str(test_data_dir))
    
    yield test_data_dir
    
    # Clean up connections
    close_all()


@pytest.mark.asyncio
async def test_session_summary_mode():
    # 1. Insert a mock session and some mock episodic memory messages in the isolated test DB
    conn = get_connection("default")
    session_id = "test_session_123"
    
    conn.execute(
        "INSERT INTO sessions (id, source, title, started_at, last_activity_at) "
        "VALUES (?, 'cli', 'Mock Session Title', '2026-05-23 00:00:00.000000', '2026-05-23 00:05:00.000000')",
        (session_id,)
    )
    
    messages = [
        ("mem_1", "user", "Hello Andrew! Can you help me write a quick Python script?"),
        ("mem_2", "assistant", "Sure! I can help you write python scripts. What do you need?"),
        ("mem_3", "user", "I need a simple hello world script.")
    ]
    for mid, role, content in messages:
        conn.execute(
            "INSERT INTO episodic_memory (id, session_id, role, content, source, importance, strength, created_at) "
            "VALUES (?, ?, ?, ?, 'cli', 0.8, 1.0, '2026-05-23 00:01:00.000000')",
            (mid, session_id, role, content)
        )
    
    # Spawn sub-agent
    manager = SubAgentManager()
    script_path = "scripts/background_summarizer.py"
    
    aid = manager.spawn(
        task="Test session summary",
        script_path=script_path,
        args=["--type", "session", "--session-id", session_id]
    )
    
    assert aid in manager.agents
    agent = manager.agents[aid]
    
    # Wait for completion (timeout 30 seconds)
    timeout = 30
    elapsed = 0
    while agent.status == "running" and elapsed < timeout:
        await asyncio.sleep(0.5)
        elapsed += 0.5
        
    output_str = "".join(agent.output)
    print("Session summarizer output:\n", output_str)
    
    assert agent.status == "completed", f"Subagent failed: {agent.status}. Output: {output_str}"
    assert "[Progress 0%]" in output_str
    assert "[Progress 20%]" in output_str
    assert "[Progress 100%]" in output_str
    
    # Verify report is written to isolated RESEARCH_OUTPUT_DIR
    import config.settings
    latest_report = config.settings.RESEARCH_OUTPUT_DIR / "session_summary_latest.md"
    assert latest_report.exists()
    report_content = latest_report.read_text(encoding="utf-8")
    assert len(report_content) > 0


@pytest.mark.asyncio
async def test_file_summary_mode(tmp_path):
    # Create a mock text file
    mock_file = tmp_path / "important_document.txt"
    mock_file.write_text(
        "This is an extremely important document about rocket science.\n"
        "It details the propulsion mechanics and thermodynamics of hybrid fuel engines.\n",
        encoding="utf-8"
    )
    
    # Spawn sub-agent
    manager = SubAgentManager()
    script_path = "scripts/background_summarizer.py"
    
    aid = manager.spawn(
        task="Test file summary",
        script_path=script_path,
        args=["--type", "file", "--path", str(mock_file)]
    )
    
    assert aid in manager.agents
    agent = manager.agents[aid]
    
    # Wait for completion (timeout 30 seconds)
    timeout = 30
    elapsed = 0
    while agent.status == "running" and elapsed < timeout:
        await asyncio.sleep(0.5)
        elapsed += 0.5
        
    output_str = "".join(agent.output)
    print("File summarizer output:\n", output_str)
    
    assert agent.status == "completed", f"Subagent failed: {agent.status}. Output: {output_str}"
    assert "[Progress 0%]" in output_str
    assert "[Progress 20%]" in output_str
    assert "[Progress 100%]" in output_str
    
    import config.settings
    latest_report = config.settings.RESEARCH_OUTPUT_DIR / "file_summary_latest.md"
    assert latest_report.exists()
    report_content = latest_report.read_text(encoding="utf-8")
    assert len(report_content) > 0


@pytest.mark.asyncio
async def test_directory_summary_mode(tmp_path):
    # Create a mock directory with space in path
    mock_dir = tmp_path / "mock space directory"
    mock_dir.mkdir()
    
    file_a = mock_dir / "module_a.py"
    file_a.write_text("def run_calculation():\n    return 42\n", encoding="utf-8")
    
    file_b = mock_dir / "notes.txt"
    file_b.write_text("General notes on architecture and modules.\n", encoding="utf-8")
    
    # Spawn sub-agent
    manager = SubAgentManager()
    script_path = "scripts/background_summarizer.py"
    
    aid = manager.spawn(
        task="Test directory summary",
        script_path=script_path,
        args=["--type", "directory", "--path", str(mock_dir)]
    )
    
    assert aid in manager.agents
    agent = manager.agents[aid]
    
    # Wait for completion (timeout 30 seconds)
    timeout = 30
    elapsed = 0
    while agent.status == "running" and elapsed < timeout:
        await asyncio.sleep(0.5)
        elapsed += 0.5
        
    output_str = "".join(agent.output)
    print("Directory summarizer output:\n", output_str)
    
    assert agent.status == "completed", f"Subagent failed: {agent.status}. Output: {output_str}"
    assert "[Progress 0%]" in output_str
    assert "[Progress 20%]" in output_str
    assert "[Progress 100%]" in output_str
    
    import config.settings
    latest_report = config.settings.RESEARCH_OUTPUT_DIR / "directory_summary_latest.md"
    assert latest_report.exists()
    report_content = latest_report.read_text(encoding="utf-8")
    assert len(report_content) > 0
