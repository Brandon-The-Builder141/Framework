"""Reflex layer for unambiguous voice commands.

Free fallback models are unreliable at tool-calling — a weak model will happily
say "I'm in the channel!" without actually calling ``join_voice_session``. For
the core, high-confidence commands (join / skip / pause / resume / stop, and
starting a named meditation) we don't need the LLM at all: match the intent from
the raw text and dispatch the real handler directly.

This runs only AFTER the message is already established as directed at Garth
(his listen channel, an @mention, or his name), so casual conversation is not at
risk. Anything that doesn't clearly match falls through to the LLM as before.

Returns ``(command, args)`` suitable for ``handle_guru_action`` — or ``None``.
"""
from __future__ import annotations

import re

# --- meditation requests (need a request verb so "I had a deep sleep" is ignored) ---
_MED_VERB = re.compile(
    r"\b(play|start|run|do|begin|put on|give me|i want|i'?d like|can (you|we)|"
    r"let'?s (do|try|start)|guide me|meditat)\b",
    re.I,
)
_SCRIPTS: list[tuple[str, re.Pattern]] = [
    ("deep_sleep", re.compile(r"\bdeep sleep\b", re.I)),
    ("rain_sleep", re.compile(r"\b(rain|sleep in the rain)\b", re.I)),
    ("sleep_drift", re.compile(r"\b(drift (in|off)?to sleep|drift into sleep|sleep drift)\b", re.I)),
    ("bedtime_winddown", re.compile(r"\b(bedtime|wind[- ]?down)\b", re.I)),
    ("box_breathing", re.compile(r"\bbox breathing\b", re.I)),
    ("body_scan", re.compile(r"\bbody scan\b", re.I)),
    ("loving_kindness", re.compile(r"\bloving[- ]?kindness\b", re.I)),
    ("quick_calm", re.compile(r"\bquick calm\b", re.I)),
]

# --- voice controls ---
_SKIP = re.compile(
    r"\b(skip|next (track|song|one)|change (the )?(track|song)|different (song|track)|another (song|track))\b",
    re.I,
)
_STOP = re.compile(
    r"\b(stop (the )?(music|session|meditation|track)|leave (the )?(voice|vc|channel|call)|"
    r"disconnect|get out of (voice|vc))\b",
    re.I,
)
_PAUSE = re.compile(r"\bpause\b|\bhold (on )?(the )?(music|it)\b", re.I)
_RESUME = re.compile(
    r"\b(resume|unpause|keep playing|play (it|the music) again|continue (the )?music|"
    r"start (the )?music again)\b",
    re.I,
)
_JOIN = re.compile(
    r"\b(join( voice| us| the (voice|vc|channel))?|hop in|jump in|get in here|"
    r"come (in|join|chill|hang)|come on in)\b",
    re.I,
)
_JOIN_MUSIC = re.compile(
    r"\b(play|put on|throw on|start|give me)\b.{0,20}\b(music|chill|ambient|tunes|"
    r"a song|some (music|tunes)|something (calm|chill|relaxing))\b",
    re.I,
)
_CHILL = re.compile(r"\b(let'?s chill|chill music|chill out|some chill|chill vibes)\b", re.I)


def detect_voice_intent(text: str) -> tuple[str, list[str]] | None:
    t = (text or "").strip()
    if not t:
        return None

    # 1. Named meditation (explicit request) — check before generic join.
    if _MED_VERB.search(t) or re.search(r"\bmeditat", t, re.I):
        for name, pat in _SCRIPTS:
            if pat.search(t):
                return ("meditate", [name])

    # 2. Track / playback controls.
    if _SKIP.search(t):
        return ("skip", [])
    if _STOP.search(t):
        return ("stop", [])
    if _PAUSE.search(t):
        return ("pause", [])
    if _RESUME.search(t):
        return ("play", [])

    # 3. Join + ambient music (the default).
    if _JOIN.search(t) or _JOIN_MUSIC.search(t) or _CHILL.search(t):
        return ("start", [])

    return None
