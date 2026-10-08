"""Download multiple royalty-free ambient tracks into guru/audio/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guru.paths import AUDIO_DIR  # noqa: E402

# (YouTube URL, output basename without extension) — CC / no-copyright meditation ambient
TRACKS: list[tuple[str, str]] = [
    ("https://www.youtube.com/watch?v=H6_jZ48Ntxo", "zen-instrumental-ambient"),
    ("https://www.youtube.com/watch?v=gUgyfUIhGQc", "dreamcatcher-calm-ambient"),
    ("https://www.youtube.com/watch?v=ri72WZu-d5Y", "lost-ambient-pads"),
    ("https://www.youtube.com/watch?v=h_SJmiVLM_g", "fragments-aerhead-ambient"),
    ("https://www.youtube.com/watch?v=JOPMnCGThuo", "positive-mood-ambient"),
    ("https://www.youtube.com/watch?v=qB7r_MgINU0", "five-minute-relaxing-calm"),
    ("https://www.youtube.com/watch?v=updllnGlDNM", "relax-five-minute-calm"),
    ("https://www.youtube.com/watch?v=iHXKiXsJBYk", "five-minute-royalty-calm"),
    ("https://www.youtube.com/watch?v=EGxezmuDk4g", "peaceful-background-calm"),
    ("https://www.youtube.com/watch?v=2B9l28YqZB8", "free-ambient-meditation"),
]


def download_one(ydl, url: str, basename: str) -> Path | None:
    out = AUDIO_DIR / f"{basename}.%(ext)s"
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }
    import yt_dlp

    with yt_dlp.YoutubeDL(opts) as dl:
        dl.download([url])
    mp3 = AUDIO_DIR / f"{basename}.mp3"
    return mp3 if mp3.is_file() else None


def main() -> None:
    try:
        import yt_dlp
    except ImportError:
        print("Install yt-dlp: pip install yt-dlp")
        raise SystemExit(1)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    ok: list[str] = []
    failed: list[str] = []
    for url, name in TRACKS:
        print(f"Downloading {name} ...", flush=True)
        try:
            import yt_dlp

            opts = {
                "format": "bestaudio/best",
                "outtmpl": str(AUDIO_DIR / f"{name}.%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                "quiet": False,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            mp3 = AUDIO_DIR / f"{name}.mp3"
            if mp3.is_file():
                ok.append(mp3.name)
                print(f"  OK: {mp3.name}")
            else:
                failed.append(name)
                print(f"  FAIL: no mp3 for {name}")
        except Exception as e:
            failed.append(name)
            print(f"  ERROR {name}: {e}")

    print(f"\nDone: {len(ok)} saved, {len(failed)} failed")
    if ok:
        print("Files:", ", ".join(ok))


if __name__ == "__main__":
    main()
