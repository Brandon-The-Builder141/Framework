"""Standalone TTS for Guru (Edge) — no Solen agent dependency."""
import io

import edge_tts


async def synthesize(text: str, *, voice: str = "en-US-AriaNeural") -> bytes:
    communicate = edge_tts.Communicate((text or "").strip(), voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()
