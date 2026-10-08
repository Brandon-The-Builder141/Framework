# Reminders

One-off, time-based reminders that fire on their own — Travis does not need to
be actively chatting when they go off.

## Tools

- `set_reminder(text, remind_at, channel?)`
  - `remind_at` is an ISO 8601 local datetime, e.g. `2026-07-29T15:00:00`.
    Compute it from the current time plus whatever offset Travis gave
    ("in 20 minutes", "at 3pm", "tomorrow morning").
  - `channel` is `discord` (DM, default) or `web` (dashboard notification).
- `list_reminders(include_resolved?)` — pending reminders, or all if `include_resolved=true`.
- `cancel_reminder(reminder_id)` — cancel a pending one by id.

## How delivery works

Stored in `data/profiles/default/reminders.json`. A background loop
(`_background_thoughts_loop` in `src/web/app.py`) polls every ~2 minutes for
anything due and delivers it through the same outreach pipeline
`send_discord_message` uses — so delivery bypasses proactive outreach caps
and cooldowns (a reminder is an explicit scheduled request, not a
speculative message).

This is separate from `remember_schedule` — use `set_reminder` for a single
future nudge, `remember_schedule` for a recurring routine/checklist that
should live in durable memory and get surfaced in context every turn.
