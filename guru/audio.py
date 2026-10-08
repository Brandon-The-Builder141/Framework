"""YouTube + local ambient audio for Discord voice."""

from __future__ import annotations



import random

import re

import shutil

from pathlib import Path

from typing import Any



from guru.config import load_config

from guru.logger import log_action

from guru.paths import GURU_ROOT



_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/)([\w-]{11})")





def ffmpeg_executable() -> str:

    """Path to ffmpeg binary (required for Discord voice)."""

    return shutil.which("ffmpeg") or "ffmpeg"





def ambient_track_key(source: str | Path, *, cfg: dict[str, Any] | None = None) -> str:

    """Stable id for rotation (filename or youtube video id)."""

    if isinstance(source, Path):

        return f"local:{source.name}"

    p = Path(str(source))

    if p.is_file():

        return f"local:{p.name}"

    s = str(source)

    m = _YT_ID_RE.search(s)

    if m:

        return f"yt:{m.group(1)}"

    cfg = cfg or load_config()

    for url in cfg.get("youtube_urls") or []:

        mid = _YT_ID_RE.search(str(url))

        if mid and mid.group(1) in s:

            return f"yt:{mid.group(1)}"

    return f"stream:{hash(s) & 0xFFFFFFFF:08x}"





def resolve_youtube_audio_url(url_or_id: str) -> str | None:

    try:

        import yt_dlp

    except ImportError:

        log_action("yt_dlp_missing", "pip install yt-dlp", level="error")

        return None



    target = (url_or_id or "").strip()

    if not target:

        return None

    if not target.startswith("http"):

        target = f"https://www.youtube.com/watch?v={target}"



    opts = {

        "format": "bestaudio/best",

        "quiet": True,

        "no_warnings": True,

    }

    try:

        with yt_dlp.YoutubeDL(opts) as ydl:

            info = ydl.extract_info(target, download=False)

            if not info:

                return None

            if info.get("url"):

                return info["url"]

            entries = info.get("entries") or []

            if entries:

                first = entries[0]

                if isinstance(first, dict) and first.get("url"):

                    return first["url"]

                if first:

                    inner = ydl.extract_info(

                        first.get("webpage_url") or first.get("url"), download=False

                    )

                    return inner.get("url") if inner else None

    except Exception as e:

        log_action("youtube_error", str(e)[:200], level="error")

    return None





def resolve_youtube_playlist_random(

    playlist_id: str,

    *,

    exclude: frozenset[str] | None = None,

) -> tuple[str, str] | None:

    """Pick a random track from a YouTube playlist. Returns (stream_url, track_key)."""

    try:

        import yt_dlp

    except ImportError:

        return None

    pid = (playlist_id or "").strip()

    if not pid.startswith("http"):

        pid = f"https://www.youtube.com/playlist?list={pid}"

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}

    try:

        with yt_dlp.YoutubeDL(opts) as ydl:

            info = ydl.extract_info(pid, download=False)

            entries = [e for e in (info or {}).get("entries") or [] if e]

            if not entries:

                return None

            exclude = exclude or frozenset()

            candidates = []

            for e in entries:

                vid = e.get("id") or ""

                if not vid and e.get("url"):

                    m = _YT_ID_RE.search(str(e.get("url")))

                    vid = m.group(1) if m else ""

                if not vid:

                    continue

                key = f"yt:{vid}"

                if key not in exclude:

                    candidates.append((vid, key))

            if not candidates:

                candidates = [

                    (e.get("id") or "", f"yt:{e.get('id')}")

                    for e in entries

                    if e.get("id")

                ]

            vid, key = random.choice(candidates)

            watch = f"https://www.youtube.com/watch?v={vid}"

            stream = resolve_youtube_audio_url(watch)

            if stream:

                return stream, key

    except Exception as e:

        log_action("youtube_playlist_error", str(e)[:200], level="error")

    return None





