"""
Discord bot: receives messages, runs agent, sends response.
Splits long replies into chunks, attaches TTS voice to each reply.
Emits notifications for web/desktop when messages arrive.
Consumes outreach queue for proactive messages.
"""
import asyncio
import io
import json
from pathlib import Path

from config.settings import DISCORD_OWNER_ID, DISCORD_BOT_TOKEN

DISCORD_MAX_LEN = 1900  # leave buffer under 2000

# Will be set by app on startup
_agent_ref = None
_discord_client = None

# guild_id -> VoiceRecvClient, for the live voice-call feature (join_voice_channel)
_voice_clients: dict[int, "object"] = {}
_voice_play_locks: dict[int, asyncio.Lock] = {}


def set_agent(agent):
    global _agent_ref
    _agent_ref = agent


async def _run_discord_bot():
    """Run the Discord bot (called from lifespan)."""
    if not DISCORD_BOT_TOKEN:
        print("Discord: DISCORD_BOT_TOKEN not set, skipping Discord bot.")
        return

    try:
        import discord
        from discord.ext import commands
    except ImportError:
        print("Discord: discord.py not installed. Run: pip install discord.py")
        return

    global _discord_client

    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages = True
    intents.dm_messages = True
    intents.guild_messages = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    _discord_client = bot

    from src import contacts
    from src import notifications
    from src.outreach import get_outreach_queue, OutreachMessage

    @bot.event
    async def on_ready():
        print(f"Discord bot ready: {bot.user}")

    @bot.event
    async def on_message(message):
        if message.author.bot:
            return
        if not _agent_ref:
            return
        # Only respond to DMs or @mentions in servers
        if message.guild and bot.user not in message.mentions:
            return

        author_name = message.author.display_name or str(message.author)
        author_id = str(message.author.id)
        content = (message.content or "").strip()
        if message.guild and bot.user in message.mentions:
            content = content.replace(f"<@{bot.user.id}>", "").strip()
        if not content:
            return

        # Deterministically persist every Discord speaker. Do this before slash
        # commands too, so contacts do not depend on the LLM choosing to call
        # update_contact.
        try:
            contacts.record_discord_interaction(
                discord_id=author_id,
                display_name=author_name,
                content=content,
            )
        except Exception:
            pass

        # Slash-command interception — bypasses the LLM entirely. Same parser
        # as web/CLI, so behavior matches across surfaces.
        try:
            from src.agent import memory_commands
            if memory_commands.is_command(content):
                response = memory_commands.handle(content, _agent_ref.memory)
                if response is not None:
                    _agent_ref.memory.add_short_term(
                        f"[Discord – {author_name} said]: {content}"
                    )
                    _agent_ref.memory.add_short_term(f"Andrew: {response}")
                    # Discord 2000-char limit
                    chunk = response if len(response) <= 1900 else (response[:1897] + "...")
                    try:
                        await message.reply(f"```\n{chunk}\n```")
                    except Exception:
                        await message.channel.send(f"```\n{chunk}\n```")
                    return
        except Exception:
            pass

        # Notify owner: desktop + web
        notifications.emit_notification(
            "discord_message",
            f"Discord: {author_name}",
            content[:200],
            {"author": author_name, "author_id": author_id, "content": content},
        )
        # Store in memory so when Creator replies (e.g. in web), agent knows what they're responding to
        try:
            _agent_ref.memory.add_short_term(f"[Discord – {author_name} said]: {content}")
        except Exception:
            pass
        notifications.show_desktop_notification(
            f"Discord from {author_name}",
            content[:200],
        )

        # Load contact context
        contact = contacts.get_contact("", discord_id=author_id)
        contact_ctx = contacts.format_contact_for_context(contact)
        ctx_prefix = ""
        if contact_ctx:
            ctx_prefix = f"[Contact profile: {contact_ctx}]\n\n"
        from src.agent.soul import get_context_for_speaker
        speaker_ctx = get_context_for_speaker(is_web=False, discord_id=author_id, author_name=author_name)
        if speaker_ctx:
            ctx_prefix += speaker_ctx
        user_msg = f"{ctx_prefix}Message from {author_name} (Discord, discord_id={author_id}) who just said: {content}"

        _agent_ref.memory.set_working("current_speaker_discord_id", author_id)

        narrate_queue = asyncio.Queue()

        async def run_agent():
            try:
                return await _agent_ref.chat(
                    user_msg,
                    narrate_queue=narrate_queue,
                    speaker_discord_id=author_id,
                )
            except Exception as e:
                return f"Sorry, I hit an error: {e}"

        agent_task = asyncio.create_task(run_agent())
        status_msg = None

        async def edit_status_loop():
            nonlocal status_msg
            status_msg = await message.reply("🔄 Processing...")
            while not agent_task.done():
                try:
                    item = await asyncio.wait_for(narrate_queue.get(), timeout=0.3)
                except asyncio.TimeoutError:
                    continue
                if item and item.get("type") == "narrate":
                    text = (item.get("text") or "")[:1900]
                    try:
                        await status_msg.edit(content=f"🔄 {text}")
                    except Exception:
                        pass
            while True:
                try:
                    item = narrate_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item and item.get("type") == "narrate":
                    text = (item.get("text") or "")[:1900]
                    try:
                        await status_msg.edit(content=f"🔄 {text}")
                    except Exception:
                        pass

        edit_task = asyncio.create_task(edit_status_loop())
        reply = await agent_task
        await edit_task
        reply = (reply or "…").strip()

        # Edit status to "Complete" before sending final reply
        if status_msg:
            try:
                await status_msg.edit(content="✅ Complete.")
            except Exception:
                pass

        # Split long messages into chunks
        def chunk_text(text: str, max_len: int = DISCORD_MAX_LEN) -> list[str]:
            if len(text) <= max_len:
                return [text] if text else []
            chunks = []
            while text:
                if len(text) <= max_len:
                    chunks.append(text)
                    break
                cut = text.rfind("\n", 0, max_len + 1)
                if cut <= 0:
                    cut = text.rfind(" ", 0, max_len + 1)
                if cut <= 0:
                    cut = max_len
                chunks.append(text[:cut].strip())
                text = text[cut:].strip()
            return [c for c in chunks if c]

        chunks = chunk_text(reply)

        # Generate voice (TTS) for full reply
        voice_bytes = None
        if reply:
            try:
                from src.voice.tts import synthesize
                from src.user_settings import get_tts_voice

                voice_bytes = await synthesize(reply, voice=get_tts_voice())
            except Exception:
                pass

        # Send text chunks; attach voice to first message
        try:
            for i, chunk in enumerate(chunks):
                files = []
                if i == 0 and voice_bytes and len(voice_bytes) < 25 * 1024 * 1024:  # 25MB limit
                    files.append(discord.File(io.BytesIO(voice_bytes), filename="reply.mp3"))
                if files:
                    await message.reply(chunk, files=files)
                else:
                    await message.reply(chunk)
        except Exception:
            for chunk in chunks:
                try:
                    await message.channel.send(chunk)
                except Exception:
                    pass

    await bot.start(DISCORD_BOT_TOKEN)


