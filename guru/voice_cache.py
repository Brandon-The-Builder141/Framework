"""Pre-rendered guided-meditation voice cache.

Guided-meditation lines are fixed text, so we render each one once with Fish
Speech (voice 6, 0.86 tempo) and cache a single mp3 per line, keyed by a hash of
the line text. Garth plays the cached clip instead of synthesizing live; any line
that isn't cached yet falls back to Edge TTS, so nothing ever breaks mid-session.

Both the renderer (Python 3.11 / Fish venv) and Garth (Python 3.14) import the
same ``cache_key`` so the filenames line up. Stdlib only — no heavy deps.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

VOICE_CACHE_DIR = Path(__file__).resolve().parent / "voice_cache"


def cache_key(text: str) -> str:
    """Stable hash of a line of script text (whitespace-normalized)."""
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()


def cached_voice_path(text: str) -> Path:
    """Absolute path to the cached clip for ``text`` (may not exist yet)."""
    return VOICE_CACHE_DIR / f"{cache_key(text)}.mp3"
