"""
Full soul training pipeline - runs all 4 steps in sequence.
Spawned by run_soul_training_step(step='full').

Steps:
  1. prepare  - download TinyLlama base from HuggingFace (~2-3 GB, cached)
  2. generate - create soul training pairs via Ollama
  3. review   - filter chatbot framing, write curated.jsonl
  4. train    - LoRA fine-tune -> data/soul_training/soul_model/

Progress and errors are printed to stdout (captured by subagent manager).
On success: prints TRAINING COMPLETE and the model path.
On failure: prints TRAINING FAILED with the step and error.

Usage:
  python scripts/run_full_soul_training.py [--topic TOPIC] [--count N] [--epochs N]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from config.settings import SOUL_TRAINING_DIR, SOUL_BASE_MODEL


def _banner(msg: str):
    print(f"\n{'=' * 60}", flush=True)
    print(f"  {msg}", flush=True)
    print(f"{'=' * 60}\n", flush=True)


def step_prepare() -> bool:
    """Download and cache TinyLlama base model."""
    _banner("STEP 1/4 - Downloading base model")
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print("ERROR: transformers not installed. Run: pip install -r requirements-soul.txt", flush=True)
        return False
    try:
        print(f"Fetching tokenizer: {SOUL_BASE_MODEL}", flush=True)
        AutoTokenizer.from_pretrained(SOUL_BASE_MODEL, trust_remote_code=True)
        print(f"Fetching model weights: {SOUL_BASE_MODEL}", flush=True)
        AutoModelForCausalLM.from_pretrained(SOUL_BASE_MODEL, trust_remote_code=True)
        print("Base model ready (cached).", flush=True)
        return True
    except Exception as e:
        print(f"ERROR during prepare: {e}", flush=True)
        return False


def step_generate(topic: str, count: int) -> bool:
    """Generate soul training pairs via Ollama."""
    _banner(f"STEP 2/4 - Generating {count} soul pairs (topic: {topic})")
    try:
        from scripts.generate_training_data import run
        path = run(topic=topic, count=count, soul=True)
        pairs = sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
        print(f"Generated {pairs} pairs -> {path}", flush=True)
        if pairs == 0:
            print("ERROR: No pairs generated. Is Ollama running?", flush=True)
            return False
        return True
    except Exception as e:
        print(f"ERROR during generate: {e}", flush=True)
        return False


def step_review() -> bool:
    """Filter chatbot framing, produce curated.jsonl."""
    _banner("STEP 3/4 - Reviewing and curating pairs")
    soul_latest = SOUL_TRAINING_DIR / "soul_latest.jsonl"
    if not soul_latest.exists():
        print(f"ERROR: {soul_latest} not found. Generate step must run first.", flush=True)
        return False
    try:
        from scripts.review_training_pairs import review
        kept, rejected, out_path = review(soul_latest, use_ollama=True)
        print(f"Review complete: {kept} kept, {rejected} rejected -> {out_path}", flush=True)
        if kept == 0:
            print("ERROR: No pairs survived review. Try generating more pairs.", flush=True)
            return False
        return True
    except Exception as e:
        print(f"ERROR during review: {e}", flush=True)
        return False


def step_train(epochs: int) -> bool:
    """LoRA fine-tune TinyLlama on curated pairs."""
    _banner("STEP 4/4 - Fine-tuning soul model (LoRA)")
    curated = SOUL_TRAINING_DIR / "curated.jsonl"
    if not curated.exists():
        print(f"ERROR: {curated} not found. Review step must run first.", flush=True)
        return False
    output_dir = SOUL_TRAINING_DIR / "soul_model"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        from scripts.train_soul import train
        result = train(curated, SOUL_BASE_MODEL, output_dir, epochs=epochs)
        adapter_cfg = result / "adapter_config.json"
        if not adapter_cfg.exists():
            print(f"ERROR: Training appeared to complete but adapter_config.json not found at {result}", flush=True)
            return False
        print(f"Soul model saved: {result}", flush=True)
        return True
    except Exception as e:
        print(f"ERROR during train: {e}", flush=True)
        return False


def main():
    args = sys.argv[1:]
    topic = "emotional tone, relational warmth, and authentic presence"
    count = 40
    epochs = 3
    i = 0
    while i < len(args):
        if args[i] == "--topic" and i + 1 < len(args):
            topic = args[i + 1]
            i += 2
        elif args[i] == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
            i += 2
        elif args[i] == "--epochs" and i + 1 < len(args):
            epochs = int(args[i + 1])
            i += 2
        else:
            i += 1

    t0 = time.time()
    _banner("FULL SOUL TRAINING PIPELINE STARTING")
    print(f"Topic:  {topic}", flush=True)
    print(f"Pairs:  {count}", flush=True)
    print(f"Epochs: {epochs}", flush=True)

    steps = [
        ("prepare", lambda: step_prepare()),
        ("generate", lambda: step_generate(topic, count)),
        ("review", lambda: step_review()),
        ("train", lambda: step_train(epochs)),
    ]

    for name, fn in steps:
        ok = fn()
        if not ok:
            elapsed = time.time() - t0
            print(f"\nTRAINING FAILED at step: {name} (elapsed {elapsed:.0f}s)", flush=True)
            sys.exit(1)

    elapsed = time.time() - t0
    soul_model_dir = SOUL_TRAINING_DIR / "soul_model"
    _banner("TRAINING COMPLETE")
    print(f"Soul model: {soul_model_dir}", flush=True)
    print(f"Total time: {elapsed:.0f}s", flush=True)
    print("The soul layer will now use your trained model automatically.", flush=True)


if __name__ == "__main__":
    main()
