# Process Monitoring

## list_processes

**When to use:** User wants to see what's running, monitor CPU/memory, find heavy processes, audit running apps.

**How:**
- `max_lines`: Optional, default 50. Limits output.
- Returns process name, ID, CPU usage, memory (Working Set on Windows).
- Sorted by CPU, highest first.

**Examples:**
- Top processes: `list_processes(30)`
- Full list: `list_processes(100)`

**Tips:** Use for "what's using my CPU" or "show me running processes."

---

## is_process_running

**When to use:** Check if a specific process, daemon, or service is running by name.

**How:**
- `name`: Process name or partial match (case-insensitive).
- Returns matching processes with PIDs, or "not found."

**Examples:**
- Check daemon: `is_process_running("curiosity")`
- Check Python: `is_process_running("python")`
- Check service: `is_process_running("ollama")`

**Tips:** Use partial names. "python" matches "python.exe". Good for "is X running?" questions.
