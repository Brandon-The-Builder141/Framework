#!/usr/bin/env python3
"""Weekly memory health: dedupe profile facts, archive trivial episodic rows, reindex embeddings.

Schedule (Windows Task Scheduler example):
  Weekly Sunday 3:00 AM — python scripts/memory_health.py

Cron (Linux):
  0 3 * * 0 cd /path/to/Framework && python scripts/memory_health.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.memory_dedup import run_memory_health


def main() -> int:
    parser = argparse.ArgumentParser(description="Andrew memory health pass")
    parser.add_argument("--user-id", default="default", help="Profile user id")
    args = parser.parse_args()
    stats = run_memory_health(user_id=args.user_id)
    print("Memory health complete:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
