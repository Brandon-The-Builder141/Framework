from pastor_ray import reread
import asyncio
import contextlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import tasks

from pastor_ray.brain import Brain
from pastor_ray.guild_config import GuildConfig
from pastor_ray.music import Choir
from pastor_ray.schedule import due_slot, next_prayer
from pastor_ray.settings import ROOT, load_config, load_globals
from pastor_ray.storage import Store
from pastor_ray.scripture import passages
from pastor_ray.music_intent import music_intent
from pastor_ray import discipleship
from pastor_ray.sermons import SermonSession, intent as sermon_intent

log = logging.getLogger("pastor_ray")
HELP = '''**Pastor Ray** — DM me to talk, pray, or study Scripture at your pace.
I also answer text messages in Inspirational Vibes and Meditation Vibes. Personal mentoring is best in DMs.
I'm a digital faith companion. DM history is saved locally for continuity, separate from public prayers. Use `!ray forget` to erase it.

**Choir:** `!ray play`, `pause`, `resume`, `skip`, `stop`, `playlist`, `credits`, `status`.
**Sermons:** hosts use `!ray sermon forgiveness 5 minutes`, `!ray sermon pause/resume/end/status`, or `!ray sermon end choir` to bring back music.
**Church services:** say "Ray, give me a morning sermon" (about 15 minutes), or `!ray sermon morning 20 minutes`. Includes four KJV verses, context, explanation, application, and prayer, followed by Q&A.
**Public questions:** `!ray ask <question>` during a session. Anyone can suggest `!ray topic <topic>`; hosts see `!ray topics`.
**Spoken questions:** during sermons or Q&A, say "Ray" then your question to interrupt. Use `!ray talk` for conversation without a sermon. Hosts: `!ray sermon listen off` / `!ray sermon listen on`.
**Read an earlier excerpt:** reply to my message with `!ray reread` or "Ray, read this aloud". A Discord message link also works with `!ray reread <link>`.
**Voice first:** sermon requests join Meditation Vibes. Say "Ray" plus your question to interrupt speech. `!ray talk` starts a voice conversation without a sermon. Hosts: `!ray sermon listen off` / `!ray sermon listen on`.
**Private:** `!ray remember <note>`, `!ray memory`, `!ray forget`.
**Study plans:** `!ray plan start John` (or prayer/forgiveness/faith), `!ray plan current`, `next`, `pause`, `resume`, `reflect <thought>`, `pace <preference>`.
**Long-term recall:** `!ray recall <topic>` or ask naturally in a DM. Original private conversations stay saved until you forget them.
**Bible:** `!ray bible John 3:16` (KJV; chapters/ranges up to 20 verses per request).
**Share a prayer request:** `!ray request <text>` includes that text in public community prayers for seven days; omit names/private details. `!ray unrequest` removes it.
**Owner only:** `!ray reachout <user ID or @mention> <exact message>`.
Daily prayers: 8 AM, 1 PM, 8 PM America/New_York, posted in Inspirational Vibes and spoken in Meditation Vibes. Hosts: `!ray prayer <topic>` starts a public spoken prayer and leaves afterward.
Slash shortcut: `/ray action` (help, play, pause, resume, skip, stop, playlist, credits, status).
'''

SETUP_TIMEOUT = 600  # seconds to finish the !ray setup questionnaire

WELCOME = '''**Pastor Ray has joined the server.**
I'm a faith companion for your Discord — daily prayers, Bible study, sermons in voice chat, and private discipleship in DMs.

A server admin should run `!ray setup` so I know which channels to use, plus prayer times and timezone. Until then I'll use the defaults: prayers at 8am, 1pm, 8pm Eastern.

Type `!ray help` anytime for the full list. I'm not a replacement for your pastor — I'm the companion for the hours in between.'''


async def send_chunks(destination, text):
    text = text.strip()
    while text:
        cut = min(1900, len(text))
        if cut < len(text):
            boundary = text.rfind("\n", 0, cut)
            if boundary > 900:
                cut = boundary
        await destination.send(text[:cut], allowed_mentions=discord.AllowedMentions.none())
        text = text[cut:].lstrip()


def owner_allowed(uid, g):
    return int(uid) == g["owner_id"]


def music_allowed(uid, gcfg, g):
    return owner_allowed(uid, g) or (gcfg is not None and int(uid) in gcfg.music_controller_ids)


def public_chat_allowed(message, gcfg, bot_id):
    if gcfg is None:
        return False
    if message.channel.id not in {gcfg.text_channel_id, gcfg.voice_channel_id}:
        return False
    addressed = any(m.id == bot_id for m in getattr(message, "mentions", [])) or bool(re.search(r"\b(?:pastor\s+)?ray\b", message.content, re.I))
    other_bot = any(m.bot and m.id != bot_id for m in getattr(message, "mentions", []))
    if not addressed and (other_bot or re.search(r"\bgarth\b", message.content, re.I)):
        return False
    return not message.content.lstrip().startswith(("!", "/"))


