"""LLM-powered Deep Project Review Sub-Agent.

Crawls the codebase, invokes the active LLM provider to audit code quality,
architectural alignment, and documentation completeness, and generates a
comprehensive markdown report in the research output directory.
"""
import asyncio
import json
import os
import re
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
from config.settings import RESEARCH_OUTPUT_DIR


# Directories and extensions to ignore
IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "generated_images", "logs", "data", "brain", ".gemini",
    ".idea", ".vscode", "dist", "build"
}

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".html", ".css", ".md", ".json", ".ini", ".toml", ".txt",
    ".go", ".java", ".cpp", ".c", ".cs", ".sh", ".ps1", ".bat", ".yml", ".yaml"
}


def crawl_project(root_path: Path) -> list[Path]:
    """Recursively crawl the directory and find source/doc files to review."""
    found_files: list[Path] = []
    
    for current_dir, dirs, files in os.walk(root_path):
        # In-place modify dirs to skip ignored ones
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            p = Path(current_dir) / file
            if p.suffix.lower() in ALLOWED_EXTENSIONS:
                found_files.append(p)
                
    # Sort files to prioritize config, readmes, and core source code files
    def priority_key(path: Path) -> int:
        name = path.name.lower()
        if name == "readme.md":
            return 0
        if "config" in str(path) or "settings" in str(path):
            return 1
        if "src/agent/" in str(path.as_posix()):
            return 2
        if "src/tools/" in str(path.as_posix()):
            return 3
        if "src/" in str(path.as_posix()):
            return 4
        return 5

    found_files.sort(key=priority_key)
    return found_files


async def analyze_file_with_llm(
    client: AsyncOpenAI,
    model: str,
    root_path: Path,
    file_path: Path
) -> dict:
    """Read a file and invoke the LLM to audit its structure and quality."""
    rel_path = file_path.relative_to(root_path).as_posix()
    
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"file": rel_path, "error": f"Could not read file: {e}"}
        
    # Truncate content if it is exceptionally large to conserve tokens
    lines = content.splitlines()
    if len(lines) > 400:
        content = "\n".join(lines[:200]) + "\n... [TRUNCATED] ...\n" + "\n".join(lines[-100:])
        
    system_prompt = (
        "You are a Senior Principal Software Architect and Security Auditor.\n"
        "Analyze the provided file contents and return a JSON object with the following fields:\n"
        "1. 'purpose': A brief 1-2 sentence description of what the file/component does.\n"
        "2. 'code_quality_score': An integer rating from 1 (poor) to 10 (excellent).\n"
        "3. 'code_quality_notes': A short description of quality, code smells, or issues.\n"
        "4. 'documentation_score': An integer rating from 1 (undocumented) to 10 (fully docstringed/documented).\n"
        "5. 'documentation_notes': Notes on docstrings, comment quality, and clarity.\n"
        "6. 'vulnerabilities': A list of potential bugs, security concerns, or architectural flaws.\n"
        "\n"
        "Respond ONLY with a valid JSON block. Do not include markdown code block formatting."
    )
    
    user_prompt = f"File Path: {rel_path}\n\nFile Content:\n```\n{content}\n```"
    
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )
        output = (resp.choices[0].message.content or "").strip()
        
        # Clean any accidental markdown code fences
        if output.startswith("```"):
            output = re.sub(r"^```(?:json)?\n", "", output)
            output = re.sub(r"\n```$", "", output)
            output = output.strip()
            
        data = json.loads(output)
        data["file"] = rel_path
        return data
    except Exception as e:
        return {
            "file": rel_path,
            "error": f"LLM analysis failed: {str(e)}",
            "purpose": "Unknown (failed to analyze)",
            "code_quality_score": 1,
            "code_quality_notes": f"Analysis failed: {e}",
            "documentation_score": 1,
            "documentation_notes": "",
            "vulnerabilities": []
        }


async def generate_final_report(
    client: AsyncOpenAI,
    model: str,
    project_name: str,
    analyses: list[dict]
) -> str:
    """Compile all individual file reviews into a single structured report using the LLM."""
    system_prompt = (
        "You are a Senior Principal Software Architect and Tech Lead.\n"
        "You will be given a list of file audits for a codebase. Synthesize these audits into a "
        "comprehensive, state-of-the-art markdown Project Deep Review Report.\n"
        "Ensure the report contains the following specific sections:\n"
        "1. '# Project Deep Review Report: [Project Name]'\n"
        "2. '## Executive Summary' (overall health assessment, high-level findings, system type)\n"
        "3. '## Architectural Overview' (description of components, how they interact, dependency structure)\n"
        "4. '## Detailed File Audit' (a markdown table listing each file, its purpose, quality score, and doc score)\n"
        "5. '## Code Quality & Technical Debt' (synthesized review of code quality, common code smells, patterns)\n"
        "6. '## Documentation & Test Gaps' (assessment of documentation and suggest tests)\n"
        "7. '## Actionable Recommendations' (prioritized list of specific changes, refactoring steps, and updates)\n"
        "\n"
        "Format the output beautifully in clean markdown."
    )
    
    # Send a compact summary of the analyses to the LLM to avoid context bloat
    compact_data = []
    for a in analyses:
        compact_data.append({
            "file": a.get("file"),
            "purpose": a.get("purpose"),
            "quality": a.get("code_quality_score", 5),
            "doc_score": a.get("documentation_score", 5),
            "issues": a.get("vulnerabilities", []) or a.get("error", "")
        })
        
    user_prompt = f"Project Name: {project_name}\n\nFile Audits:\n{json.dumps(compact_data, indent=2)}"
    
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        # Fallback basic report generation if LLM fails
        lines = [
            f"# Project Deep Review Report: {project_name}",
            f"\nGenerated on: {datetime.now().isoformat()}",
            "\n## Executive Summary",
            "Warning: Automated report synthesis failed. A basic listing is provided below.",
            "\n## Detailed File Audit",
            "| File | Purpose | Quality Score | Doc Score |",
            "| --- | --- | --- | --- |"
        ]
        for a in analyses:
            lines.append(
                f"| {a.get('file')} | {a.get('purpose')} | {a.get('code_quality_score')} | {a.get('documentation_score')} |"
            )
        lines.append(f"\nError details: {e}")
        return "\n".join(lines)