async def _outreach_consumer():
    """Background task: send proactive Discord messages from outreach queue."""
    try:
        import discord
    except ImportError:
        return

    from src.outreach import OutreachMessage, get_outreach_queue

    q = get_outreach_queue()
    while True:
        try:
            msg = await asyncio.wait_for(q.get(), timeout=300.0)
        except asyncio.TimeoutError:
            continue
        if not isinstance(msg, OutreachMessage) or msg.channel != "discord":
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
            continue
        client = _discord_client
        if not client:
            await asyncio.sleep(5)
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
            continue
        if not client.is_ready():
            await asyncio.sleep(2)
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
            continue
        content = (msg.content or "").strip()
        attachment_paths = list(getattr(msg, "attachment_paths", []) or [])
        if not content and not attachment_paths:
            continue
        from src.logging_config import log_outreach_attempt, log_outreach_failure, log_outreach_success
        from src import notifications
        
        # Determine target: channel or user DM
        target_channel_id = getattr(msg, "target_channel_id", None)
        user_id = msg.target_user_id or DISCORD_OWNER_ID
        is_direct = getattr(msg, "is_direct", False)
        target_desc = f"channel:{target_channel_id}" if target_channel_id else f"user:{user_id}"
        log_outreach_attempt("discord", target_desc, content[:80])
        
        try:
            voice_bytes = None
            try:
                from src.voice.tts import synthesize
                from src.user_settings import get_tts_voice
                voice_bytes = await synthesize(content, voice=get_tts_voice())
            except Exception:
                pass
            
            # Chunk the message
            chunks = []
            remainder = content
            while remainder:
                chunk = remainder[:DISCORD_MAX_LEN]
                if len(remainder) > DISCORD_MAX_LEN:
                    cut = remainder.rfind("\n", 0, DISCORD_MAX_LEN + 1)
                    if cut <= 0:
                        cut = remainder.rfind(" ", 0, DISCORD_MAX_LEN + 1)
                    if cut <= 0:
                        cut = DISCORD_MAX_LEN
                    chunk = remainder[:cut].strip()
                    remainder = remainder[cut:].strip()
                else:
                    remainder = ""
                chunks.append(chunk)
            if not chunks:
                chunks = ["(attachment)"]

            files_payload = []
            for p in attachment_paths:
                try:
                    path = str(p)
                    data = Path(path).read_bytes()
                    files_payload.append(discord.File(io.BytesIO(data), filename=Path(path).name))
                except Exception:
                    continue
            
            # Send to channel or user
            if target_channel_id:
                channel = client.get_channel(int(target_channel_id))
                if not channel:
                    channel = await client.fetch_channel(int(target_channel_id))
                for i, chunk in enumerate(chunks):
                    files = []
                    if i == 0 and voice_bytes and len(voice_bytes) < 25 * 1024 * 1024:
                        files.append(discord.File(io.BytesIO(voice_bytes), filename="reply.mp3"))
                    if i == 0 and files_payload:
                        files.extend(files_payload)
                    if files:
                        await channel.send(chunk, files=files)
                    else:
                        await channel.send(chunk)
            else:
                if not user_id:
                    raise ValueError("No target user id and DISCORD_OWNER_ID is not set.")
                user = await client.fetch_user(int(user_id))
                for i, chunk in enumerate(chunks):
                    files = []
                    if i == 0 and voice_bytes and len(voice_bytes) < 25 * 1024 * 1024:
                        files.append(discord.File(io.BytesIO(voice_bytes), filename="reply.mp3"))
                    if i == 0 and files_payload:
                        files.extend(files_payload)
                    if files:
                        await user.send(chunk, files=files)
                    else:
                        await user.send(chunk)
            
            log_outreach_success("discord", target_desc)
            # Store in memory so when Creator replies, agent knows what they're responding to
            try:
                msg_type = "Direct message" if is_direct else "Proactive message"
                _agent_ref.memory.add_short_term(f"[{msg_type} I sent via Discord to {target_desc}]: {content}")
            except Exception:
                pass
        except Exception as e:
            log_outreach_failure("discord", target_desc, str(e))
            notifications.emit_notification(
                "delivery_failed",
                "Discord message failed",
                f"Could not deliver to {target_desc}: {str(e)[:100]}. Falling back to web.",
                {"channel": "discord", "target": target_desc, "error": str(e), "content_preview": content[:100]},
            )
            try:
                notifications.show_desktop_notification(
                    "Discord message failed — check web app",
                    f"Error: {str(e)[:80]}. Message delivered via web instead.",
                )
            except Exception:
                pass
            try:
                notifications.emit_notification("proactive", "Discord message (failed)", content[:200], {"content": content})
                _agent_ref.memory.add_short_term(f"[Message I tried to send via Discord (failed)]: {content}")
            except Exception:
                pass


