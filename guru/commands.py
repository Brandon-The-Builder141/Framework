"""Parse and dispatch !guru commands."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from guru.config import load_config, normalize_discord_id
from guru.logger import log_action
from guru.profile import load_profile, record_session_rating, save_profile
from guru.session import GuruSessionManager

if TYPE_CHECKING:
    import discord

_PREFIX = re.compile(r"^!guru\b", re.IGNORECASE)
_SESSION: GuruSessionManager | None = None


def _manager() -> GuruSessionManager:
    global _SESSION
    if _SESSION is None:
        _SESSION = GuruSessionManager()
    return _SESSION


def is_guru_command(text: str) -> bool:
    return bool(_PREFIX.match((text or "").strip()))


def _trusted_ids(cfg: dict[str, Any]) -> set[str]:
    from guru.env import GURU_OWNER_ID

    ids = {normalize_discord_id(x) for x in (cfg.get("trusted_user_ids") or []) if x}
    owner = normalize_discord_id(cfg.get("owner_discord_id") or GURU_OWNER_ID)
    if owner:
        ids.add(owner)
    return {i for i in ids if i}


def _parse_args(text: str) -> tuple[str, list[str]]:
    body = _PREFIX.sub("", (text or "").strip()).strip()
    if not body:
        return "help", []
    parts = body.split()
    return parts[0].lower(), parts[1:]


async def handle_guru_action(
    cmd: str,
    args: list[str],
    ctx: Any,
    bot: Any,
) -> str:
    """Run a Guru command (ctx = message or interaction)."""
    cfg = load_config()
    author_id = normalize_discord_id(str(getattr(ctx.author, "id", "")))
    trusted = _trusted_ids(cfg)
    owner = normalize_discord_id(cfg.get("owner_discord_id") or "")
    from guru.env import GURU_OWNER_ID

    owner = owner or normalize_discord_id(GURU_OWNER_ID)
    if trusted and author_id not in trusted and author_id != owner:
        return (
            f"Guru shortcuts are limited to trusted users (your id: {author_id}). "
            "Add your Discord id to guru/guru_config.json → trusted_user_ids, "
            "or set GURU_OWNER_ID in guru/.env. This is not Andrew/Solen agent setup."
        )

    mgr = _manager()
    log_action("command", f"{cmd} user={author_id}")

    if cmd == "doctor":
        from guru.doctor import run_doctor
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = run_doctor()
        out = buf.getvalue().strip()
        return f"```\n{out}\n```" + ("\nFix issues above." if code else "\nAll checks passed.")

    if cmd == "help":
        return (
            "**Just talk to me** — DM or say \"Garth, join voice and let's meditate\"\n\n"
            "Shortcuts: `!guru start`, `!guru pause`, `!guru play`, `!guru skip`, `!guru quote`, `!guru stop`\n"
            "Or just talk — guided meditation only when you ask for it."
        )

    if cmd == "setup":
        from guru.channels import ensure_relaxing_spot

        return await ensure_relaxing_spot(bot, cfg)  # noqa: uses bot.user for overwrites

    if cmd == "status":
        return mgr.status_text()

    if cmd == "mood" and args:
        mood = args[0].lower()
        if mood not in ("calm", "playful"):
            return "Use `!guru mood calm` or `!guru mood playful`."
        prof = load_profile(author_id)
        prof["mood"] = mood
        save_profile(author_id, prof)
        mgr.set_mood(mood)
        return f"Mood set to **{mood}**."

    if cmd == "script":
        name = (args[0] if args else "random").lower().replace(" ", "_")
        mgr.set_script_choice(name)
        return f"Script selection: **{name}**."

    if cmd == "rate" and args:
        try:
            rating = int(args[0])
        except ValueError:
            return "Usage: `!guru rate 4 optional feedback`"
        feedback = " ".join(args[1:])
        script = mgr.last_script_name or "unknown"
        record_session_rating(author_id, script_name=script, rating=rating, feedback=feedback)
        return f"Thanks — logged **{rating}/5** for {script}."

    if cmd == "stop":
        return await mgr.stop(bot, ctx)

    if cmd in ("skip", "next", "track"):
        return await mgr.skip_track(bot, ctx)

    if cmd in ("pause", "hold"):
        return await mgr.pause(bot)

    if cmd in ("play", "resume", "unpause"):
        return await mgr.resume(bot)

    if cmd == "quote":
        from guru.quotes import post_random_quote

        ok = await post_random_quote(bot)
        return (
            "Posted a quote to **Inspirational Vibes**."
            if ok
            else "Could not post — check channel id and bot permissions."
        )

    if cmd == "meditate":
        from guru.scripts_loader import list_scripts

        script = (args[0] if args else "quick_calm").lower().replace(" ", "_")
        if script not in list_scripts():
            return f"Unknown script. Try: {', '.join(list_scripts())}"
        return await mgr.start(bot, ctx, author_id, script_name=script)

    if cmd == "start":
        if args:
            from guru.scripts_loader import list_scripts

            script = args[0].lower().replace(" ", "_")
            if script in list_scripts():
                return await mgr.start(bot, ctx, author_id, script_name=script)
        return await mgr.start_chill(bot, ctx, author_id)

    return "Unknown command. Try `/guru help` or `!guru help`."


async def handle_guru_command(text: str, message: Any, bot: Any) -> str:
    """Parse `!guru ...` text and dispatch."""
    cmd, args = _parse_args(text)
    return await handle_guru_action(cmd, args, message, bot)
