# Pastor Ray

Standalone Discord faith companion using local Ollama Joe Speedboat. No cloud AI fallback,
no OpenRouter/OpenAI credentials, and no imports or edits to Garth's bot.

## Run

From the Framework root:

```powershell
python -m pip install -r pastor_ray/requirements.txt
npm ci --prefix pastor_ray/voice_sidecar
python -m pastor_ray.fetch_music
python -m pastor_ray.scripture
python -m unittest pastor_ray.test_ray pastor_ray.test_memory pastor_ray.test_sermons pastor_ray.test_listening -v
.\start-pastor-ray.ps1
```

Requires Ollama running with the model named in config.json, FFmpeg/FFprobe on PATH,
and a Discord bot with Message Content Intent enabled. Bot needs View Channel,
Read Message History, Send Messages, Connect, and Speak in its configured channels.
It uses its own ignored `.env` containing `PASTOR_RAY_DISCORD_BOT_TOKEN`.
Do not add secrets to config.json. Only one instance may bind local port 18763.

## Conversations and discipleship

DM Ray as a member of the configured guild for private mentoring. He also replies to human
text messages in Inspirational Vibes and Meditation Vibes' text chat, except commands or
messages addressed to Garth/another bot. Public exchanges have separate, short in-memory
history per user and channel; they never load private DM history, notes, or summaries.
Ordinary messages in other channels do not trigger replies. Spoken conversations require an explicitly requested voice session.
He leans Baptist, uses KJV with plain-English explanation, adapts depth, and distinguishes
his digital role from human pastoral authority. `!ray bible John 3:16` returns exact text
from a local 66-book KJV database (aruljohn/Bible-kjv, MIT; license retained). Named passages
and common topics supply source text to the model. Explanations are model-generated and
can still be mistaken; exact lookup is deterministic. Source: https://github.com/aruljohn/Bible-kjv

`!ray help` lists commands. `!ray remember <note>` saves preferences/goals. `!ray memory`
shows notes and rolling continuity summary. `!ray forget` deletes locally stored history,
notes, summary, search vectors, study plan and shared request, including Ray-managed backups
(not existing Discord messages or external/OneDrive version history). Private state is held in
`data/ray.sqlite3`, never used as public prayer context. It is local plaintext: the machine
owner and backups/OneDrive may access it. No DM content is written to runtime logs.

### Durable private memory

Original DM conversations are retained without the former 40-message deletion limit.
Existing retained messages migrate without loss; their original dates are unknown. Already
deleted old messages cannot be reconstructed. New messages receive UTC timestamps.
Retrieval combines SQLite full-text search with local `nomic-embed-text:latest` semantic
embeddings, plus explicit earliest-conversation lookup. Only relevant source excerpts and
bounded recent history enter a reply; the rolling summary is supporting context, not the
archive. New corrections take precedence in the prompt. Retrieval is user-scoped and never
used in public replies or public prayers. Model recall is still fallible; `!ray recall <topic>`
shows source records directly, and `!ray memory` shows archive size and continuity notes.
If embeddings fail, keyword retrieval remains available. Pending embeddings backfill every
five minutes. Install the local embedding model with `ollama pull nomic-embed-text:latest`.
Daily SQLite snapshots retain the latest 14 snapshot dates under `data/backups`; they protect
against accidental database damage, not loss of this disk. Restore manually with Ray stopped.
The archive persists months or years while its files remain intact; there is no expiry.

### Personal discipleship plans

In DMs: `!ray plan start John` (any full Bible book name), or prayer, forgiveness, faith.
Books are split into readings of at most 15 verses, with exact local KJV text. Natural
"Let's study John" and "continue my study" also work. Discuss each reading as deeply as
you want. `!ray plan next` explicitly advances; `pause`, `resume`, `pace <preference>`,
`reflect <thought>`, `current`, and `end` manage progress. Pace is a preference, not a
notification schedule. Current progress and reflections survive restarts and enter private
conversation context. Only one current plan is maintained; start another after finishing
or ending it. Saved reflection messages remain in the conversation archive.

### Windows startup and recovery

Run `pastor_ray/install-startup.ps1` to install the **Pastor Ray** Windows login task.
It launches hidden `pythonw -m pastor_ray.supervisor` from this workspace. The supervisor
restarts its bot child after a crash, with 5–120 second backoff, and starts local Ollama if
unavailable. Task Scheduler also retries supervisor failures. If task registration is not
permitted, the installer uses a per-user Startup shortcut instead. Ports 18763 (bot) and
18764 (supervisor) prevent duplicate instances. Logs: `logs/supervisor.log`, `logs/ray.log`.
This starts after Brandon signs into Windows; it cannot run while the PC is off/asleep.
Choir playback is not automatically started on recovery. To stop intentionally, disable
the login task and stop the supervisor before stopping its child. Restart the scheduled
task to resume. No tokens are included in process arguments or task definitions.