async def list_connected_channels(guild_id: str | None = None) -> str:
    """Return guild/channel visibility for the connected Discord bot."""
    client = _discord_client
    if not client:
        return "Error: Discord client not started."
    if not client.is_ready():
        return "Error: Discord client is not ready yet."

    rows: list[dict] = []
    guild_filter = str(guild_id or "").strip()
    for guild in client.guilds:
        if guild_filter and str(guild.id) != guild_filter:
            continue
        channels: list[dict] = []
        for ch in sorted(guild.channels, key=lambda c: (getattr(c, "position", 0), str(c.id))):
            channels.append(
                {
                    "id": str(ch.id),
                    "name": getattr(ch, "name", str(ch)),
                    "type": str(getattr(ch, "type", "unknown")),
                    "position": int(getattr(ch, "position", 0)),
                }
            )
        rows.append(
            {
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "channel_count": len(channels),
                "channels": channels,
            }
        )

    if guild_filter and not rows:
        return f"No connected guild matched guild_id={guild_filter}."
    if not rows:
        return "No connected guilds found."
    return json.dumps({"guilds": rows}, indent=2)


async def _handle_voice_addressed(user, text: str, guild_id: int) -> None:
    """Called by ConversationSink when someone in a joined voice channel says
    'Solen' and then speaks. Runs the agent and speaks the reply back into
    the channel."""
    if not _agent_ref or not text.strip():
        return
    try:
        from src import contacts
        from src.agent.soul import get_context_for_speaker
        from src.logging_config import log_voice_event

        log_voice_event("handling_addressed", f"user_id={user.id} text={text!r}")

        author_id = str(user.id)
        author_name = getattr(user, "display_name", None) or str(user)
        try:
            contacts.record_discord_interaction(
                discord_id=author_id, display_name=author_name, content=text
            )
        except Exception:
            pass

        contact = contacts.get_contact("", discord_id=author_id)
        contact_ctx = contacts.format_contact_for_context(contact)
        ctx_prefix = f"[Contact profile: {contact_ctx}]\n\n" if contact_ctx else ""
        speaker_ctx = get_context_for_speaker(is_web=False, discord_id=author_id, author_name=author_name)
        if speaker_ctx:
            ctx_prefix += speaker_ctx
        user_msg = (
            f"{ctx_prefix}Message from {author_name} (Discord voice channel, discord_id={author_id}) "
            f"who just said, addressing you by name: {text}"
        )

        reply = await _agent_ref.chat(user_msg, speaker_discord_id=author_id)
        reply = (reply or "").strip()
        log_voice_event("agent_reply", reply[:200] if reply else "(empty)")
        if not reply:
            return

        vc = _voice_clients.get(guild_id)
        if not vc or not vc.is_connected():
            log_voice_event("speak_skipped", "voice client not connected")
            return

        from src.voice.tts import synthesize
        from src.user_settings import get_tts_voice

        audio_bytes = await synthesize(reply, voice=get_tts_voice())
        log_voice_event("tts_done", f"{len(audio_bytes) if audio_bytes else 0} bytes")
        if not audio_bytes:
            return
        await _speak_in_voice_channel(guild_id, audio_bytes)
        log_voice_event("spoke", "playback finished")

        try:
            _agent_ref.memory.add_short_term(f"[Discord voice – {author_name} said]: {text}")
            _agent_ref.memory.add_short_term(f"Solen (voice): {reply}")
        except Exception:
            pass
    except Exception as e:
        try:
            from src.logging_config import log_error
            log_error("voice_addressed", e)
        except Exception:
            pass


