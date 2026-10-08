import asyncio
import os
from pathlib import Path
import pytest
from src.tools.subagents import SubAgentManager
from config.settings import RESEARCH_OUTPUT_DIR


@pytest.mark.asyncio
async def test_subagent_realtime_logging_and_review(tmp_path):
    # Create a mock project directory with spaces to review
    mock_proj = tmp_path / "mock project space"
    mock_proj.mkdir()
    
    # Write a couple of mock files
    file_a = mock_proj / "calculator.py"
    file_a.write_text("def add(a, b):\n    # Adds two numbers\n    return a + b\n", encoding="utf-8")
    
    file_b = mock_proj / "README.md"
    file_b.write_text("# Mock Project\nThis is a test project.\n", encoding="utf-8")

    # Capture original report contents if they exist so we can restore/cleanup
    latest_report = RESEARCH_OUTPUT_DIR / "project_deep_review_latest.md"
    had_latest = latest_report.exists()
    original_latest_content = latest_report.read_text(encoding="utf-8") if had_latest else None

    # Spawn sub-agent
    manager = SubAgentManager()
    script_path = "scripts/project_deep_review.py"
    
    # Spawn and pass a flag first, and split path to mock unquoted spaces
    aid = manager.spawn(
        task="Test deep review",
        script_path=script_path,
        args=["--enable-live-output", str(mock_proj.parent / "mock"), "project", "space"]
    )
    
    assert aid in manager.agents
    agent = manager.agents[aid]
    
    # Wait for completion (timeout 30 seconds)
    timeout = 30
    elapsed = 0
    while agent.status == "running" and elapsed < timeout:
        await asyncio.sleep(0.5)
        elapsed += 0.5
        
    print("Subagent captured output:")
    print("".join(agent.output))
    
    # Assert completion and correct status
    assert agent.status == "completed", f"Subagent failed or timed out: {agent.status}. Output: {''.join(agent.output)}"
    
    # Verify that we captured logs in real-time
    output_str = "".join(agent.output)
    assert "[Progress 0%]" in output_str
    assert "Auditing: calculator.py" in output_str or "Auditing: README.md" in output_str
    assert "[Progress 100%]" in output_str
    
    try:
        # Verify output files were created in real research output directory
        assert latest_report.exists()
        report_content = latest_report.read_text(encoding="utf-8")
        assert "# Project Deep Review Report" in report_content
        assert "calculator.py" in report_content
    finally:
        # Cleanup generated test reports
        # Find the timestamped report from stdout
        for line in agent.output:
            for part in line.split():
                if "project_deep_review_" in part and part.endswith(".md"):
                    p = Path(part.strip())
                    if p.exists():
                        p.unlink()
        
        # Restore or remove latest report
        if had_latest:
            latest_report.write_text(original_latest_content, encoding="utf-8")
        else:
            if latest_report.exists():
                latest_report.unlink()
