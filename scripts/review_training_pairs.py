"""
Review generated training pairs: filter out chatbot/AI/assistant framing.
Uses local Ollama. Output: curated JSONL.

Usage:
  python scripts/review_training_pairs.py <input.jsonl> [--output <curated.jsonl>]
  python scripts/review_training_pairs.py data/soul_training/soul_latest.jsonl
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from config.settings import SOUL_TRAINING_DIR

try:
    import requests
except ImportError:
    requests = None

from src.swarm.config import OLLAMA_BASE_URL, OLLAMA_MODEL

BAD_PHRASES = [
    "i am an ai", "as an ai", "i'm an ai",
    "as a chatbot", "i'm a chatbot", "i am a chatbot",
    "as an assistant", "i'm an assistant", "i am an assistant",
    "as a language model", "i'm a language model", "large language model",
    "as an artificial intelligence", "i'm an artificial intelligence",
]


def _reject_by_rule(text: str) -> bool:
    """Reject if text contains chatbot/AI framing."""
    t = text.lower()
    return any(b in t for b in BAD_PHRASES)


def _ollama_check(instruction: str, response: str, model: str = OLLAMA_MODEL) -> bool:
    """Ask Ollama: does this sound like chatbot framing? Returns True if REJECT."""
    if not requests:
        return _reject_by_rule(response)
    prompt = f"""Does this response suggest the speaker is an AI, chatbot, or assistant? Answer ONLY "YES" or "NO".

Response: {response[:500]}

Answer:"""
    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=30,
        )
        r.raise_for_status()
        ans = (r.json().get("response") or "").strip().upper()
        return "YES" in ans[:10]
    except Exception:
        return _reject_by_rule(response)


def review(input_path: Path, output_path: Path | None = None, use_ollama: bool = True) -> tuple[int, int, Path]:
    """Review pairs. Returns (kept, rejected, output_path)."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    lines = [ln.strip() for ln in input_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    pairs = []
    for ln in lines:
        try:
            pairs.append(json.loads(ln))
        except json.JSONDecodeError:
            pass

    kept = []
    rejected = 0
    for p in pairs:
        inst = (p.get("instruction") or "").strip()
        resp = (p.get("response") or "").strip()
        if not inst or not resp:
            rejected += 1
            continue
        if _reject_by_rule(resp):
            rejected += 1
            continue
        if use_ollama and _ollama_check(inst, resp):
            rejected += 1
            continue
        kept.append({"instruction": inst, "response": resp})

    out = output_path or SOUL_TRAINING_DIR / "curated.jsonl"
    SOUL_TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for p in kept:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    return len(kept), rejected, out


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python scripts/review_training_pairs.py <input.jsonl> [--output <out.jsonl>] [--no-ollama]")
        sys.exit(1)
    inp = Path(args[0])
    out = None
    use_ollama = True
    i = 1
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            out = Path(args[i + 1])
            i += 2
        elif args[i] == "--no-ollama":
            use_ollama = False
            i += 1
        else:
            i += 1
    kept, rejected, out_path = review(inp, out, use_ollama=use_ollama)
    print(f"Review complete: {kept} kept, {rejected} rejected -> {out_path}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