Only the configured owner may use `!ray reachout <ID or mention> <exact message>`.
Recipients must belong to the server. There are no autonomous DM reminders.

## Prayer schedule

8 AM, 1 PM and 8 PM America/New_York, including DST, in Inspirational Vibes. Requires the
computer, Ollama and bot to be running. Five-minute reconnect grace; no old-prayer backlog.
SQLite claims each slot before sending. If delivery times out ambiguously, it is not retried,
favoring no duplicates over guaranteed delivery. Inspect `!ray status` and `logs/ray.log`.
Model failure uses a general prayer without claiming current server knowledge.

Context is the last 18 hours (up to 40 human messages) from explicitly listed public channels;
currently Inspirational Vibes and general. Restricted channels are excluded. Bot messages and
commands are excluded. Prompt instructs broad, anonymous themes, not personal details.
`!ray request <text>` explicitly shares a request for seven days. `!ray unrequest` removes it.
This uses a separate table, never private history or summaries.

If Message Content Intent is disabled in the Discord Developer Portal, startup detects it
and connects without the privileged intent. DMs, slash controls and scheduled prayers still
work, but public context is unavailable and public text commands may not be delivered.
Enable the intent under the application's Bot settings, save, and restart Ray to enable context.

## Spoken sermons and public Q&A

Live voice Q&A uses a Node sidecar with pinned `@discordjs/voice` 0.19.2 and its
`@snazzah/davey` DAVE implementation. Node 22.12 or newer is required by that pinned
release (this machine uses 24.14.1). Python keeps the existing Discord gateway and
forwards voice state/server events through private stdio; Node owns sending AND
receiving during the sermon session. The choir keeps its existing Python transport.
No second bot account, inbound network port, or bot token is given to the sidecar.
The child exits when its parent pipe closes. Library source:
https://github.com/discordjs/discord.js/tree/main/packages/voice
Discord does not document audio receiving, so library support may change.

Selected voice: **Andrew**, `en-US-AndrewNeural`, rate `-8%`. Sermon writing and
question answering use local Joe Speedboat. Speech synthesis uses Edge's online
service; generated public sermon and answer text goes to that service. Private DM
history, notes and discipleship plans are never loaded by the sermon engine.

- Hosts (the owner and configured music controllers): `!ray sermon forgiveness`,
  `!ray sermon Romans 12:9-13 3 minutes`, or `/sermon topic: forgiveness`.
- Natural requests: "Ray, preach about forgiveness" or "join Meditation Vibes and
  preach about forgiveness". Default target five minutes, supported range 1–20;
  actual duration depends on the generated text and spoken delivery.
- Morning services: say "Ray, give me a morning sermon", "Give me a 20-minute morning
  service on hope", or use `!ray sermon morning 15 minutes`. Morning requests default
  to 15 minutes. Requests of ten minutes or more also use the extended service structure.
  The service focuses on four consecutive KJV verses, with opening prayer, passage
  context, two explanation sections, practical application, and closing prayer.
  A general morning request uses Lamentations 3:22–25; a named topic or passage directs
  the selection. No new scheduled service is created: every service is requested.
  Long services are generated in sections and speech is synthesized in bounded chunks.
  Ray joins immediately, replacing choir playback, and gives a short spoken welcome. Preparation may take several minutes.
  The start announcement reports the measured audio duration. Length is a target,
  not a guarantee of exact minutes; spoken Q&A follows the prepared service separately.
  Small pitch-preserving tempo adjustments help fit the requested duration without
  cutting off the prayer. Full-service audio is checked against the 10–20 minute range
  before playback; a draft that cannot fit that range is rejected rather than truncated.
- Anyone: `!ray topic <topic>` suggests a public topic; `!ray topics` lists suggestions.
  Hosts choose a topic to start and can use `!ray sermon clear-topics`.
- During preparation or preaching: `!ray ask <question>` queues a public question.
  During Q&A, `/ask` or an explicit Ray mention in the configured chat channels works
  too. Questions are answered sequentially aloud and in voice-channel text chat.
