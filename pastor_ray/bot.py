from pastor_ray import reread
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from pastor_ray.brain import Brain
from pastor_ray.music import Choir
from pastor_ray.schedule import due_slot, next_prayer
from pastor_ray.settings import ROOT, load_config
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
**Voice first:** sermon requests join Meditation Vibes. Say "Ray" plus your question to interrupt speech. `!ray talk` starts a voice conversation without a sermon.
**Private:** `!ray remember <note>`, `!ray memory`, `!ray forget`.
**Study plans:** `!ray plan start John` (or prayer/forgiveness/faith), `!ray plan current`, `next`, `pause`, `resume`, `reflect <thought>`, `pace <preference>`.
**Long-term recall:** `!ray recall <topic>` or ask naturally in a DM. Original private conversations stay saved until you forget them.
**Bible:** `!ray bible John 3:16` (KJV; chapters/ranges up to 20 verses per request).
**Share a prayer request:** `!ray request <text>` includes that text in public community prayers for seven days; omit names/private details. `!ray unrequest` removes it.
**Owner only:** `!ray reachout <user ID or @mention> <exact message>`.
Daily prayers: 8 AM, 1 PM, 8 PM America/New_York, posted in Inspirational Vibes and spoken in Meditation Vibes. Hosts: `!ray prayer <topic>` starts a public spoken prayer and leaves afterward.
Slash shortcut: `/ray action` (help, play, pause, resume, skip, stop, playlist, credits, status).
'''


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


def owner_allowed(uid, cfg):
    return int(uid) == cfg["owner_id"]


def music_allowed(uid, cfg):
    return owner_allowed(uid, cfg) or int(uid) in cfg["music_controller_ids"]


def public_chat_allowed(message, cfg, bot_id):
    if message.channel.id not in {cfg["text_channel_id"], cfg["voice_channel_id"]}:
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
        self.cfg = load_config()
        self.store = Store(ROOT / "data" / "ray.sqlite3")
        self.brain = Brain(self.cfg)
        self.choir = Choir(self, self.cfg)
        self.sermon = SermonSession(self)
        self.tree = app_commands.CommandTree(self)
        self.user_locks = {}
        self.pending_chats = 0
        self.last_error = ""
        self.public_content_enabled = message_content
        self.public_history = {}
        self.play_on_start = play_on_start
        self.startup_announced = False
        self._register_commands()

    def _register_commands(self):
        @self.tree.command(name='sermon',description='Host a spoken sermon in Meditation Vibes, or control the current session.')
        async def sermon(interaction: discord.Interaction, topic: str):
            await interaction.response.defer(ephemeral=True)
            if interaction.guild_id != self.cfg['guild_id']:
                await interaction.followup.send('Use this in the configured server.',ephemeral=True)
                return
            result = await self.command(interaction.user.id,'sermon',topic,private=False)
            await interaction.followup.send(result[:1900],ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

        @self.tree.command(name='ask',description='Queue a PUBLIC sermon question to be answered aloud.')
        async def ask(interaction: discord.Interaction, question: str):
            if interaction.guild_id != self.cfg['guild_id'] or interaction.channel_id not in {self.cfg['voice_channel_id'],self.cfg['text_channel_id']}:
                await interaction.response.send_message('Ask in Meditation Vibes or Inspirational Vibes.',ephemeral=True)
                return
            await interaction.response.send_message(self.sermon.ask(interaction.user.id,question),ephemeral=True)

        @self.tree.command(name="ray", description="Pastor Ray: choir controls and help. DM for personal guidance.")
        @app_commands.choices(action=[app_commands.Choice(name=s, value=s) for s in
            ("help", "play", "pause", "resume", "skip", "stop", "playlist", "credits", "status")])
        async def ray(interaction: discord.Interaction, action: app_commands.Choice[str]):
            await interaction.response.defer(ephemeral=True)
            if interaction.guild_id != self.cfg["guild_id"]:
                await interaction.followup.send("Use this shortcut in the configured server.", ephemeral=True)
                return
            try:
                result = await self.command(interaction.user.id, action.value, "", private=False)
                await interaction.followup.send(result[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            except Exception as exc:
                log.warning("Slash command failed: %s", type(exc).__name__)
                await interaction.followup.send("That action failed. Please try again.", ephemeral=True)

    async def setup_hook(self):
        guild = discord.Object(id=self.cfg["guild_id"])
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.prayer_tick.start()
        self.memory_maintenance.start()

    async def on_ready(self):
        await self.change_presence(status=discord.Status.online, activity=discord.Game("DM me for prayer & discipleship"))
        for key in ("text_channel_id", "voice_channel_id"):
            channel = self.get_channel(self.cfg[key])
            if channel:
                permissions = channel.permissions_for(channel.guild.me)
                log.info("Channel ready: %s (%s); view=%s send=%s history=%s connect=%s speak=%s",
                         channel.name, channel.type, permissions.view_channel, permissions.send_messages,
                         permissions.read_message_history, permissions.connect, permissions.speak)
            else:
                log.error("Configured channel unavailable: %s", key)
        log.info("Pastor Ray connected; local model=%s; next prayer=%s", self.cfg["model"], next_prayer(datetime.now(timezone.utc), self.cfg).isoformat())
        if not self.startup_announced:
            channel = self.get_channel(self.cfg['text_channel_id'])
            if channel:
                try:
                    await send_chunks(channel, "**Pastor Ray is online.** I'm here for prayer, conversation, and discipleship. Ask me naturally for a spoken prayer or sermon in Meditation Vibes, or DM me to talk privately.")
                    self.startup_announced = True
                    log.info('Startup announcement delivered to Inspirational Vibes')
                except discord.HTTPException:
                    log.warning('Could not deliver the startup announcement')
        # One-shot local operator request, consumed before dispatch to prevent replay.
        request_path=ROOT/'data'/'startup-service.json'
        if request_path.exists():
            request=json.loads(request_path.read_text(encoding='utf-8'))
            request_path.unlink()
            if datetime.now(timezone.utc).timestamp()<request.get('expires',0):
                result=await self.sermon.start(request['topic'])
                await self.sermon.announce(result)
                log.info('Explicit operator service request: active=%s result=%s',self.sermon.active,result)
        if self.play_on_start:
            self.play_on_start = False
            try:
                result = await self.command(self.cfg['owner_id'], 'play', '', private=False)
                log.info("Owner-requested startup playback: %s", result)
            except Exception:
                log.exception("Owner-requested startup playback failed")

    async def member(self, uid):
        guild = self.get_guild(self.cfg["guild_id"])
        if guild is None:
            return None
        try:
            return guild.get_member(uid) or await guild.fetch_member(uid)
        except (discord.NotFound, discord.Forbidden):
            return None

    async def on_message(self, message):
        if message.author.bot or not message.content.strip():
            return
        private = isinstance(message.channel, discord.DMChannel)
        if not private and (message.guild is None or message.guild.id != self.cfg["guild_id"]):
            return
        if private and not await self.member(message.author.id):
            await message.channel.send("I'm available to members of my Discord community. Please join the server first.")
            return
        text = message.content.strip()
        session = getattr(self,'sermon',None)
        if session and (private or public_chat_allowed(message,self.cfg,self.user.id)):
            if reread.requested(text):
                await send_chunks(message.channel,await reread.handle(self,message))
                return
            sermon_action = sermon_intent(text)
            if sermon_action:
                if sermon_action[0]=='prayer' and not private and music_allowed(message.author.id,self.cfg) and not session.active:
                    await message.channel.send('I am preparing that prayer and its audio now. I will join Meditation Vibes and speak it as soon as it is ready.',allowed_mentions=discord.AllowedMentions.none())
                result = await self.command(message.author.id,*sermon_action,private=private)
                await send_chunks(message.channel,result)
                return
            if re.search(r'\b(?:sermon|preach|service)\b',text,re.I) and re.search(r'\b(?:give|want|need|get|deliver|do|start|join)\b',text,re.I) and not re.search(r'\b(?:write|draft|text|explain|what|why|how)\b',text,re.I):
                await message.channel.send('For a spoken sermon, say **Ray, preach about <topic>**, **give me a morning sermon**, or use **!ray sermon <topic>**. I have not started a voice session from that wording.')
                return
            if not private and session.active and not music_intent(text) and (any(m.id==self.user.id for m in getattr(message,'mentions',[])) or re.match(r'^(?:hey[, ]+)?(?:pastor )?ray\b',text,re.I)):
                await send_chunks(message.channel,session.ask(message.author.id,text))
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
                    result = await self.command(message.author.id, name, args, private=private)
                    await send_chunks(message.channel, result)
                except Exception as exc:
                    log.warning("Command failed: %s", type(exc).__name__)
                    await message.channel.send("That action couldn't finish. Please try again; !ray status can help.")
            return
        if private or public_chat_allowed(message, self.cfg, self.user.id):
            action = music_intent(text)
            if action:
                try:
                    async with message.channel.typing():
                        result = await self.command(message.author.id, action, "", private=private)
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
            if public_chat_allowed(message, self.cfg, self.user.id):
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

    async def command(self, uid, name, args, *, private):
        session = getattr(self,'sermon',None)
        if name in {'talk','voice'}:
            name,args='sermon','conversation'
        if name=='prayer':
            if not music_allowed(uid,self.cfg):
                return 'Only Brandon and configured hosts can start public voice prayers.'
            if private:
                return 'Request a spoken prayer in the server chat with !ray prayer <topic>; private mentoring stays in DMs.'
            return await session.prayer(args or 'community')
        if name in {'sermon','ask','topic','topics'}:
            if name=='ask':
                if private:
                    return 'Ask sermon questions in Meditation Vibes or Inspirational Vibes using !ray ask. Your DMs stay private.'
                return session.ask(uid,args)
            if name=='topics':
                return 'Suggested sermon topics:\n'+'\n'.join(session.requests) if session.requests else 'No suggested topics yet. Use !ray topic <topic> in public chat.'
            if name=='topic':
                if private:
                    return 'Suggest public sermon topics in a server channel using !ray topic <topic>.'
                if not args.strip() or len(args)>250:
                    return 'Use !ray topic <topic>, up to 250 characters.'
                if len(session.requests)>=10:
                    return 'The topic list is full. A host can use !ray sermon clear-topics after reviewing it.'
                session.requests.append(args.strip())
                return 'Topic added for a host to choose. It has not started a sermon.'
            if args.strip().lower()=='status':
                return session.status()
            if not music_allowed(uid,self.cfg):
                return 'Only Brandon and configured hosts can start or control sermons. Suggest !ray topic <topic> in public chat.'
            action = args.strip().lower()
            if action=='clear-topics':
                session.requests.clear()
                return 'Suggested topics cleared.'
            if action in {'pause','resume','stop','end','end choir','stop choir','listen on','listen off'}:
                result = await session.control(action if action.startswith('listen ') else action.split()[0])
                if action.endswith(' choir'):
                    result += '\n'+await self.choir.start()
                return result
            return await session.start(args)
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
            return (f"{self.choir.status()}\n{session.status() if session else ''}\nBrain: local Joe Speedboat (Ollama).\n"
                    f"Next prayer: {next_prayer(datetime.now(timezone.utc), self.cfg):%a %I:%M %p %Z}.\n"
                    f"Last prayer: {self.store.last_prayer() or 'none yet'}.\n"
                    f"Public context: {'enabled' if self.public_content_enabled else 'Message Content Intent needs enabling in Discord'}.\n"
                    f"Last conversation error: {self.last_error or 'none'}.")
        if name in {"playlist", "credits"}:
            return self.choir.credits() or "No recordings installed yet."
        if name in {"play", "pause", "resume", "skip", "stop"}:
            if not music_allowed(uid, self.cfg):
                return "Choir controls are currently limited to Brandon and configured music controllers."
            if session and session.active:
                if name in {'stop','pause','resume'}:
                    return await session.control(name)
                return 'A sermon session is active. Use !ray sermon end choir to finish and start music.'
            if name == "play":
                if self.choir.voice and self.choir.voice.is_paused():
                    return self.choir.control("resume")
                return await self.choir.start()
            if name == "stop":
                return await self.choir.stop()
            return self.choir.control(name)
        if name == "reachout":
            if not owner_allowed(uid, self.cfg):
                return "Only Brandon can authorize me to initiate a DM."
            match = re.fullmatch(r"(?:<@!?(\d+)>|(\d+))\s+([\s\S]+)", args)
            if not match:
                return "Use !ray reachout <user ID or @mention> <exact message>."
            target = await self.member(int(match[1] or match[2]))
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
                self.store.share_request(uid, args.strip())
                return "That request may be included in public prayers for the next seven days. Use !ray unrequest to remove it."
            with self.store.db:
                self.store.db.execute("DELETE FROM requests WHERE uid=?", (str(uid),))
            return "Removed your shared prayer request."
        return "I don't recognize that command. Use !ray help."

    async def public_context(self):
        if not self.public_content_enabled:
            return []
        messages = []
        after = datetime.now(timezone.utc) - timedelta(hours=18)
        for channel_id in self.cfg["public_context_channel_ids"]:
            channel = self.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.cfg["guild_id"]:
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
        if not self.cfg["prayers_enabled"]:
            return
        slot = due_slot(datetime.now(timezone.utc), self.cfg)
        if slot is None:
            return
        channel = self.get_channel(self.cfg["text_channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return
        if not self.store.claim_prayer(slot):
            return
        hour = int(slot[11:13])
        period = {8: "morning", 13: "midday", 20: "evening"}.get(hour, "community")
        try:
            try:
                prayer = await asyncio.wait_for(self.brain.prayer(period, await self.public_context(), self.store.public_requests()), timeout=120)
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
                self.store.prayer_result(slot,"sent",sent.id)
            session=getattr(self,'sermon',None)
            if session:
                result=await session.prayer(period,text=prayer[:1750],publish=publish)
                if not result.startswith('Prayer spoken'):
                    if not published:
                        await publish(prayer[:1750])
                    await channel.send(result,allowed_mentions=discord.AllowedMentions.none())
                    self.store.prayer_result(slot,"failed",detail='voice-prayer-unavailable')
            else:
                await publish(prayer[:1750])
            log.info("Scheduled prayer processed: %s",slot)
        except Exception as exc:
            self.store.prayer_result(slot, "failed", detail=type(exc).__name__)
            log.error("Prayer delivery failed: %s (%s)", slot, type(exc).__name__)

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
        if self.sermon.active:
            if member.bot and member.id != self.user.id and after.channel and after.channel.id==self.cfg['voice_channel_id']:
                await self.sermon.control('end')
                return
            if member.id==self.user.id and before.channel and (not after.channel or after.channel.id!=self.cfg['voice_channel_id']):
                if self.sermon.voice:
                    await self.sermon.control('end')
            if not member.bot and self.sermon.listening:
                await self.sermon.refresh_listening()
        if self.choir.voice and after.channel and after.channel.id == self.cfg["voice_channel_id"]:
            if member.bot and member.id != self.user.id:
                await self.choir.stop()
                log.info("Choir yielded voice to another bot")

    async def close(self):
        self.prayer_tick.cancel()
        self.memory_maintenance.cancel()
        await self.sermon.control('end')
        await self.choir.stop()
        await self.brain.close()
        self.store.close()
        await super().close()
