"""Offline KJV lookup, with source text for local-model explanations."""
import io
import json
import re
import zipfile
from functools import lru_cache

import httpx
from pastor_ray.settings import ROOT


@lru_cache(maxsize=1)
def books():
    path = ROOT / "data" / "kjv.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def passages(text):
    data = books()
    if not data:
        return []
    aliases = {book.lower(): book for book in data}
    aliases["psalm"] = "Psalms"
    pattern = r"(?<!\w)(" + "|".join(re.escape(n) for n in sorted(aliases, key=len, reverse=True)) + r")\s+(\d{1,3})(?::(\d{1,3})(?:[-–](\d{1,3}))?)?(?!\d)"
    out = []
    for m in re.finditer(pattern, text, re.I):
        book, chapter = aliases[m[1].lower()], int(m[2])
        chapters = data[book]
        if not 1 <= chapter <= len(chapters):
            continue
        verses = chapters[chapter-1]["verses"]
        start = int(m[3] or 1)
        end = int(m[4] or m[3] or len(verses))
        if not (1 <= start <= end <= len(verses)):
            continue
        for verse in verses[start-1:min(end,start+19)]:
            out.append(f"{book} {chapter}:{verse['verse']} (KJV): {verse['text']}")
        if len(out)>=20:
            break
    return out[:20]


def context(text):
    direct = passages(text)
    if direct:
        return direct
    topics = {
        "grace": "Ephesians 2:8-10", "forgiv": "Ephesians 4:32",
        "anxi": "Philippians 4:6-7", "worr": "Matthew 6:25-27",
        "grief": "Psalms 34:18", "wisdom": "James 1:5",
        "salvation": "Romans 10:9-13", "love": "1 Corinthians 13:4-7",
    }
    for topic, reference in topics.items():
        if topic in text.lower():
            return passages(reference)
    return []


def main():
    response = httpx.get("https://codeload.github.com/aruljohn/Bible-kjv/zip/refs/heads/master", timeout=60)
    response.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    result = {}
    for name in archive.namelist():
        if name.endswith(".json") and not name.endswith("/Books.json"):
            data = json.loads(archive.read(name))
            result[data["book"]] = data["chapters"]
    if len(result) != 66:
        raise ValueError("Expected all 66 books")
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "kjv.json").write_text(json.dumps(result), encoding="utf-8")
    (ROOT / "KJV-LICENSE.txt").write_bytes(archive.read("Bible-kjv-master/LICENSE"))
    print("Installed 66 KJV books. Source: aruljohn/Bible-kjv; MIT license retained.")


if __name__ == "__main__":
    main()