- Hosts can use `!ray talk` to start a voice conversation without a sermon.
- During preaching or Q&A, say **Ray, <question>**, then
  pause for about a second. Whisper transcribes locally and an addressed question joins
  the conversation. During playback, Ray pauses, answers, and resumes about one second before the interruption. Say just "Ray" to receive an invitation and a 25-second window for your question. Incidental chatter without the name at the beginning is ignored outside that window.
  Hosts can use `!ray sermon listen off` and `!ray sermon listen on`.
- Hosts: `!ray sermon pause`, `!ray sermon resume`, `!ray sermon end` (immediate stop),
  or `!ray sermon end choir` (end session and start the music playlist again).
  `!ray stop`, `pause`, and `resume` also control the active sermon session.
- `!ray sermon status` reports preparation, preaching, Q&A, or idle.

Sermon requests, including build/write requests, automatically join voice. The complete sermon text is posted in voice-channel chat as playback begins. No separate join command is required. A preparation failure is reported and the voice session closes.
KJV readings are inserted directly from the offline Bible after reference lookup;
the explanation is model-generated and can still be mistaken. Ray announces playback
only after Discord reports audio playing. Speech failure ends the session or reports
a failed question; it does not claim success. Another bot in voice blocks a new sermon
and causes an active session to yield. Microphone reception is enabled during sermons and ordinary spoken answers, and disabled during initial preparation, answer generation, interruption answers, or a host pause. Local transcription introduces a delay; interruption is not instantaneous. A text-match echo filter is used, not acoustic echo cancellation. No recordings
are saved. At most four simultaneous 30-second speech segments are buffered in RAM;
the pending transcription queue also holds at most four. Audio is discarded after
transcription and queued audio is discarded at session end. Already-running local
transcription may finish after cancellation, but its result is ignored.

The local CPU/int8 `faster-whisper` base model must be cached before use; this machine
already has it. Runtime loading is offline (`local_files_only=True`). A new installation
can download it once with `python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"`.
If unavailable, Ray announces that only typed questions are available. Transcripts are
not added to private memory or runtime logs; recognized questions are shown in public
voice-channel chat for transparency. Only non-bot channel members are subscribed.

The queue holds ten questions with one outstanding question per person and a 15-second
cooldown. Q&A retains the sermon and the last four public exchanges, never private memory.
Topics and session state are in memory; a restart does not replay an interrupted sermon.
Temporary audio is removed when the session ends. After ten minutes without a queued
question, the session disconnects. Choir restart is explicit and starts a new track;
it does not resume at the previous song's position.

Operator verification: `python -m pastor_ray.verify_sermon_live` intentionally posts a
test notice, plays a short sermon, exercises pause/resume, and answers one sample question.
Stop the normal bot and its supervisor first; the same singleton port prevents duplicates.
Restart the **Pastor Ray** scheduled task afterward. This test never runs on normal startup.
Add `--listen-check` to wait up to two minutes for an addressed question from a real
participant and verify receive/decrypt/transcribe/answer. No incoming question is reported
as unverified, not passed. A host can stop the test using the normal sermon end command.

### Sermon voice audition (prototype)

`python -m pip install -r pastor_ray/requirements-voice.txt`, then
`python -m pastor_ray.voice_prototype` generates two MP3 auditions under
`assets/voice-audition`, with matching script and duration metadata. Requires FFmpeg.
The fixed public excerpt reads Ephesians 4:32 directly from the local KJV source,
followed by a plain-language explanation and prayer. Andrew and Brian are stock
synthetic voices, slowed slightly with pauses between sections.
This uses Edge's online speech service through https://github.com/rany2/edge-tts;
it is not offline TTS and sends the sample script to that service. No DM memory is used.
The audition generator only writes local files. Andrew was selected for live sessions.

## Choir

Natural requests work in DMs and both chat channels: "join Meditation Vibes and play the
choir", "play worship music", "pause the music", "resume", "skip this song", and
"stop the choir". These dispatch real controls before model inference, with the same
controller permissions. Negated requests and quoted examples do not trigger playback.

`!ray play/pause/resume/skip/stop`, `!ray playlist`, `!ray credits`.
Slash `/ray` offers the same basic controls and status. Controls are limited to owner and
configured music controllers. Another bot in voice blocks startup; Ray leaves if another
bot joins later. Garth is untouched. Music is not started automatically.

Eight Open Skies Praise recordings are downloaded directly from the creator with CC BY-NC
4.0 permission. Noncommercial use only. music_catalog.json retains URLs, per-song credits,
duration and SHA256. Credits post on each song. Attribution failures stop playback.
Your Love also credits Murray Bunton (CC BY-NC 3.0); hymn arranger/original credits are
preserved. FFmpeg normalizes playback loudness; downloaded originals remain unchanged.
Tracks rotate without immediate repeats; a five-second skip cooldown prevents rapid skips.
Technical decoding checks do not constitute a human listening-quality review.