async def _speak_in_voice_channel(guild_id: int, audio_bytes: bytes) -> None:
    """Play mp3 bytes into the guild's active voice connection. Serialized
    per-guild so overlapping replies don't cut each other off."""
    import tempfile
    import discord

    vc = _voice_clients.get(guild_id)
    if not vc or not vc.is_connected():
        return
    lock = _voice_play_locks.setdefault(guild_id, asyncio.Lock())
    async with lock:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            path = f.name
        done = asyncio.Event()
        loop = asyncio.get_event_loop()

        def _after(_error):
            loop.call_soon_threadsafe(done.set)

        try:
            vc.play(discord.FFmpegPCMAudio(path), after=_after)
            await done.wait()
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass


async def join_voice_channel(channel_id: str) -> str:
    """Join a Discord voice channel and start listening for the wake word
    ('Solen'). Command-only — never called automatically."""
    client = _discord_client
    if not client or not client.is_ready():
        return "Error: Discord client not ready."
    try:
        import discord
        from discord.ext import voice_recv
    except ImportError as e:
        return f"Error: voice support not installed ({e}). Run: pip install discord-ext-voice-recv"

    # discord.py loads Opus for *encoding* (speaking) automatically when a
    # voice client connects, but never for *decoding* incoming audio — without
    # this, listen() silently receives nothing to decode and write() on the
    # sink never fires. Must happen before connect().
    if not discord.opus.is_loaded():
        try:
            discord.opus._load_default()
        except Exception as e:
            return f"Error: could not load Opus codec, voice receive won't work ({e})"

    try:
        cid = int(channel_id)
    except ValueError:
        return f"Error: channel_id must be numeric, got {channel_id!r}"

    channel = client.get_channel(cid)
    if channel is None:
        try:
            channel = await client.fetch_channel(cid)
        except Exception as e:
            return f"Error: could not find channel {channel_id}: {e}"
    if not isinstance(channel, discord.VoiceChannel):
        return f"Error: channel {channel_id} ('{getattr(channel, 'name', '?')}') is not a voice channel."

    guild_id = channel.guild.id
    existing = _voice_clients.get(guild_id)
    if existing and existing.is_connected():
        if existing.channel and existing.channel.id == cid:
            return f"Already connected to '{channel.name}'."
        await existing.move_to(channel)
        return f"Moved to voice channel '{channel.name}'."

    try:
        vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
    except Exception as e:
        return f"Error joining voice channel: {e}"

    from src.voice.voice_call import ConversationSink

    sink = ConversationSink(on_addressed=lambda user, text: _handle_voice_addressed(user, text, guild_id))
    vc.listen(sink)
    _voice_clients[guild_id] = vc
    try:
        from src.logging_config import log_voice_event

        log_voice_event(
            "listening_started",
            f"channel={channel.name} opus_loaded={discord.opus.is_loaded()} vc_connected={vc.is_connected()}",
        )
    except Exception:
        pass
    return f"Joined voice channel '{channel.name}'. Listening — say 'Solen' to address me."


