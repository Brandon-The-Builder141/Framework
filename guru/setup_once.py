"""One-shot: create Relaxing Spot (no long-running bot needed)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> None:
    import httpx
    from guru.channels import ensure_relaxing_spot
    from guru.config import load_config
    from guru.env import GURU_DISCORD_BOT_TOKEN

    if not GURU_DISCORD_BOT_TOKEN:
        print("Missing GURU_DISCORD_BOT_TOKEN")
        raise SystemExit(1)

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {GURU_DISCORD_BOT_TOKEN}"},
        )
        r.raise_for_status()
        me = r.json()

    cfg = load_config()
    guild_id = int(cfg.get("guild_id") or "1502773553857302698")
    guild = SimpleNamespace(id=guild_id, name="Solen", categories=[])

    def get_guild(gid: int):
        return guild if gid == guild_id else None

    bot = SimpleNamespace(
        user=SimpleNamespace(id=int(me["id"])),
        guilds=[guild],
        get_guild=get_guild,
    )
    result = await ensure_relaxing_spot(bot, cfg)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
