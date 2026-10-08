"""Post inspirational quotes to Inspirational Vibes on a schedule."""
from __future__ import annotations

import asyncio
import random
from typing import Any

from guru.config import load_config
from guru.logger import log_action
from guru.messaging import post_inspirational

_DEFAULT_QUOTES = [
    "Small steps still move you forward.",
    "Breathe — you're allowed to pause.",
    "Your effort today is enough for today.",
    "Calm is a skill you can practice.",
    "You don't have to carry everything at once.",
    "Stillness is not laziness — it's repair.",
    "You are allowed to rest without earning it.",
    "Let the noise settle. You can hear yourself again.",
    "Progress isn't always loud.",
    "Gentle consistency beats harsh intensity.",
    "The present moment is enough to stand in.",
    "Trust the pace your nervous system asks for.",
]


async def post_random_quote(bot: Any) -> bool:
    cfg = load_config()
    if not cfg.get("quotes_enabled", True):
        log_action("quote_skipped", "quotes_enabled is false", level="info")
        return False
    channel_id = (cfg.get("text_channel_id") or "").strip()
    if not channel_id:
        log_action("quote_skipped", "no text_channel_id", level="warn")
        return False
    quote = random.choice(_DEFAULT_QUOTES)
    try:
        await post_inspirational(bot, f"✨ {quote}", cfg=cfg)
        log_action("quote_posted", quote[:80])
        return True
    except Exception as e:
        log_action("quote_failed", str(e)[:200], level="error")
        return False


async def quote_loop(bot: Any) -> None:
    """Background: first quote soon after boot, then every N hours."""
    cfg = load_config()
    startup_min = float(cfg.get("quote_startup_delay_minutes") or 3)
    await asyncio.sleep(max(60, startup_min * 60))
    await post_random_quote(bot)

    while True:
        cfg = load_config()
        hours = float(cfg.get("quote_interval_hours") or 4)
        await asyncio.sleep(max(1800, hours * 3600))
        await post_random_quote(bot)


def start_quote_task(bot: Any) -> asyncio.Task:
    return asyncio.create_task(quote_loop(bot), name="guru_quotes")