async def leave_voice_channel(channel_id: str = "") -> str:
    """Leave a voice channel. If channel_id is omitted and only one is
    active, leaves that one."""
    if not _voice_clients:
        return "Not connected to any voice channel."

    guild_id = None
    if channel_id:
        try:
            cid = int(channel_id)
        except ValueError:
            return f"Error: channel_id must be numeric, got {channel_id!r}"
        for gid, vc in _voice_clients.items():
            if vc.channel and vc.channel.id == cid:
                guild_id = gid
                break
        if guild_id is None:
            return f"Not connected to channel {channel_id}."
    elif len(_voice_clients) == 1:
        guild_id = next(iter(_voice_clients))
    else:
        names = ", ".join(str(vc.channel) for vc in _voice_clients.values())
        return f"Connected to multiple voice channels ({names}) — specify channel_id."

    vc = _voice_clients.pop(guild_id, None)
    _voice_play_locks.pop(guild_id, None)
    if vc:
        name = str(vc.channel) if vc.channel else "voice channel"
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        return f"Left '{name}'."
    return "Not connected."


def start_discord_task():
    """Start Discord bot and outreach consumer. Returns the task."""
    async def _run():
        consumer = asyncio.create_task(_outreach_consumer())
        try:
            await _run_discord_bot()
        finally:
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass

    return asyncio.create_task(_run())
