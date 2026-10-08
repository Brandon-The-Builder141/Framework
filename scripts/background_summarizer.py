"""LLM-powered Background Summarizer Sub-Agent.

Summarizes active chat sessions, files, or directories using the active LLM
provider and logs them as artifacts in the registry.
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path so we can import local modules
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from openai import AsyncOpenAI
from src.backend_switching import get_active_backend
from src.agent.memory_db import get_connection
from config.settings import RESEARCH_OUTPUT_DIR


async def summarize_text(client: AsyncOpenAI, model: str, system_prompt: str, user_content: str) -> str:
    """Helper to query the LLM for a summary."""
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Error: LLM query failed: {e}"


async def handle_session_summary(client: AsyncOpenAI, model: str, session_id: str | None) -> tuple[str, str]:
    """Retrieve chat history from SQLite and summarize the session."""
    print("[Progress 20%] Querying memory database connection...", flush=True)
    conn = get_connection("default")
    
    if not session_id:
        print("[Progress 30%] Finding most recent active session...", flush=True)
        row = conn.execute("SELECT id, title, started_at FROM sessions ORDER BY last_activity_at DESC LIMIT 1").fetchone()
        if not row:
            return "Error: No active sessions found in database.", ""
        session_id = row["id"]
        session_title = row["title"] or "Unnamed Session"
        started_at = row["started_at"]
    else:
        print(f"[Progress 30%] Retrieving session '{session_id}'...", flush=True)
        row = conn.execute("SELECT title, started_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        session_title = row["title"] if row else "Session"
        started_at = row["started_at"] if row else "Unknown time"

    print(f"[Progress 40%] Loading messages for session: {session_id}", flush=True)
    rows = conn.execute(
        "SELECT role, content, created_at FROM episodic_memory "
        "WHERE session_id = ? AND deleted_at IS NULL ORDER BY created_at ASC",
        (session_id,)
    ).fetchall()
    
    if not rows:
        return f"Error: No messages found for session '{session_id}'.", session_id

    # Format dialogue
    dialog_lines = []
    for r in rows:
        role_label = "User" if r["role"] == "user" else "Andrew" if r["role"] == "assistant" else r["role"].capitalize()
        dialog_lines.append(f"[{r['created_at']}] {role_label}: {r['content']}")
    dialogue = "\n".join(dialog_lines)
    
    # Cap dialog content if too long
    if len(dialogue) > 15000:
        dialogue = dialogue[:8000] + "\n\n... [TRUNCATED] ...\n\n" + dialogue[-7000:]

    print("[Progress 60%] Requesting dialogue summary from LLM...", flush=True)
    system_prompt = (
        "You are a Senior Technical Project Manager.\n"
        "Summarize the following chat dialogue session between the user and Andrew.\n"
        "Compile a clean, formatted Markdown summary report that outlines:\n"
        "1. '# Session Summary: [Title]'\n"
        "2. '## Session Metadata' (Session ID, start date, message count)\n"
        "3. '## Objectives' (what the user wanted to accomplish)\n"
        "4. '## Tasks Completed' (specific actions Andrew took, code written, tools run)\n"
        "5. '## Key Decisions & Findings'\n"
        "6. '## Action Items & Next Steps'"
    )
    user_content = f"Session ID: {session_id}\nStarted At: {started_at}\n\nDialogue:\n{dialogue}"
    
    summary = await summarize_text(client, model, system_prompt, user_content)
    return summary, session_id


async def handle_file_summary(client: AsyncOpenAI, model: str, file_path_str: str) -> tuple[str, str]:
    """Read a specific file and summarize its content."""
    p = Path(file_path_str).resolve()
    print(f"[Progress 20%] Verifying file existence: {p}...", flush=True)
    if not p.exists() or not p.is_file():
        return f"Error: File '{p}' does not exist or is not a file.", ""
        
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Error: Could not read file: {e}", ""
        
    if len(content) > 15000:
        content = content[:8000] + "\n\n... [TRUNCATED] ...\n\n" + content[-7000:]
        
    print(f"[Progress 50%] Requesting file summary from LLM...", flush=True)
    system_prompt = (
        "You are a Tech Lead.\n"
        "Summarize the provided document content concisely. Write a Markdown report containing:\n"
        "1. '# Document Summary: [Filename]'\n"
        "2. '## Overview'\n"
        "3. '## Key Findings & Core Concepts'\n"
        "4. '## Technical Details' (if applicable)\n"
        "5. '## Summary Conclusion'"
    )
    user_content = f"Filename: {p.name}\nPath: {p}\n\nContent:\n{content}"
    
    summary = await summarize_text(client, model, system_prompt, user_content)
    return summary, p.name


async def handle_directory_summary(client: AsyncOpenAI, model: str, dir_path_str: str) -> tuple[str, str]:
    """Crawl a directory, extract structure/content, and generate a summary report."""
    p = Path(dir_path_str).resolve()
    print(f"[Progress 20%] Verifying directory existence: {p}...", flush=True)
    if not p.exists() or not p.is_dir():
        return f"Error: Directory '{p}' does not exist or is not a directory.", ""
        
    # Gather a listing of files in the directory (shallow crawl)
    files = []
    try:
        for entry in p.iterdir():
            if entry.is_file() and not entry.name.startswith("."):
                files.append(entry)
    except OSError as e:
        return f"Error: Could not list directory: {e}", ""
        
    file_list_str = "\n".join(f"- {f.name} ({f.stat().st_size} bytes)" for f in sorted(files, key=lambda x: x.name))
    
    # Read first 80 lines of the top 5 files to give context
    context_blocks = []
    for f in sorted(files, key=lambda x: x.name)[:5]:
        try:
            head = f.read_text(encoding="utf-8", errors="replace").splitlines()[:80]
            context_blocks.append(f"--- File: {f.name} ---\n" + "\n".join(head))
        except OSError:
            pass
            
    context = "\n\n".join(context_blocks)
    
    print(f"[Progress 60%] Requesting directory summary from LLM...", flush=True)
    system_prompt = (
        "You are a Principal Architect.\n"
        "Generate a structured Markdown report summarizing the contents of this directory.\n"
        "Include the following sections:\n"
        "1. '# Directory Summary: [Directory Name]'\n"
        "2. '## Overview'\n"
        "3. '## Directory Structure & File List'\n"
        "4. '## Core Contents Analysis' (reviewing file samples)\n"
        "5. '## Recommendations or Comments'"
    )
    user_content = f"Directory: {p.name}\nPath: {p}\n\nFiles found:\n{file_list_str}\n\nSamples:\n{context}"
    
    summary = await summarize_text(client, model, system_prompt, user_content)
    return summary, p.name


async def main():
    parser = argparse.ArgumentParser(description="Background Summarizer Sub-Agent")
    parser.add_argument("--type", choices=["session", "file", "directory"], default="session")
    parser.add_argument("--path", help="Path to file or directory to summarize")
    parser.add_argument("--session-id", help="Session ID to summarize")
    
    # Ignore flags that subagent spawner might pass by accident
    parsed_args, unknown = parser.parse_known_args()
    
    print(f"[Progress 0%] Commencing background summarization (mode: {parsed_args.type})...", flush=True)
    
    # Setup API client
    try:
        active = get_active_backend(user_id="default")
        api_key = active.api_key
        base_url = active.base_url
        model = active.model
    except Exception as e:
        print(f"Error loading LLM configuration: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
        
    if not api_key:
        print("Error: No active API key found.", file=sys.stderr, flush=True)
        sys.exit(1)
        
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    
    # Routing based on type
    if parsed_args.type == "session":
        summary, identifier = await handle_session_summary(client, model, parsed_args.session_id)
    elif parsed_args.type == "file":
        if not parsed_args.path:
            print("Error: --path is required for file summary mode.", file=sys.stderr, flush=True)
            sys.exit(1)
        summary, identifier = await handle_file_summary(client, model, parsed_args.path)
    elif parsed_args.type == "directory":
        if not parsed_args.path:
            print("Error: --path is required for directory summary mode.", file=sys.stderr, flush=True)
            sys.exit(1)
        summary, identifier = await handle_directory_summary(client, model, parsed_args.path)
    else:
        print(f"Error: Invalid mode: {parsed_args.type}", file=sys.stderr, flush=True)
        sys.exit(1)
        
    if summary.startswith("Error"):
        print(summary, file=sys.stderr, flush=True)
        sys.exit(1)
        
    # Save Report
    print("[Progress 80%] Writing summary report file...", flush=True)
    RESEARCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    safe_id = "".join(c for c in (identifier or "summary") if c.isalnum() or c in ("-", "_")).strip()
    
    report_path = RESEARCH_OUTPUT_DIR / f"{parsed_args.type}_summary_{safe_id}_{timestamp}.md"
    latest_path = RESEARCH_OUTPUT_DIR / f"{parsed_args.type}_summary_latest.md"
    
    try:
        report_path.write_text(summary, encoding="utf-8")
        latest_path.write_text(summary, encoding="utf-8")
        print(f"[Progress 90%] Summary saved to: {report_path}", flush=True)
        
        # Log to artifact registry
        try:
            from src.artifact_memory import record_artifact
            record_artifact(
                str(latest_path),
                title=f"{parsed_args.type.capitalize()} Summary (Latest)",
                category="document",
                summary=f"Automated background {parsed_args.type} summary report generated by sub-agent.",
                source="background_summarizer_script"
            )
        except Exception:
            pass
            
        print("[Progress 100%] Summarization complete!", flush=True)
    except OSError as e:
        print(f"Error writing summary files: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted.", flush=True)
        sys.exit(130)
