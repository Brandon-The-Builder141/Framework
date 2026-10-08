"""Tools Garth's LLM can call — voice, music, meditation, channels, memory."""
from __future__ import annotations

import json
from typing import Any

from guru.channels import create_channels, ensure_relaxing_spot, grant_trusted_member
from guru.messaging import post_inspirational, send_user_dm
from guru.quotes import post_random_quote
from guru.commands import _manager, _trusted_ids
from guru.config import load_config, normalize_discord_id
from guru.env import GURU_OWNER_ID


def _is_guru_owner(user_id: str, cfg: dict[str, Any]) -> bool:
    owner = normalize_discord_id(cfg.get("owner_discord_id") or GURU_OWNER_ID)
    return bool(owner) and normalize_discord_id(user_id) == owner
from guru.conversation_memory import add_profile_note
from guru.logger import log_action
from guru.profile import load_profile, record_session_rating, save_profile
from guru.scripts_loader import list_scripts


def tool_definitions() -> list[dict]:
    scripts = ", ".join(list_scripts())
    return [
        {
            "type": "function",
            "function": {
                "name": "setup_relaxing_spot",
                "description": "Create the Relaxing Spot category with Meditation Vibes (voice) and Inspirational Vibes (text).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_channels",
                "description": "Create a Discord category and channels (voice and/or text).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category_name": {"type": "string"},
                        "voice_channel_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "text_channel_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["category_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "join_voice_session",
                "description": (
                    "Join Meditation Vibes. DEFAULT: mode=chill (music only, no spoken guide). "
                    "Use mode=meditate ONLY when the user explicitly asks for a guided meditation; "
                    "then script is required (box_breathing, loving_kindness, body_scan, quick_calm)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["chill", "meditate"],
                        },
                        "script": {
                            "type": "string",
                            "description": f"One of: {scripts}, or random",
                        },
                    },
                    "required": ["mode"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "skip_ambient_track",
                "description": (
                    "Skip to the next background track (one call only). "
                    "Use when user asks to change/skip song. Each song plays for several minutes."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pause_voice_session",
                "description": "Pause current voice playback but stay in the voice channel.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "resume_voice_session",
                "description": "Resume paused voice playback while staying in the voice channel.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "stop_voice_session",
                "description": "Leave voice channel and stop all audio.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grant_trusted_access",
                "description": (
                    "Grant a Discord user access to Relaxing Spot voice/text and Guru tools. "
                    "Use user_id or username (e.g. travis5279)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "username": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "post_inspirational_vibes",
                "description": (
                    "Post a message to the Inspirational Vibes text channel. "
                    "Use for notes to the server, quotes, or anything Brandon/Travis should see."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_dm",
                "description": (
                    "Send a direct message to a user (e.g. Travis / travis5279). "
                    "Use user_id or username."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "user_id": {"type": "string"},
                        "username": {"type": "string"},
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "post_inspirational_quote",
                "description": "Post a random motivational quote to Inspirational Vibes now.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "session_status",
                "description": "Check if a voice session is active and channel config.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remember_about_user",
                "description": "Save a fact or preference about this user for future sessions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {"type": "string"},
                    },
                    "required": ["note"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rate_last_session",
                "description": "Record user rating 1-5 for the last meditation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "integer"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["score"],
                },
            },
        },
    ]


async def execute_tool(
    name: str,
    args: dict[str, Any],
    *,
    ctx: Any,
    bot: Any,
    user_id: str,
) -> str:
    cfg = load_config()
    trusted = _trusted_ids(cfg)
    uid = normalize_discord_id(user_id)
    gated = {
        "join_voice_session",
        "stop_voice_session",
        "setup_relaxing_spot",
        "create_channels",
        "grant_trusted_access",
        "skip_ambient_track",
        "pause_voice_session",
        "resume_voice_session",
        "post_inspirational_vibes",
        "send_dm",
        "post_inspirational_quote",
    }
    if name in gated and trusted and uid not in trusted and not _is_guru_owner(uid, cfg):
        return (
            "Permission denied: this Discord user is not in Guru's trusted_user_ids "
            f"(your id: {uid}). This is a Guru bot setting in guru/guru_config.json — "
            "not Andrew/Solen setup. Owner can run grant_trusted_access or add the id to the config."
        )

    mgr = _manager()
    log_action("garth_tool", f"{name} {json.dumps(args)[:120]}")

    if name == "setup_relaxing_spot":
        return await ensure_relaxing_spot(bot, cfg)

    if name == "grant_trusted_access":
        return await grant_trusted_member(
            bot,
            str(args.get("user_id") or ""),
            username_hint=str(args.get("username") or ""),
        )

    if name == "create_channels":
        return await create_channels(
            bot,
            category_name=args.get("category_name") or "New Category",
            voice_names=args.get("voice_channel_names") or [],
            text_names=args.get("text_channel_names") or [],
        )

    if name == "session_status":
        return mgr.status_text()

    if name == "stop_voice_session":
        return await mgr.stop(bot, ctx)

    if name == "remember_about_user":
        add_profile_note(uid, str(args.get("note") or ""))
        return "Noted — I'll remember that."

    if name == "rate_last_session":
        score = int(args.get("score") or 5)
        record_session_rating(
            uid,
            script_name=mgr.last_script_name or "unknown",
            rating=score,
            feedback=str(args.get("feedback") or ""),
        )
        return f"Logged {score}/5. Thank you."

    if name == "skip_ambient_track":
        return await mgr.skip_track(bot, ctx)

    if name == "pause_voice_session":
        return await mgr.pause(bot)

    if name == "resume_voice_session":
        return await mgr.resume(bot)

    if name == "post_inspirational_vibes":
        return await post_inspirational(bot, str(args.get("message") or ""), cfg=cfg)

    if name == "send_dm":
        return await send_user_dm(
            bot,
            str(args.get("user_id") or ""),
            str(args.get("message") or ""),
            username_hint=str(args.get("username") or ""),
        )

    if name == "post_inspirational_quote":
        ok = await post_random_quote(bot)
        return "Posted a fresh quote to **Inspirational Vibes**." if ok else (
            "Could not post — check text_channel_id and bot Send Messages permission."
        )

    if name == "join_voice_session":
        mode = (args.get("mode") or "chill").lower()
        script = (args.get("script") or "").strip().lower().replace(" ", "_")
        if mode != "meditate":
            return await mgr.start_chill(bot, ctx, uid)
        if not script:
            return (
                "Which guided meditation? box_breathing, loving_kindness, body_scan, or quick_calm."
            )
        return await mgr.start(bot, ctx, uid, script_name=script)

    return f"Unknown tool: {name}"