def list_local_tracks(cfg: dict[str, Any]) -> list[Path]:

    """MP3/WAV in guru/audio/ plus optional local_music_files names in config."""

    fallback_dir = GURU_ROOT / (cfg.get("fallback_audio_dir") or "audio")

    seen: set[str] = set()

    out: list[Path] = []



    def add(path: Path) -> None:

        key = str(path.resolve())

        if path.is_file() and key not in seen:

            seen.add(key)

            out.append(path)



    for name in cfg.get("local_music_files") or []:

        p = Path(name)

        if not p.is_absolute():

            p = fallback_dir / name

        add(p)

    for pattern in ("*.mp3", "*.wav", "*.ogg"):

        for p in sorted(fallback_dir.glob(pattern)):

            add(p)

    return out





def _pick_from_candidates(

    candidates: list[tuple[str | Path, str]],

    exclude: frozenset[str],

) -> tuple[str | Path, str] | None:

    if not candidates:

        return None

    fresh = [(src, key) for src, key in candidates if key not in exclude]

    pool = fresh if fresh else candidates

    return random.choice(pool)





def pick_ambient_source(
    cfg: dict[str, Any] | None = None,
    *,
    exclude: frozenset[str] | None = None,
    local_only: bool = False,
) -> tuple[str | Path, str] | None:
    """Pick next ambient track. Returns (playable_source, stable_track_key)."""
    cfg = cfg or load_config()
    exclude = exclude or frozenset()
    locals_ = list_local_tracks(cfg)
    local_candidates = [(p, ambient_track_key(p)) for p in locals_]
    local_pick = _pick_from_candidates(local_candidates, exclude)
    if local_pick:
        src, key = local_pick
        log_action("ambient_pick", f"local:{Path(src).name}", level="info")
        return src, key

    if local_only or cfg.get("ambient_local_only"):
        return None

    candidates: list[tuple[str | Path, str]] = []
    for path in locals_:
        key = ambient_track_key(path)
        candidates.append((path, key))

    for url in cfg.get("youtube_urls") or []:

        url = str(url).strip()

        m = _YT_ID_RE.search(url)

        key = f"yt:{m.group(1)}" if m else f"yt:{url}"

        if key not in exclude or len(candidates) < 2:

            candidates.append((url, key))  # resolve stream at play time



    picked = _pick_from_candidates(candidates, exclude)

    if not picked:

        log_action("no_ambient_source", "empty pool", level="warn")

        return None



    src, key = picked

    if isinstance(src, Path) or Path(str(src)).is_file():

        log_action("ambient_pick", f"local:{Path(src).name}", level="info")

        return src, key



    stream = resolve_youtube_audio_url(str(src))

    if stream:

        log_action("ambient_pick", key, level="info")

        return stream, key



    # Try other YouTube URLs if first pick failed to resolve

    urls = [str(u).strip() for u in (cfg.get("youtube_urls") or [])]

    random.shuffle(urls)

    for url in urls:

        m = _YT_ID_RE.search(url)

        key = f"yt:{m.group(1)}" if m else f"yt:{url}"

        if key in exclude:

            continue

        stream = resolve_youtube_audio_url(url)

        if stream:

            log_action("ambient_pick", key, level="info")

            return stream, key



    playlist = (cfg.get("youtube_playlist_id") or "").strip()

    if playlist:

        pl = resolve_youtube_playlist_random(playlist, exclude=exclude)

        if pl:

            stream, key = pl

            log_action("ambient_pick", f"playlist:{key}", level="info")

            return stream, key



    # Last resort: any local file

    locals_ = list_local_tracks(cfg)

    if locals_:

        path = random.choice(locals_)

        key = ambient_track_key(path)

        log_action("ambient_pick", f"local_fallback:{path.name}", level="info")

        return path, key



    log_action("no_ambient_source", str(GURU_ROOT / (cfg.get("fallback_audio_dir") or "audio")), level="warn")

    return None





def ffmpeg_pcm_source(path_or_url: str | Path, *, volume: float = 0.15) -> Any:

    import discord



    vol = max(0.01, min(1.0, float(volume)))

    exe = ffmpeg_executable()

    target = str(path_or_url)
    is_remote = target.startswith("http://") or target.startswith("https://")
    kwargs: dict[str, Any] = {
        "executable": exe,
        "options": f"-filter:a volume={vol}",
    }
    if is_remote:
        kwargs["before_options"] = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        )
    # -nostdin prevents ffmpeg from exiting early on local files
    if not is_remote:
        kwargs["before_options"] = "-nostdin"
    return discord.FFmpegPCMAudio(target, **kwargs)

