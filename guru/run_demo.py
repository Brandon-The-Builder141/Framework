"""Simulate Guru command flow without Discord (parse, profile, scripts)."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guru.commands import _parse_args, is_guru_command
from guru.profile import load_profile, pick_script_for_profile, record_session_rating
from guru.scripts_loader import list_scripts, load_script


def main() -> None:
    print("=== Guru demo (offline) ===\n")
    assert is_guru_command("!guru start box_breathing")
    cmd, args = _parse_args("!guru start box_breathing")
    assert cmd == "start" and args == ["box_breathing"]
    print("Command parser OK")

    scripts = list_scripts()
    print("Scripts:", scripts)
    script = load_script("box_breathing")
    assert script and script.get("segments")
    print(f"Loaded: {script['title']} ({len(script['segments'])} segments)")

    uid = "demo_user"
    pick = pick_script_for_profile(scripts, load_profile(uid))
    print("Profile pick:", pick)
    record_session_rating(uid, script_name="box_breathing", rating=5, feedback="demo")
    print("Profile rating saved")

    print("\nDemo complete. For live voice test: !guru setup then !guru start in Discord.")


if __name__ == "__main__":
    main()
