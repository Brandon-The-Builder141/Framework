"""
Speech-to-text for long recordings.
Uses faster-whisper (local, no API key) - handles long audio well.
Model is loaded lazily on first transcribe.
"""
import tempfile
from pathlib import Path

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("base", device="cpu", compute_type="int8")
    return _model


def transcribe_audio(audio_bytes: bytes, language: str = "en") -> str:
    """
    Transcribe audio bytes to text.
    Expects raw audio or common formats (wav, mp3, etc).
    """
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        path = f.name

    try:
        model = _get_model()
        segments, _ = model.transcribe(path, language=language)
        return " ".join(s.text.strip() for s in segments if s.text).strip()
    finally:
        Path(path).unlink(missing_ok=True)


def transcribe_pcm(
    pcm: bytes,
    language: str = "en",
    sample_rate: int = 48000,
    channels: int = 2,
    sample_width: int = 2,
) -> str:
    """Transcribe raw signed-integer PCM (e.g. from a live Discord voice
    channel via discord-ext-voice-recv, which delivers 48kHz/16-bit/stereo).
    Wraps it in a real WAV header first so ffmpeg/av decode it correctly."""
    import wave

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
        with wave.open(f, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(sample_width)
            w.setframerate(sample_rate)
            w.writeframes(pcm)

    try:
        model = _get_model()
        segments, _ = model.transcribe(path, language=language)
        return " ".join(s.text.strip() for s in segments if s.text).strip()
    finally:
        Path(path).unlink(missing_ok=True)
