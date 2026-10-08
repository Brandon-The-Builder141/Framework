"""Create Relaxing Spot category and channels."""
from __future__ import annotations

import json
from typing import Any

import httpx

from guru.config import load_config, normalize_discord_id
from guru.logger import log_action
from guru.paths import CONFIG_PATH


async def _api(
    method: str,
    endpoint: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
) -> dict | str:
    from guru.env import GURU_DISCORD_BOT_TOKEN

    token = token or GURU_DISCORD_BOT_TOKEN
    if not token:
        return "Error: GURU_DISCORD_BOT_TOKEN not set in guru/.env"
    url = f"https://discord.com/api/v10{endpoint}"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.request(method, url, headers=headers, json=json_body)
        if r.status_code >= 400:
            return f"Error: HTTP {r.status_code} — {r.text[:300]}"
        if r.content:
            return r.json()
        return {}


async def ensure_relaxing_spot(bot: Any, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    guild_id = (cfg.get("guild_id") or "").strip()
    if not guild_id and bot.guilds:
        guild_id = str(bot.guilds[0].id)
    if not guild_id:
        return "Set `guild_id` in guru_config.json or invite the bot to a server."

    cat_name = cfg.get("category_name") or "Relaxing Spot"
    voice_name = cfg.get("voice_channel_name") or "Meditation Vibes"
    text_name = cfg.get("text_channel_name") or "Inspirational Vibes"

    guild = bot.get_guild(int(guild_id))
    if guild:
        for cat in guild.categories:
            if cat.name == cat_name:
                category_id = str(cat.id)
                voice_id = ""
                text_id = ""
                for ch in cat.channels:
                    if ch.name == voice_name:
                        voice_id = str(ch.id)
                    if ch.name == text_name:
                        text_id = str(ch.id)
                if voice_id and text_id:
                    _persist_channel_ids(category_id, voice_id, text_id, guild_id)
                    return f"Already exists: **{cat_name}** (voice `{voice_id}`, text `{text_id}`)."

    payload = {"name": cat_name, "type": 4}
    cat_resp = await _api("POST", f"/guilds/{guild_id}/channels", json_body=payload)
    if isinstance(cat_resp, str):
        return cat_resp
    category_id = cat_resp.get("id")
    if not category_id:
        return "Failed to create category."

    bot_id = normalize_discord_id(str(getattr(bot.user, "id", "")))
    trusted = _trusted_user_list(cfg, bot_id)
    voice_overwrites = _voice_permission_overwrites(guild_id, bot_id, trusted)

    created_voice = ""
    created_text = ""
    for ch_name, ch_type in ((voice_name, 2), (text_name, 0)):
        body: dict[str, Any] = {
            "name": ch_name,
            "type": ch_type,
            "parent_id": category_id,
        }
        if ch_type == 2:
            body["permission_overwrites"] = voice_overwrites
        resp = await _api("POST", f"/guilds/{guild_id}/channels", json_body=body)
        if isinstance(resp, str):
            return resp
        if ch_type == 2:
            created_voice = resp.get("id", "")
        else:
            created_text = resp.get("id", "")

    _persist_channel_ids(category_id, created_voice, created_text, guild_id)
    log_action("channels_created", f"{cat_name} voice={created_voice} text={created_text}")
    return (
        f"Created **{cat_name}** with voice **{voice_name}** and text **{text_name}**. "
        "Tune permissions in Discord if needed — bot needs Connect/Speak."
    )


async def create_channels(
    bot: Any,
    *,
    category_name: str,
    voice_names: list[str] | None = None,
    text_names: list[str] | None = None,
) -> str:
    """Create a category with optional voice/text channels."""
    cfg = load_config()
    guild_id = (cfg.get("guild_id") or "").strip()
    if not guild_id and bot.guilds:
        guild_id = str(bot.guilds[0].id)
    if not guild_id:
        return "No guild_id — invite Garth to your server first."

    payload = {"name": category_name, "type": 4}
    cat_resp = await _api("POST", f"/guilds/{guild_id}/channels", json_body=payload)
    if isinstance(cat_resp, str):
        return cat_resp
    category_id = cat_resp.get("id")
    if not category_id:
        return "Failed to create category."

    created = []
    for name in voice_names or []:
        body = {"name": name, "type": 2, "parent_id": category_id}
        resp = await _api("POST", f"/guilds/{guild_id}/channels", json_body=body)
        if isinstance(resp, str):
            return resp
        created.append(f"voice `{name}`")
    for name in text_names or []:
        body = {"name": name, "type": 0, "parent_id": category_id}
        resp = await _api("POST", f"/guilds/{guild_id}/channels", json_body=body)
        if isinstance(resp, str):
            return resp
        created.append(f"text `{name}`")

    log_action("channels_custom", f"{category_name} {created}")
    return f"Created category **{category_name}** with: {', '.join(created) or 'no channels'}."


def _trusted_user_list(cfg: dict[str, Any], bot_id: str = "") -> list[str]:
    from guru.env import GURU_OWNER_ID

    trusted = [normalize_discord_id(x) for x in (cfg.get("trusted_user_ids") or []) if x]
    owner = normalize_discord_id(cfg.get("owner_discord_id") or GURU_OWNER_ID)
    if owner and owner not in trusted:
        trusted.append(owner)
    bid = normalize_discord_id(bot_id)
    if bid and bid not in trusted:
        pass  # bot handled separately in overwrites
    return trusted


def _voice_permission_overwrites(
    guild_id: str,
    bot_id: str,
    trusted: list[str],
) -> list[dict[str, Any]]:
    allow_voice = str(1048576 + 2097152 + 1024)  # CONNECT + SPEAK + VIEW
    deny_speak = "2097152"
    overwrites: list[dict[str, Any]] = [
        {"id": guild_id, "type": 0, "deny": deny_speak},
    ]
    if bot_id:
        overwrites.append({"id": bot_id, "type": 1, "allow": allow_voice})
    for uid in trusted:
        if uid:
            overwrites.append({"id": uid, "type": 1, "allow": allow_voice})
    return overwrites


async def sync_relaxing_spot_permissions(bot: Any, cfg: dict | None = None) -> str:
    """Apply trusted-user voice overwrites on Meditation Vibes (and save config)."""
    cfg = cfg or load_config()
    guild_id = (cfg.get("guild_id") or "").strip()
    voice_id = (cfg.get("voice_channel_id") or "").strip()
    if not guild_id or not voice_id:
        return "Missing guild_id or voice_channel_id in guru_config.json."

    bot_id = normalize_discord_id(str(getattr(bot.user, "id", "")))
    if not bot_id:
        async with httpx.AsyncClient() as client:
            from guru.env import GURU_DISCORD_BOT_TOKEN

            r = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {GURU_DISCORD_BOT_TOKEN}"},
            )
            if r.status_code == 200:
                bot_id = normalize_discord_id(r.json().get("id", ""))

    trusted = _trusted_user_list(cfg, bot_id)
    overwrites = _voice_permission_overwrites(guild_id, bot_id, trusted)
    resp = await _api(
        "PATCH",
        f"/channels/{voice_id}",
        json_body={"permission_overwrites": overwrites},
    )
    if isinstance(resp, str):
        return resp
    names = ", ".join(trusted) or "(none)"
    log_action("voice_perms_sync", f"trusted={names}")
    return f"Updated **Meditation Vibes** access for trusted users: {names}"


