# Cursor CLI (headless `agent` / `cursor-agent`)

## What `agent --trust` is

`agent --trust` is a **Cursor Agent CLI** flag, not a Solen framework setting. It tells Cursor to trust the workspace directory without an interactive prompt. Required for non-interactive runs (`-p` / `--print`).

## Framework behavior

Doctor Mode and `cursor_edit` invoke the CLI via `src/tools/cursor_cli.py`, which passes **`--trust` and `--workspace`** automatically (config: `CURSOR_CLI_TRUST=true` in `.env` by default).

## Do not nag the Creator

- **Never** tell the user to run `agent --trust` before normal chat, `update_profile`, Discord, or web dashboard actions — those do not need it.
- Only mention manual `agent --trust` if a **Cursor CLI subprocess** failed with an explicit trust/workspace prompt and automated `--trust` is disabled (`CURSOR_CLI_TRUST=false`).
- Subagents running Python scripts (`spawn_subagent`) are unrelated unless the script itself shells out to `agent` without `--trust`.

## One-time manual fix (if needed)

From the project root in PowerShell:

```powershell
cd C:\Users\Brandon\OneDrive\Desktop\Framework
agent --trust -p "ok" --output-format text
```

## Not the same as

- `complete_setup` / `soul.json` — first-boot owner + agent name onboarding
- Guru `trusted_user_ids` — Discord meditation bot access list