async def main():
    project_dir = ROOT
    enable_live_output = False
    
    # Parse command line flags vs positional arguments
    positional_args = []
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            if arg == "--enable-live-output":
                enable_live_output = True
        else:
            positional_args.append(arg)
            
    if positional_args:
        # Check if it is a multi-part path due to unquoted spaces on Windows
        # e.g., C:\Users\travi\OneDrive\Desktop\My Project -> ["C:\Users\travi\OneDrive\Desktop\My", "Project"]
        first_path = Path(positional_args[0]).resolve()
        if not first_path.exists() and len(positional_args) > 1:
            joined_str = " ".join(positional_args)
            joined_path = Path(joined_str).resolve()
            if joined_path.exists():
                project_dir = joined_path
            else:
                project_dir = first_path
        else:
            project_dir = first_path

    print(f"[Progress 0%] Commencing deep project review for root: {project_dir}", flush=True)
    
    # Check if directory exists and is valid
    if not project_dir.exists():
        print(f"Error: Path '{project_dir}' does not exist.", file=sys.stderr, flush=True)
        sys.exit(1)
        
    if not project_dir.is_dir():
        print(f"Error: Path '{project_dir}' is not a directory.", file=sys.stderr, flush=True)
        sys.exit(1)
        
    # Retrieve active backend config from Andrew configuration
    try:
        active = get_active_backend(user_id="default")
        api_key = active.api_key
        base_url = active.base_url
        model = active.model
    except Exception as e:
        print(f"Error loading LLM configuration: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
        
    if not api_key:
        print("Error: No active API key found. Please configure LLM provider settings.", file=sys.stderr, flush=True)
        sys.exit(1)
        
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    
    print(f"[Progress 10%] Crawling root directory: {project_dir}...", flush=True)
    files = crawl_project(project_dir)
    
    # Cap files to prevent excessive API costs/limits
    MAX_FILES = 40
    if len(files) > MAX_FILES:
        print(f"[Progress 15%] Found {len(files)} files. Capping audit to top {MAX_FILES} prioritized files.", flush=True)
        files = files[:MAX_FILES]
    else:
        print(f"[Progress 15%] Found {len(files)} files to audit.", flush=True)
        
    if not files:
        print(f"Error: No files matching allowed extensions found in '{project_dir}'.", file=sys.stderr, flush=True)
        sys.exit(1)
        
    analyses = []
    total_files = len(files)
    
    for idx, f in enumerate(files):
        rel_p = f.relative_to(project_dir).as_posix()
        # Scale progress between 15% and 85%
        progress = int(15 + (idx / total_files) * 70)
        print(f"[Progress {progress}%] Auditing: {rel_p}", flush=True)
        
        analysis = await analyze_file_with_llm(client, model, project_dir, f)
        analyses.append(analysis)
        
    print("[Progress 85%] Synthesizing overall Project Deep Review Report...", flush=True)
    report = await generate_final_report(client, model, project_dir.name, analyses)
    
    # Save reports
    RESEARCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    timestamped_path = RESEARCH_OUTPUT_DIR / f"project_deep_review_{timestamp}.md"
    latest_path = RESEARCH_OUTPUT_DIR / "project_deep_review_latest.md"
    
    try:
        timestamped_path.write_text(report, encoding="utf-8")
        latest_path.write_text(report, encoding="utf-8")
        print(f"[Progress 100%] Review complete! Report saved to:", flush=True)
        print(f"  - {timestamped_path}", flush=True)
        print(f"  - {latest_path}", flush=True)
        
        # Log to artifact registry
        try:
            from src.artifact_memory import record_artifact
            record_artifact(
                str(latest_path),
                title="Project Deep Review (Latest)",
                category="document",
                summary="Deep LLM audit report compiling quality, vulnerabilities, docs, and architecture recommendations.",
                source="project_deep_review_script"
            )
        except Exception:
            pass
            
    except OSError as e:
        print(f"Error saving report files: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.", flush=True)
        sys.exit(130)
