"""
Download TinyLlama base model from Hugging Face.
Run once so it's cached before fine-tuning. ~2–3 GB.

Usage:
  python scripts/prepare_soul_base.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from config.settings import SOUL_BASE_MODEL


def main():
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print("Install first: pip install transformers torch")
        sys.exit(1)
    print(f"Downloading {SOUL_BASE_MODEL} from Hugging Face (~2–3 GB)...")
    tokenizer = AutoTokenizer.from_pretrained(SOUL_BASE_MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(SOUL_BASE_MODEL, trust_remote_code=True)
    print(f"Done. Cached. Ready for train_soul.py.")

if __name__ == "__main__":
    main()
