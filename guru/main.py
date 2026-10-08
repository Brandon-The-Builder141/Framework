"""Run the Guru Discord bot (separate from Solen)."""
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from guru.bot import main

if __name__ == "__main__":
    main()
