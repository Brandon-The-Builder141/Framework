# Fallback ambient audio

Garth picks from **YouTube URLs** and **MP3/WAV in this folder** (weighted by count — more files here = more often local).
Listed in `local_music_files` in `guru_config.json`, plus any other tracks in this folder.

**Preload offline backup:**
```powershell
python guru\download_ambient.py
python guru\download_batch_ambient.py
```

Drop your own loops here too (rain, pads, etc.). Requires **ffmpeg** on PATH.
