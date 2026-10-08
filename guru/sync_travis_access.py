"""Sync Meditation Vibes permissions for trusted users (Travis)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> None:
    import httpx
    from guru.channels import sync_relaxing_spot_permissions
    from guru.config import load_config
    from guru.env import GURU_DISCORD_BOT_TOKEN

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {GURU_DISCORD_BOT_TOKEN}"},
        )
        r.raise_for_status()
        me = r.json()

    cfg = load_config()
    guild_id = int(cfg.get("guild_id") or "1502773553857302698")
    bot = SimpleNamespace(
        user=SimpleNamespace(id=int(me["id"])),
        guilds=[SimpleNamespace(id=guild_id)],
        get_guild=lambda gid: SimpleNamespace(id=guild_id) if gid == guild_id else None,
    )
    print(await sync_relaxing_spot_permissions(bot, cfg))


if __name__ == "__main__":
    asyncio.run(main())
