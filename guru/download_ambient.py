"""Download one short ambient track into guru/audio/ for offline fallback."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guru.paths import AUDIO_DIR  # noqa: E402

# ~5 min meditation track — small file, good offline backup
DEFAULT_URL = "https://www.youtube.com/watch?v=inpok4MKVLM"


def main() -> None:
    try:
        import yt_dlp
    except ImportError:
        print("Install yt-dlp: pip install yt-dlp")
        raise SystemExit(1)

    url = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL).strip()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDIO_DIR / "ambient_fallback.%(ext)s"
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "quiet": False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    mp3s = list(AUDIO_DIR.glob("ambient_fallback.mp3")) + list(AUDIO_DIR.glob("*.mp3"))
    if mp3s:
        print(f"Saved: {mp3s[0]}")
    else:
        print("Download finished — check guru/audio/")


if __name__ == "__main__":
    main()