async def grant_trusted_member(
    bot: Any,
    user_id: str,
    *,
    username_hint: str = "",
) -> str:
    """Add a Discord user to trusted_user_ids and sync voice channel permissions."""
    cfg = load_config()
    uid = normalize_discord_id(user_id)
    if not uid and username_hint:
        uid = await _resolve_member_id(cfg.get("guild_id") or "", username_hint)
    if not uid:
        return "Need a valid Discord user id (or username if member search works)."

    ids = [normalize_discord_id(x) for x in (cfg.get("trusted_user_ids") or []) if x]
    if uid not in ids:
        ids.append(uid)
    cfg["trusted_user_ids"] = ids
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_msg = await sync_relaxing_spot_permissions(bot, cfg)
    return f"Added trusted user `{uid}`. {sync_msg}"


async def _resolve_member_id(guild_id: str, query: str) -> str:
    """Best-effort guild member lookup by username (requires members intent)."""
    q = (query or "").strip().lower().lstrip("@")
    if not guild_id or not q:
        return ""
    resp = await _api("GET", f"/guilds/{guild_id}/members/search", json_body=None)
    # search endpoint uses query param — fix _api to support params or use httpx directly
    from guru.env import GURU_DISCORD_BOT_TOKEN

    if not GURU_DISCORD_BOT_TOKEN:
        return ""
    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/search"
    headers = {"Authorization": f"Bot {GURU_DISCORD_BOT_TOKEN}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers, params={"query": q, "limit": 10})
        if r.status_code >= 400:
            return ""
        for m in r.json() or []:
            user = m.get("user") or {}
            name = (user.get("username") or "").lower()
            global_name = (user.get("global_name") or "").lower()
            if q in name or q in global_name or name == q:
                return normalize_discord_id(user.get("id", ""))
    return ""


def _persist_channel_ids(
    category_id: str,
    voice_id: str,
    text_id: str,
    guild_id: str,
) -> None:
    cfg = load_config()
    cfg["guild_id"] = guild_id
    cfg["category_id"] = category_id
    cfg["voice_channel_id"] = voice_id
    cfg["text_channel_id"] = text_id
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