License: https://openskiespraise.org/using-our-music
Catalog: https://openskiespraise.org/songs

To add licensed originals later, place files under audio/ and append a matching metadata
record to music_catalog.json. The downloader regenerates the starter catalog, so back up
custom catalog entries before rerunning it. No paid content or Suno downloads are assumed.

### Prayer voice visits

Hosts can say "give me a morning prayer", "start a prayer session for strength", or
`!ray prayer <topic>` in public chat. Ray prepares a public prayer, joins Meditation
Vibes, posts the same text as playback starts, then disconnects without Q&A or listening.
Scheduled 8 AM, 1 PM and 8 PM prayers use this same voice visit, with their text in
Inspirational Vibes. An occupied Ray session or another bot blocks the voice visit;
the scheduled prayer still posts in text and reports the voice failure. It is not retried.
Private DM prayer conversations are not automatically broadcast into the server.
Text posting and playback start concurrently; this does not provide word-level captions.

### Reread earlier excerpts

Reply to a public Ray message with `!ray reread` or "Ray, read this aloud", or send
`!ray reread <Discord message link>`. Hosts can replay the exact selected message
from Inspirational Vibes or Meditation Vibes. Ray joins, speaks, and leaves.
For a sermon split across messages, select the specific excerpt to read; it does not
automatically combine neighboring messages. Private and other users messages are excluded.

Natural history lookup: say "Find your sermon from September 25 about forgiveness and reread it aloud." Ray searches the available public history in both configured channels, filters dates, uses the local model to select a matching excerpt, then speaks the original source. Closely consecutive message chunks are grouped. Ambiguous matches ask for more detail. Deleted messages cannot be recovered; this is chat-history retrieval, not a durable sermon archive.

### Active speech provider

Ray now uses Fish Audio voice `16f85c97afdd43619ad861d0315ebbc0` for all live speech,
with the `s2.1-pro-free` model and balanced latency. The API key stays in the ignored
.env file. Public spoken text is sent to Fish Audio; private DM memory remains excluded.
Earlier Andrew/Edge references describe the previous provider and audition prototype.
No silent fallback to a different voice is enabled. Audio is prepared before playback;
this integration does not yet stream speech directly into Discord.

### Pastoral planning and progressive services

Extended services use Joe Speedboat to choose a title, purpose, KJV references and applications when unspecified. Public sections are written by the installed local `qwen3:latest` model and checked independently by `qwen2.5-coder:7b`; private conversations and initial spoken answers continue to use Joe. Public answers receive local Scripture-quotation checks; a failed answer is rewritten once with the teaching model and withheld if it still fails. These model names are configurable with `sermon_model`, `review_model`, and `model`. A generic morning-service request is sufficient. Explicit selections are preserved. Scripture is validated locally and the exact reading is inserted from the local KJV file.

Writing and Fish Audio generation run as separate bounded producers. Reviewed sections are divided at sentence boundaries into audio pieces of up to 1,100 characters, ready for playback individually. The opening, Scripture reading and passage context are separate pieces; the first two verses are explained in separate writing sections to reduce the first teaching delay. The full sermon is not prepared before playback starts. Duration remains an approximate content target, not a premeasured or tempo-adjusted total.

Playback first buffers two audio pieces to cover the early generation delay. Startup
therefore includes planning, review and synthesis of those pieces, and is not instant. Extended services prepare those pieces before joining voice, then join and begin playback. Cancelling during preparation never joins voice.

Sections receive a model review plus direct checks for known failures found in offline acceptance: generated verse-labelled readings, specific suffering-blame language, coercive giving suggestions, incomplete sentences and incomplete closing prayers. Attributed Scripture quotations are checked against the supplied KJV; ordinary quoted titles and explicitly hypothetical examples remain permitted. Unverified Greek, Hebrew and Aramaic word-origin claims are rejected because no verified lexicon is supplied. Chapter openings and neighboring verses ground historical context. Model review is fallible and these checks do not certify all possible factual or pastoral claims. Failed reviews stop the service rather than speaking the rejected draft.

Voice listening remains active across consecutive audio pieces; pause, interruption and session-end transitions still discard stale captures. Gaps can occur if generation is slower than playback. The next-section wait is bounded and visible. See PASTORAL_DESIGN.md for ministry responsibilities and VALIDATION.md for measured results and remaining checks.
