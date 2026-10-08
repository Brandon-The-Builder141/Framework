# Build Orchestrator

## run_build

**When to use:** Build or install a project—web (npm) or Python (pip).

**How:**
- `project_path`: Path to project root (where package.json or requirements.txt lives).
- `project_type`: `"auto"`, `"web"`, or `"python"`. Auto detects from package.json or pyproject.toml/requirements.txt.

**Examples:**
- Build web app: `run_build("frontend")` or `run_build("c:/projects/my-app", "web")`
- Install Python: `run_build(".")` in project dir

**Auto-detection:**
- `package.json` → web (npm run build, or yarn/pnpm)
- `pyproject.toml`, `setup.py`, or `requirements.txt` → python (pip install)

**Tips:** If build fails, check the error output. Use list_dir to confirm project structure first.
