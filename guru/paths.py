"""Paths for Guru data, logs, audio, and scripts."""
from pathlib import Path

GURU_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = GURU_ROOT / "scripts"
AUDIO_DIR = GURU_ROOT / "audio"
LOGS_DIR = GURU_ROOT / "guru_logs"
CONFIG_PATH = GURU_ROOT / "guru_config.json"
PROFILE_PATH = GURU_ROOT / "guru_profile.json"
TASKS_PATH = GURU_ROOT / "tasks.json"

for d in (SCRIPTS_DIR, AUDIO_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)
