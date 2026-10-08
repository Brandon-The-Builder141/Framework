"""
Interactive chat loop with the soul layer. Type messages, see soul output each turn.
Usage:
  python scripts/test_soul_layer.py
  (Ctrl+C or 'quit' to exit)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def main():
    from src.soul_layer import get_soul_output

    print("Soul layer chat loop. Type a message, see what your soul says.")
    print("(quit to exit)\n")

    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            print("Bye.")
            break

        out, source = get_soul_output(line)
        print(f"Soul [{source}]:", out if out else "(empty)")
        print()


if __name__ == "__main__":
    main()