class Ray(discord.Client):
    def __init__(self, *, message_content=True, play_on_start=False):
        intents = discord.Intents.default()
        intents.message_content = message_content
        intents.voice_states = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        raw = load_config()
        self.globals = load_globals(raw)
        self.store = Store(ROOT / "data" / "ray.sqlite3")
        # Zero-downtime migration for the original single-server database.
        self.store.seed_guild_from_legacy(raw)
        self.store.migrate_guild_scoping(int(raw["guild_id"]))
        self.guild_cache = {g.guild_id: g for g in self.store.active_guilds()}
        self.brain = Brain(self.globals)
        self.sermon_sessions = {}
        self.choir_sessions = {}
        self.tree = app_commands.CommandTree(self)
        self.user_locks = {}
        self.pending_chats = 0
        self.last_error = ""
        self.public_content_enabled = message_content
        self.public_history = {}
        self.play_on_start = play_on_start
        self._setups = {}
        self._register_commands()

    # ---- per-guild accessors ----

    def guild_config(self, guild_id):
        """GuildConfig for a server, or None when Ray isn't set up there."""
        if guild_id is None:
            return None
        gid = int(guild_id)
        gcfg = self.guild_cache.get(gid)
        if gcfg is None:
            gcfg = self.store.get_guild(gid)
            if gcfg is not None:
                self.guild_cache[gid] = gcfg
        return gcfg

    def sermon_for(self, guild_id):
        gid = int(guild_id)
        session = self.sermon_sessions.get(gid)
        if session is None:
            session = SermonSession(self, gid)
            self.sermon_sessions[gid] = session
        return session

    def choir_for(self, guild_id):
        gid = int(guild_id)
        choir = self.choir_sessions.get(gid)
        if choir is None:
            gcfg = self.guild_config(gid)
            if gcfg is None:
                raise RuntimeError(f"Guild {gid} is not configured")
            choir = Choir(self, gcfg)
            self.choir_sessions[gid] = choir
        return choir

    async def member(self, uid, guild_id):
        guild = self.get_guild(int(guild_id))
        if guild is None:
            return None
        try:
            return guild.get_member(uid) or await guild.fetch_member(uid)
        except (discord.NotFound, discord.Forbidden):
            return None

    async def primary_guild_for(self, uid):
        """First active server where this user is a member (for DM context)."""
        for gcfg in self.store.active_guilds():
            if await self.member(uid, gcfg.guild_id):
                return gcfg
        return None

    def _register_commands(self):
        @self.tree.command(name='sermon',description='Host a spoken sermon in Meditation Vibes, or control the current session.')
        async def sermon(interaction: discord.Interaction, topic: str):
            await interaction.response.defer(ephemeral=True)
            if self.guild_config(interaction.guild_id) is None:
                await interaction.followup.send("I'm not set up on this server yet — a server admin can run `!ray setup`.",ephemeral=True)
                return
            result = await self.command(interaction.user.id,'sermon',topic,private=False,guild_id=interaction.guild_id)
            await interaction.followup.send(result[:1900],ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

        @self.tree.command(name='ask',description='Queue a PUBLIC sermon question to be answered aloud.')
        async def ask(interaction: discord.Interaction, question: str):
            gcfg = self.guild_config(interaction.guild_id)
            if gcfg is None or interaction.channel_id not in {gcfg.voice_channel_id, gcfg.text_channel_id}:
                await interaction.response.send_message("I'm not set up here yet, or ask from the prayer or voice channel.",ephemeral=True)
                return
            await interaction.response.send_message(self.sermon_for(gcfg.guild_id).ask(interaction.user.id,question),ephemeral=True)

        @self.tree.command(name="ray", description="Pastor Ray: choir controls and help. DM for personal guidance.")
        @app_commands.choices(action=[app_commands.Choice(name=s, value=s) for s in
            ("help", "play", "pause", "resume", "skip", "stop", "playlist", "credits", "status")])
        async def ray(interaction: discord.Interaction, action: app_commands.Choice[str]):
            await interaction.response.defer(ephemeral=True)
            if self.guild_config(interaction.guild_id) is None:
                await interaction.followup.send("I'm not set up on this server yet — a server admin can run `!ray setup`.", ephemeral=True)
                return
            try:
                result = await self.command(interaction.user.id, action.value, "", private=False, guild_id=interaction.guild_id)
                await interaction.followup.send(result[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            except Exception as exc:
                log.warning("Slash command failed: %s", type(exc).__name__)
                await interaction.followup.send("That action failed. Please try again.", ephemeral=True)

    async def setup_hook(self):
        # Global command sync: one registration serves every server.
        await self.tree.sync()
        self.prayer_tick.start()
        self.memory_maintenance.start()

    async def on_ready(self):
        await self.change_presence(status=discord.Status.online, activity=discord.Game("DM me for prayer & discipleship"))
        for gcfg in self.store.active_guilds():
            self.guild_cache[gcfg.guild_id] = gcfg
            for key in ("text_channel_id", "voice_channel_id"):
                channel = self.get_channel(getattr(gcfg, key))
                if channel:
                    permissions = channel.permissions_for(channel.guild.me)
                    log.info("Guild %s channel ready: %s (%s); view=%s send=%s history=%s connect=%s speak=%s",
                             gcfg.guild_id, channel.name, channel.type, permissions.view_channel, permissions.send_messages,
                             permissions.read_message_history, permissions.connect, permissions.speak)
                else:
                    log.error("Guild %s configured channel unavailable: %s", gcfg.guild_id, key)
            log.info("Pastor Ray connected; guild=%s local model=%s; next prayer=%s",
                     gcfg.guild_id, self.globals.get("model"), next_prayer(datetime.now(timezone.utc), gcfg.sched()).isoformat())
            if not gcfg.startup_announced:
                channel = self.get_channel(gcfg.text_channel_id)
                if channel:
                    try:
                        await send_chunks(channel, "**Pastor Ray is online.** I'm here for prayer, conversation, and discipleship. Ask me naturally for a spoken prayer or sermon in Meditation Vibes, or DM me to talk privately.")
                        gcfg.startup_announced = True
                        self.store.upsert_guild(gcfg)
                        log.info('Startup announcement delivered (guild %s)', gcfg.guild_id)
                    except discord.HTTPException:
                        log.warning('Could not deliver the startup announcement (guild %s)', gcfg.guild_id)
        # One-shot local operator request, consumed before dispatch to prevent replay.
        request_path=ROOT/'data'/'startup-service.json'
        if request_path.exists():
            request=json.loads(request_path.read_text(encoding='utf-8'))
            request_path.unlink()
            guilds = self.store.active_guilds()
            if guilds and datetime.now(timezone.utc).timestamp()<request.get('expires',0):
                sermon = self.sermon_for(guilds[0].guild_id)
                result=await sermon.start(request['topic'])
                await sermon.announce(result)
                log.info('Explicit operator service request: active=%s result=%s',sermon.active,result)
        if self.play_on_start:
            self.play_on_start = False
            try:
                guilds = self.store.active_guilds()
                if guilds:
                    result = await self.command(self.globals['owner_id'], 'play', '', private=False, guild_id=guilds[0].guild_id)
                    log.info("Owner-requested startup playback: %s", result)
            except Exception:
                log.exception("Owner-requested startup playback failed")

    async def on_guild_join(self, guild):
        """First contact with a new server: register it with defaults and say hello."""
        gcfg = GuildConfig(guild_id=guild.id)
        self.store.upsert_guild(gcfg)
        self.guild_cache[gcfg.guild_id] = gcfg
        log.info("Joined new guild %s; registered with default config", guild.id)
        target = guild.system_channel
        if target is None:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    target = channel
                    break
        if target is not None:
            try:
                await send_chunks(target, WELCOME)
            except discord.HTTPException:
                log.warning("Could not deliver welcome message (guild %s)", guild.id)

    async def on_guild_remove(self, guild):
        self.store.set_guild_active(guild.id, False)
        self.guild_cache.pop(int(guild.id), None)
        log.info("Removed from guild %s; config kept for rejoin", guild.id)

    # ---- !ray setup questionnaire ----

    @staticmethod
    def _parse_channel_mention(text):
        match = re.search(r"<#(\d+)>", text)
        if match:
            return int(match[1])
        stripped = text.strip()
        return int(stripped) if stripped.isdigit() else None

    @staticmethod
    def _parse_hours(text):
        if text.strip().lower() == "default":
            return [8, 13, 20]
        try:
            hours = sorted({int(p) for p in re.split(r"[,\s]+", text.strip()) if p})
        except ValueError:
            return None
        if not hours or any(h < 0 or h > 23 for h in hours) or len(hours) > 6:
            return None
        return hours

    @staticmethod
    def _parse_timezone(text):
        if text.strip().lower() == "default":
            return "America/New_York"
        try:
            ZoneInfo(text.strip())
        except (ZoneInfoNotFoundError, ValueError):
            return None
        return text.strip()

    async def _handle_setup_answer(self, message, guild_id):
        key = (int(guild_id), int(message.author.id))
        sess = self._setups.get(key)
        if sess is None:
            return False
        if time.time() > sess["expires"]:
            self._setups.pop(key, None)
            return False
        text = message.content.strip()
        if re.match(r"^!ray\s+setup\s+cancel", text, re.I):
            self._setups.pop(key, None)
            await message.channel.send("Setup cancelled. Run `!ray setup` anytime to try again.")
            return True
        if text.startswith("!"):
            return False  # let normal command dispatch handle it
        step, data = sess["step"], sess["data"]
        if step == 0:
            cid = self._parse_channel_mention(text)
            channel = self.get_channel(cid) if cid else None
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != int(guild_id):
                await message.channel.send("I couldn't find that text channel in this server. Mention it like #prayers, or paste its channel ID.")
                return True
            data["text_channel_id"] = channel.id
            sess["step"] = 1
            await message.channel.send("Got it. **Which voice channel** should I join for sermons and spoken prayers? Mention it or paste its ID.")
        elif step == 1:
            cid = self._parse_channel_mention(text)
            channel = self.get_channel(cid) if cid else None
            if not isinstance(channel, discord.VoiceChannel) or channel.guild.id != int(guild_id):
                await message.channel.send("I couldn't find that voice channel in this server. Mention it or paste its ID.")
                return True
            data["voice_channel_id"] = channel.id
            sess["step"] = 2
            await message.channel.send("Almost done. **What times** should I post daily prayers? Send hours like `8 13 20` (24-hour clock), or `default` for 8am, 1pm, 8pm Eastern.")
        elif step == 2:
            hours = self._parse_hours(text)
            if hours is None:
                await message.channel.send("I need hours like `8 13 20` (up to 6 times), or just say `default`.")
                return True
            data["prayer_hours"] = hours
            sess["step"] = 3
            await message.channel.send("Last one: **what timezone** is this community in? Something like `America/Chicago` — or `default` for Eastern.")
        elif step == 3:
            tz = self._parse_timezone(text)
            if tz is None:
                await message.channel.send("I didn't recognize that timezone. Try something like `America/Denver`, or `default`.")
                return True
            data["timezone"] = tz
            existing = self.store.get_guild(guild_id)
            gcfg = GuildConfig(
                guild_id=int(guild_id),
                text_channel_id=data["text_channel_id"],
                voice_channel_id=data["voice_channel_id"],
                timezone=data["timezone"],
                prayer_hours=data["prayer_hours"],
                prayers_enabled=True,
                public_context_channel_ids=[data["text_channel_id"]],
                music_controller_ids=existing.music_controller_ids if existing else [],
            )
            self.store.upsert_guild(gcfg)
            self.guild_cache[int(guild_id)] = gcfg
            self._setups.pop(key, None)
            times = ", ".join(f"{h}:00" for h in gcfg.prayer_hours)
            await message.channel.send(
                f"**Pastor Ray is set up.** I'll post daily prayers at {times} ({gcfg.timezone}). "
                "Type `!ray help` for everything I can do.")
        return True

    async def on_message(self, message):
        if message.author.bot or not message.content.strip():
            return
        private = isinstance(message.channel, discord.DMChannel)
        guild = getattr(message, "guild", None)
        guild_id = guild.id if guild is not None else None
        if not private and guild_id is not None:
            if await self._handle_setup_answer(message, guild_id):
                return
            gcfg = self.guild_config(guild_id)
            if gcfg is None:
                text = message.content.strip()
                if re.match(r"^!ray\b", text, re.I) or re.search(r"\bray\b", text, re.I):
                    await message.channel.send("I'm not set up on this server yet — a server admin can run `!ray setup`.")
                return
        elif private:
            if await self.primary_guild_for(message.author.id) is None:
                await message.channel.send("I'm available to members of my Discord community. Please join the server first.")
                return
            gcfg = None
        else:
            return
        text = message.content.strip()
        sermon = self.sermon_for(guild_id) if (gcfg is not None and guild_id is not None) else None
        if sermon and (private or public_chat_allowed(message, gcfg, self.user.id)):
            if reread.requested(text):
                await send_chunks(message.channel, await reread.handle(self, message))
                return
            sermon_action = sermon_intent(text)
            if sermon_action:
                if sermon_action[0]=='prayer' and not private and music_allowed(message.author.id, gcfg, self.globals) and not sermon.active:
                    await message.channel.send('I am preparing that prayer and its audio now. I will join Meditation Vibes and speak it as soon as it is ready.',allowed_mentions=discord.AllowedMentions.none())
                result = await self.command(message.author.id,*sermon_action,private=private,guild_id=guild_id)
                await send_chunks(message.channel,result)
                return
            if re.search(r'\b(?:sermon|preach|service)\b',text,re.I) and re.search(r'\b(?:give|want|need|get|deliver|do|start|join)\b',text,re.I) and not re.search(r'\b(?:write|draft|text|explain|what|why|how)\b',text,re.I):
                await message.channel.send('For a spoken sermon, say **Ray, preach about <topic>**, **give me a morning sermon**, or use **!ray sermon <topic>**. I have not started a voice session from that wording.')
                return
            if not private and sermon.active and not music_intent(text) and (any(m.id==self.user.id for m in getattr(message,'mentions',[])) or re.match(r'^(?:hey[, ]+)?(?:pastor )?ray\b',text,re.I)):
                await send_chunks(message.channel,sermon.ask(message.author.id,text))
                return
        plan_action = discipleship.intent(text) if private else None
        if plan_action:
            lock = self.user_locks.setdefault(message.author.id, asyncio.Lock())
            async with lock:
                await send_chunks(message.channel, discipleship.command(self.store,message.author.id,plan_action))
            return
        command_match = re.match(r"^!ray(?:\s+|$)", text, re.I)
        if command_match:
            parts = text[command_match.end():].split(maxsplit=1)
            name, args = (parts[0].lower(), parts[1] if len(parts)>1 else "") if parts else ("help", "")
            lock = self.user_locks.setdefault(message.author.id, asyncio.Lock())
            async with lock:
                try:
                    result = await self.command(message.author.id, name, args, private=private, guild_id=guild_id)
                    await send_chunks(message.channel, result)
                except Exception as exc:
                    log.warning("Command failed: %s", type(exc).__name__)
                    await message.channel.send("That action couldn't finish. Please try again; !ray status can help.")
            return
        if private or public_chat_allowed(message, gcfg, self.user.id):
            action = music_intent(text)
            if action:
                try:
                    async with message.channel.typing():
                        result = await self.command(message.author.id, action, "", private=private, guild_id=guild_id)
                    await send_chunks(message.channel, result)
                    log.info("Natural music request dispatched: %s", action)
                except Exception as exc:
                    log.warning("Natural music action failed: %s", type(exc).__name__)
                    await message.channel.send("I couldn't complete that music action. Please try !ray status, then try again.")
                return
            if re.search(r"\b(?:choir|music|playlist|meditation vibes)\b", text, re.I) and re.search(r"\b(?:join|play|start|pause|resume|skip|stop)\b", text, re.I):
                await message.channel.send("I can join Meditation Vibes and play the choir. I haven't started anything from that message. Say **join and play the choir**, or use **!ray play**.")
                return
        if not private:
            if public_chat_allowed(message, gcfg, self.user.id):
                await self.public_chat(message)
            return
        lock = self.user_locks.setdefault(message.author.id, asyncio.Lock())
        if lock.locked() or self.pending_chats >= 3:
            await message.channel.send("I'm still working through a conversation. Give me a moment, then send that again.")
            return
        self.pending_chats += 1
        try:
            async with lock, message.channel.typing():
                uid = message.author.id
                history = self.store.history(uid)
                profile = self.store.profile(uid)
                saved_id = self.store.archive(uid,'user',text,source_id=message.id)
                if saved_id is None:
                    return  # Discord replay of a message already archived.
                profile['retrieved_sources'] = await self.brain.memories(self.store,uid,text)
                profile['retrieved_sources'] = [r for r in profile['retrieved_sources'] if r['id'] != saved_id]
                profile['study_plan'] = discipleship.context(self.store.plan(uid))
                reply = await self.brain.chat(text, history, profile)
                self.store.archive(uid,'assistant',reply)
                if not history:
                    reply += "\n\n*I'm a digital faith companion. Our conversation is saved locally for continuity; `!ray forget` erases it. DMs aren't used in public prayers. `!ray help` explains the controls.*"
                await send_chunks(message.channel, reply)
                if len(history) >= 12:
                    try:
                        summary = await self.brain.summarize(self.store.history(uid), profile["conversation_summary"])
                        self.store.summarize(uid, summary)
                    except Exception as exc:
                        log.warning("Private continuity update failed: %s", type(exc).__name__)
        except Exception as exc:
            self.last_error = type(exc).__name__
            log.warning("Local conversation failed: %s", self.last_error)
            await message.channel.send("My local conversation engine isn't responding right now. Please try again shortly. Music controls still work.")
        finally:
            self.pending_chats -= 1

    async def public_chat(self, message):
        # Public threads never load private notes, summaries, or DM history.
        key = (message.channel.id, message.author.id)
        lock = self.user_locks.setdefault(key, asyncio.Lock())
        if lock.locked() or self.pending_chats >= 3:
            await message.channel.send("I'm working on a reply—give me a moment, then try again.")
            return
        self.pending_chats += 1
        try:
            async with lock, message.channel.typing():
                history = self.public_history.get(key, [])
                reply = await self.brain.public_chat(message.content, history)
                await send_chunks(message.channel, reply)
                self.public_history[key] = (history + [
                    {"role": "user", "content": message.content[:5000]},
                    {"role": "assistant", "content": reply[:7000]},
                ])[-12:]
                if len(self.public_history)>100:
                    self.public_history.pop(next(iter(self.public_history)))
        except Exception as exc:
            self.last_error = type(exc).__name__
            log.warning("Public conversation failed: %s", self.last_error)
            await message.channel.send("My local conversation engine isn't responding right now. Please try again shortly.")
        finally:
            self.pending_chats -= 1

    async def command(self, uid, name, args, *, private, guild_id=None):
        gcfg = self.guild_config(guild_id) if guild_id is not None else None
        if not private and guild_id is not None and gcfg is None:
            return "I'm not set up on this server yet — a server admin can run `!ray setup`."
        if name in {'talk','voice'}:
            name,args='sermon','conversation'
        if private and name in {'sermon','prayer','play','pause','resume','skip','stop','playlist','credits','status','ask','topic','topics'}:
            # Voice-adjacent commands in a DM resolve to the sender's server.
            primary = await self.primary_guild_for(uid)
            if primary is not None:
                gcfg, guild_id = primary, primary.guild_id
        sermon = self.sermon_for(guild_id) if gcfg is not None else None
        choir = self.choir_for(guild_id) if gcfg is not None else None
        if name == "setup":
            if private:
                return "Run `!ray setup` in your server — I need to know which channels to use there."
            member = await self.member(uid, guild_id)
            is_admin = bool(member is not None and getattr(member.guild_permissions, "administrator", False))
            if not (is_admin or owner_allowed(uid, self.globals)):
                return "Only a server admin can run setup."
            self._setups[(int(guild_id), int(uid))] = {"step": 0, "data": {}, "expires": time.time() + SETUP_TIMEOUT}
            return ("Let's get this server set up. **Which text channel** should I post daily prayers in? "
                    "Mention it like #prayers, or paste its channel ID. (`!ray setup cancel` to stop.)")
        if name=='prayer':
            if private:
                return 'Request a spoken prayer in the server chat with !ray prayer <topic>; private mentoring stays in DMs.'
            if not music_allowed(uid, gcfg, self.globals):
                return 'Only Brandon and configured hosts can start public voice prayers.'
            return await sermon.prayer(args or 'community')
        if name in {'sermon','ask','topic','topics'}:
            if name=='ask':
                if private:
                    return 'Ask sermon questions in Meditation Vibes or Inspirational Vibes using !ray ask. Your DMs stay private.'
                return sermon.ask(uid,args)
            if name=='topics':
                return 'Suggested sermon topics:\n'+'\n'.join(sermon.requests) if sermon.requests else 'No suggested topics yet. Use !ray topic <topic> in public chat.'
            if name=='topic':
                if private:
                    return 'Suggest public sermon topics in a server channel using !ray topic <topic>.'
                if not args.strip() or len(args)>250:
                    return 'Use !ray topic <topic>, up to 250 characters.'
                if len(sermon.requests)>=10:
                    return 'The topic list is full. A host can use !ray sermon clear-topics after reviewing it.'
                sermon.requests.append(args.strip())
                return 'Topic added for a host to choose. It has not started a sermon.'
            if args.strip().lower()=='status':
                return sermon.status()
            if not music_allowed(uid, gcfg, self.globals):
                return 'Only Brandon and configured hosts can start or control sermons. Suggest !ray topic <topic> in public chat.'
            action = args.strip().lower()
            if action=='clear-topics':
                sermon.requests.clear()
                return 'Suggested topics cleared.'
            if action in {'pause','resume','stop','end','end choir','stop choir','listen on','listen off'}:
                result = await sermon.control(action if action.startswith('listen ') else action.split()[0])
                if action.endswith(' choir'):
                    result += '\n'+await choir.start()
                return result
            return await sermon.start(args)
        if name in {'plan','recall'}:
            if not private:
                return 'Please use that command in a DM to keep your personal details private.'
            if name == 'plan':
                return discipleship.command(self.store,uid,args)
            records = await self.brain.memories(self.store,uid,args)
            return json.dumps(records,indent=2,ensure_ascii=False) if records else 'No matching saved conversation found. Try a name, topic, or our first conversation.'
        if name == "help":
            return HELP
        if name == "bible":
            if not private:
                return "DM me for Bible reading and study: !ray bible John 3:16."
            lines = passages(args)
            return "\n\n".join(lines) if lines else "Reference not found. Try !ray bible John 3:16 or !ray bible Psalm 23."
        if name == "status":
            sg = gcfg if gcfg is not None else await self.primary_guild_for(uid)
            if sg is None:
                return "No servers configured yet."
            return (f"{choir.status() if choir else 'Choir idle.'}\n{sermon.status() if sermon else ''}\nBrain: local Joe Speedboat (Ollama).\n"
                    f"Next prayer: {next_prayer(datetime.now(timezone.utc), sg.sched()):%a %I:%M %p %Z}.\n"
                    f"Last prayer: {self.store.last_prayer(sg.guild_id) or 'none yet'}.\n"
                    f"Public context: {'enabled' if self.public_content_enabled else 'Message Content Intent needs enabling in Discord'}.\n"
                    f"Last conversation error: {self.last_error or 'none'}.")
        if name in {"playlist", "credits"}:
            if choir is None:
                return "The choir isn't set up for this conversation. Use these commands in your server."
            return choir.credits() or "No recordings installed yet."
        if name in {"play", "pause", "resume", "skip", "stop"}:
            if not music_allowed(uid, gcfg, self.globals):
                return "Choir controls are currently limited to Brandon and configured music controllers."
            if sermon and sermon.active:
                if name in {'stop','pause','resume'}:
                    return await sermon.control(name)
                return 'A sermon session is active. Use !ray sermon end choir to finish and start music.'
            if choir is None:
                return "The choir isn't available here. Use these commands in your server."
            if name == "play":
                if choir.voice and choir.voice.is_paused():
                    return choir.control("resume")
                return await choir.start()
            if name == "stop":
                return await choir.stop()
            return choir.control(name)
        if name == "reachout":
            if not owner_allowed(uid, self.globals):
                return "Only Brandon can authorize me to initiate a DM."
            match = re.fullmatch(r"(?:<@!?(\d+)>|(\d+))\s+([\s\S]+)", args)
            if not match:
                return "Use !ray reachout <user ID or @mention> <exact message>."
            target = None
            if guild_id is not None:
                target = await self.member(int(match[1] or match[2]), guild_id)
            else:
                # DM context: search every server for the member.
                for sg in self.store.active_guilds():
                    target = await self.member(int(match[1] or match[2]), sg.guild_id)
                    if target is not None:
                        break
            if not target or target.bot:
                return "That person isn't an accessible human member of this server."
            body = match[3].strip()
            if len(body)>1800:
                return "Please keep the outreach message under 1,800 characters."
            await target.send("Brandon asked me to reach out:\n\n" + body, allowed_mentions=discord.AllowedMentions.none())
            with self.store.db:
                self.store.db.execute("INSERT INTO outreach(owner,target,sent) VALUES(?,?,strftime('%s','now'))", (str(uid), str(target.id)))
            return "Sent your message. I'll wait for them to reply."
        if name in {"remember", "memory", "forget", "request", "unrequest"}:
            if not private:
                return "Please use that command in a DM to keep your personal details private."
            if name == "remember":
                if not args.strip():
                    return "Use !ray remember <preference, goal, or note>."
                self.store.note(uid, args.strip())
                return "Saved that private note."
            if name == "memory":
                count = self.store.db.execute('SELECT COUNT(*) FROM turns WHERE uid=?',(str(uid),)).fetchone()[0]
                return f"Your private archive contains {count} messages, retained until you forget them. Ask naturally about a past topic or use !ray recall <topic>.\n" + json.dumps(self.store.profile(uid), indent=2, ensure_ascii=False)
            if name == "forget":
                self.store.forget(uid)
                return "Erased your saved conversation, search memories, study plan, summary, notes, and shared prayer request. Discord's existing messages remain in Discord."
            if name == "request":
                if not args.strip():
                    return "Use !ray request <text you explicitly want included in public prayers>. It expires after seven days."
                rg = gcfg if gcfg is not None else await self.primary_guild_for(uid)
                if rg is None:
                    return "I don't know which community to share that with yet."
                self.store.share_request(uid, args.strip(), rg.guild_id)
                return "That request may be included in public prayers for the next seven days. Use !ray unrequest to remove it."
            with self.store.db:
                self.store.db.execute("DELETE FROM requests WHERE uid=?", (str(uid),))
            return "Removed your shared prayer request."
        return "I don't recognize that command. Use !ray help."

    async def public_context(self, gcfg):
        if not self.public_content_enabled:
            return []
        messages = []
        after = datetime.now(timezone.utc) - timedelta(hours=18)
        channel_ids = gcfg.public_context_channel_ids or [gcfg.text_channel_id]
        for channel_id in channel_ids:
            channel = self.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != gcfg.guild_id:
                continue
            # Never draw prayer context from restricted channels.
            if not channel.permissions_for(channel.guild.default_role).view_channel:
                continue
            try:
                async for msg in channel.history(limit=40, after=after):
                    if not msg.author.bot and not msg.content.startswith("!"):
                        content = re.sub(r"<[@#][^>]+>", "[mention]", msg.content)
                        messages.append(content[:350])
            except discord.Forbidden:
                log.warning("Public context unavailable for configured channel")
        return messages[:40]

    @tasks.loop(seconds=20)
    async def prayer_tick(self):
        for gcfg in self.store.active_guilds():
            try:
                await self._prayer_tick_guild(gcfg)
            except Exception as exc:
                log.warning("Prayer tick failed for guild %s: %s", gcfg.guild_id, type(exc).__name__)

    async def _prayer_tick_guild(self, gcfg):
        if not gcfg.prayers_enabled:
            return
        slot = due_slot(datetime.now(timezone.utc), gcfg.sched())
        if slot is None:
            return
        channel = self.get_channel(gcfg.text_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        if not self.store.claim_prayer(gcfg.guild_id, slot):
            return
        hour = int(slot[11:13])
        period = {8: "morning", 13: "midday", 20: "evening"}.get(hour, "community")
        sermon = self.sermon_for(gcfg.guild_id)
        try:
            try:
                prayer = await asyncio.wait_for(self.brain.prayer(period, await self.public_context(gcfg), self.store.public_requests(gcfg.guild_id)), timeout=120)
            except Exception as exc:
                log.warning("Prayer model unavailable; using general fallback: %s", type(exc).__name__)
                prayer = ("Father, thank You for this community. Give us wisdom for the choices before us, "
                          "patience with one another, courage in difficulty, and grateful hearts. Help us "
                          "notice those who need encouragement and make room for rest. Guide us to walk "
                          "in love and truth today. In Jesus' name, Amen.")
            # The durable slot claim prevents repeated prayers after restart.
            published=False
            async def publish(text):
                nonlocal published
                published=True
                sent=await channel.send(f"**{period.title()} prayer · Pastor Ray**\n\n{text[:1750]}",allowed_mentions=discord.AllowedMentions.none())
                self.store.prayer_result(gcfg.guild_id,slot,"sent",sent.id)
            result=await sermon.prayer(period,text=prayer[:1750],publish=publish)
            if not result.startswith('Prayer spoken'):
                if not published:
                    await publish(prayer[:1750])
                await channel.send(result,allowed_mentions=discord.AllowedMentions.none())
                self.store.prayer_result(gcfg.guild_id,slot,"failed",detail='voice-prayer-unavailable')
            log.info("Scheduled prayer processed: guild=%s slot=%s", gcfg.guild_id, slot)
        except Exception as exc:
            self.store.prayer_result(gcfg.guild_id, slot, "failed", detail=type(exc).__name__)
            log.error("Prayer delivery failed: guild=%s slot=%s (%s)", gcfg.guild_id, slot, type(exc).__name__)

    @prayer_tick.before_loop
    async def before_prayers(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=5)
    async def memory_maintenance(self):
        try:
            self.store.backup()
            # Backfill old retained messages even when their owner is not chatting.
            users = self.store.db.execute("SELECT DISTINCT uid FROM turns WHERE role='user' AND id NOT IN (SELECT turn_id FROM embeddings)").fetchall()
            for row in users:
                uid = row['uid']
                lock = self.user_locks.setdefault(int(uid),asyncio.Lock())
                if not lock.locked():
                    async with lock:
                        await self.brain.memories(self.store,uid,'')
        except Exception as exc:
            log.warning('Memory maintenance failed: %s',type(exc).__name__)

    async def on_voice_state_update(self, member, before, after):
        guild = getattr(member, "guild", None)
        gcfg = self.guild_config(guild.id) if guild is not None else None
        if gcfg is None:
            return
        sermon = self.sermon_for(gcfg.guild_id)
        choir = self.choir_for(gcfg.guild_id)
        if sermon.active:
            if member.bot and member.id != self.user.id and after.channel and after.channel.id==gcfg.voice_channel_id:
                await sermon.control('end')
                return
            if member.id==self.user.id and before.channel and (not after.channel or after.channel.id!=gcfg.voice_channel_id):
                if sermon.voice:
                    await sermon.control('end')
            if not member.bot and sermon.listening:
                await sermon.refresh_listening()
        if choir.voice and after.channel and after.channel.id == gcfg.voice_channel_id:
            if member.bot and member.id != self.user.id:
                await choir.stop()
                log.info("Choir yielded voice to another bot (guild %s)", gcfg.guild_id)

    async def close(self):
        self.prayer_tick.cancel()
        self.memory_maintenance.cancel()
        for session in self.sermon_sessions.values():
            with contextlib.suppress(Exception):
                await session.control('end')
        for choir in self.choir_sessions.values():
            with contextlib.suppress(Exception):
                await choir.stop()
        await self.brain.close()
        self.store.close()
        await super().close()
