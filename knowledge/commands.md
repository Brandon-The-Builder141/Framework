# Shell Commands

## run_command

**When to use:** Run system commands, install packages, run scripts, execute shell operations. Use when no dedicated tool exists.

**How:**
- `cmd`: The command to run (e.g. `dir`, `npm install`, `python script.py`).
- `cwd`: Optional working directory. Defaults to current.
- `timeout`: Optional, default 60 seconds.

**Examples:**
- List files: `run_command("dir")` (Windows) or `run_command("ls -la")` (Unix)
- Run Python: `run_command("python script.py")`
- Install: `run_command("pip install requests")`
- PowerShell: `run_command("powershell -Command \"Get-Process\"")`

**When NOT to use:**
- File read/write → use read_file, write_file
- Process list → use list_processes, is_process_running
- Build project → use run_build
- Web search → use search_web

**Tips:** On Windows, use `cmd` for CMD or `powershell -Command "..."` for PowerShell. Commands run in a shell; paths with spaces may need quotes.
