"""Download the eight creator-authorized CC BY-NC recordings, no ripping."""
import hashlib
import html
import json
import re
import subprocess
from urllib.parse import urljoin, urlparse

import httpx

from pastor_ray.settings import ROOT

SONGS = [
    ("Faithful One", "faithful-one-studio-recording/faithful-one"),
    ("Know You More", "fall-jam-2017/know-you-more"),
    ("Be Still", "fall-jam-2017/be-still"),
    ("Nothing But The Blood (I Will Praise Him)", "fall-jam-2017/nothing-but-the-blood"),
    ("Your Love", "matts-front-porch/your-love"),
    ("He Is Good", "spring-jam-2017/he-is-good"),
    ("I Will Rejoice", "spring-jam-2017/i-will-rejoice"),
    ("Come Thou Fount", "spring-jam-2017/come-thou-fount"),
]


def main():
    audio = ROOT / "audio"
    audio.mkdir(exist_ok=True)
    records = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for title, slug in SONGS:
            page = "https://openskiespraise.org/songs/" + slug
            response = client.get(page)
            response.raise_for_status()
            if "creativecommons.org/licenses/by-nc/4.0" not in response.text:
                raise RuntimeError(f"License not found for {title}")
            links = re.findall(r'href=[\"\x27]([^\"\x27]+)[\"\x27]', response.text)
            urls = [urljoin(page, html.unescape(x)) for x in links if ".mp3" in x.lower() and "instrumental" not in x.lower()]
            if not urls:
                raise RuntimeError(f"No official MP3 for {title}")
            url = urls[0]
            if urlparse(url).hostname != "openskiespraise.org":
                raise RuntimeError("Unexpected download host")
            dest = audio / (slug.split("/")[-1] + ".mp3")
            if not dest.exists():
                download = client.get(url)
                download.raise_for_status()
                if len(download.content) < 10000:
                    raise RuntimeError("Audio download too short")
                temp = dest.with_suffix(".part")
                temp.write_bytes(download.content)
                temp.replace(dest)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(dest)], capture_output=True, text=True, check=True)
            info = json.loads(probe.stdout)
            record = {"title": title, "artist": "Open Skies Praise", "source": page,
                "download_url": url, "file": "audio/" + dest.name,
                "license": "CC BY-NC 4.0", "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
                "attribution": f'{title} © 2017 Open Skies Praise. CC BY-NC 4.0.',
                "duration_seconds": round(float(info["format"]["duration"]), 2),
                "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(), "auditioned": False}
            if title == "Your Love":
                record["attribution"] += " Original work: Your Love by Murray Bunton, CC BY-NC 3.0."
            if title.startswith("Nothing But"):
                record["attribution"] += " Arrangement: Brad Gibson, CC BY-NC 4.0. Original words/music: Robert Lowry and Margaret J. Harris, public domain."
            if title == "Come Thou Fount":
                record["attribution"] += " Original words: Robert Robinson; music: John Wyeth, public domain."
            records.append(record)
            print(f"Verified {title}: {record['duration_seconds']} seconds")
    (ROOT / "music_catalog.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Saved {len(records)} recordings and their credits.")


if __name__ == "__main__":
    main()
