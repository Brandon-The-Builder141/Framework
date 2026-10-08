"""Standalone Guru (Garth) Discord bot — conversational + slash shortcuts."""
from __future__ import annotations

import re

from guru.commands import handle_guru_action, handle_guru_command, is_guru_command
from guru.config import load_config
from guru.env import GURU_DISCORD_BOT_TOKEN
from guru.logger import log_action
from guru.quotes import start_quote_task

DISCORD_MAX_LEN = 1900
_quote_task_started = False

# Talk to Garth in DMs, @mentions, or when you say his name
_GARTH_RE = re.compile(r"\bgarth\b", re.I)


def _should_chat(message) -> bool:
    if message.guild is None:
        return True
    cfg = load_config()
    text_id = (cfg.get("text_channel_id") or "").strip()
    if text_id and str(getattr(message.channel, "id", "")) == text_id:
        return True
    if message.guild and message.guild.me in message.mentions:
        return True
    if _GARTH_RE.search(message.content or ""):
        return True
    return False


def build_bot():
    import discord
    from discord import app_commands
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.presences = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    guru = app_commands.Group(name="guru", description="Garth — shortcuts (or just talk to him)")

    async def _run(interaction: discord.Interaction, cmd: str, args: list[str]) -> None:
        await interaction.response.defer(thinking=True)
        try:
            from guru.commands import handle_guru_action

            text = await handle_guru_action(cmd, args, interaction, bot)
            await interaction.followup.send(text[:DISCORD_MAX_LEN] if text else "Done.")
        except Exception as e:
            await interaction.followup.send(f"Guru error: {e}")

    @guru.command(name="help", description="Shortcuts (you can also just chat)")
    async def guru_help(interaction: discord.Interaction):
        await _run(interaction, "help", [])

    @guru.command(name="setup", description="Create Relaxing Spot channels")
    async def guru_setup(interaction: discord.Interaction):
        await _run(interaction, "setup", [])

    @guru.command(name="start", description="Join voice and play chill music (optional script = guided)")
    async def guru_start(interaction: discord.Interaction, script: str | None = None):
        await _run(interaction, "start", [script] if script else [])

    @guru.command(name="skip", description="Skip to a different background track")
    async def guru_skip(interaction: discord.Interaction):
        await _run(interaction, "skip", [])

    @guru.command(name="pause", description="Pause music and stay in voice")
    async def guru_pause(interaction: discord.Interaction):
        await _run(interaction, "pause", [])

    @guru.command(name="play", description="Resume music while staying in voice")
    async def guru_play(interaction: discord.Interaction):
        await _run(interaction, "play", [])

    @guru.command(name="meditate", description="Guided meditation with a script")
    async def guru_meditate(interaction: discord.Interaction, script: str = "quick_calm"):
        await _run(interaction, "meditate", [script])

    @guru.command(name="stop", description="Leave voice")
    async def guru_stop(interaction: discord.Interaction):
        await _run(interaction, "stop", [])

    @guru.command(name="quote", description="Post a quote to Inspirational Vibes")
    async def guru_quote(interaction: discord.Interaction):
        await _run(interaction, "quote", [])

    bot.tree.add_command(guru)

    @bot.event
    async def on_ready():
        global _quote_task_started
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="Talk to me · chill · pause/play",
            ),
        )
        print(f"Garth ONLINE: {bot.user}")
        print("  Chill music by default — ask for guided meditation explicitly")
        log_action("bot_ready", str(bot.user))
        if not _quote_task_started:
            start_quote_task(bot)
            _quote_task_started = True
        cfg = load_config()
        gid = (cfg.get("guild_id") or "").strip()
        try:
            if gid:
                bot.tree.copy_global_to(guild=discord.Object(id=int(gid)))
                await bot.tree.sync(guild=discord.Object(id=int(gid)))
        except Exception as e:
            print(f"  Slash sync warn: {e}")

    @bot.event
    async def on_message(message):
        if message.author.bot or not (message.content or "").strip():
            return

        content = message.content.strip()

        if is_guru_command(content):
            try:
                reply = await handle_guru_command(content, message, bot)
                if reply:
                    await message.reply(reply[:DISCORD_MAX_LEN])
            except Exception as e:
                await message.reply(f"Guru error: {e}")
            return

        if not _should_chat(message):
            return

        # Reflex: unambiguous voice commands dispatch the real handler directly,
        # so a join/skip/meditation always works even when the LLM is on a weak
        # fallback model that would otherwise narrate the action instead of doing it.
        from guru.voice_intent import detect_voice_intent

        intent = detect_voice_intent(content)
        if intent:
            cmd, args = intent
            try:
                reply = await handle_guru_action(cmd, args, message, bot)
                if reply:
                    await message.reply(reply[:DISCORD_MAX_LEN])
            except Exception as e:
                log_action("voice_intent_error", f"{cmd}: {e}", level="error")
                await message.reply(f"Garth hit a snag: {e}")
            return

        async with message.channel.typing():
            try:
                from guru.chat import chat_with_garth

                name = message.author.display_name or str(message.author)
                uid = str(message.author.id)
                reply = await chat_with_garth(
                    content,
                    ctx=message,
                    bot=bot,
                    user_id=uid,
                    user_name=name,
                )
                await message.reply(reply[:DISCORD_MAX_LEN])
            except Exception as e:
                import traceback

                log_action(
                    "chat_error",
                    f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}",
                    level="error",
                )
                await message.reply(f"Garth hit a snag: {e}")

    return bot


def main() -> None:
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from guru.doctor import run_doctor

    if not GURU_DISCORD_BOT_TOKEN:
        print("Set GURU_DISCORD_BOT_TOKEN in guru/.env")
        raise SystemExit(1)
    if run_doctor() != 0:
        raise SystemExit(1)

    bot = build_bot()
    print("Connecting Garth (leave this window open)...")
    bot.run(GURU_DISCORD_BOT_TOKEN, reconnect=True)


if __name__ == "__main__":
    main()
