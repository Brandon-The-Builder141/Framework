"""Post to Inspirational Vibes and DM users."""
from __future__ import annotations

from typing import Any

from guru.config import load_config, normalize_discord_id
from guru.logger import log_action


async def get_text_channel(bot: Any, cfg: dict | None = None) -> Any:
    import discord

    cfg = cfg or load_config()
    channel_id = (cfg.get("text_channel_id") or "").strip()
    if not channel_id:
        raise ValueError(
            "No text_channel_id — run setup or set Inspirational Vibes id in guru_config.json."
        )
    ch = bot.get_channel(int(channel_id))
    if ch is None:
        ch = await bot.fetch_channel(int(channel_id))
    if not isinstance(ch, discord.TextChannel):
        raise ValueError(f"Channel {channel_id} is not a text channel.")
    return ch


async def post_inspirational(bot: Any, message: str, *, cfg: dict | None = None) -> str:
    """Post a message to Inspirational Vibes."""
    text = (message or "").strip()
    if not text:
        return "Need something to post."
    ch = await get_text_channel(bot, cfg)
    sent = await ch.send(text[:2000])
    log_action("inspirational_post", text[:80])
    return f"Posted to **{ch.name}** (message id `{sent.id}`)."


async def send_user_dm(
    bot: Any,
    user_id: str,
    message: str,
    *,
    username_hint: str = "",
) -> str:
    """DM a Discord user by id or username."""
    from guru.channels import _resolve_member_id

    cfg = load_config()
    uid = normalize_discord_id(user_id)
    if not uid and username_hint:
        uid = await _resolve_member_id(cfg.get("guild_id") or "", username_hint)
    if not uid:
        return "Need a valid user id or username (e.g. travis5279)."

    text = (message or "").strip()
    if not text:
        return "Need a message to send."

    user = bot.get_user(int(uid))
    if user is None:
        user = await bot.fetch_user(int(uid))

    dm = await user.create_dm()
    await dm.send(text[:2000])
    name = getattr(user, "display_name", None) or getattr(user, "name", uid)
    log_action("dm_sent", f"to={uid} {text[:60]}")
    return f"Sent DM to **{name}**."
