"""
Generate instruction fine-tuning data using local Ollama (llama3.2).
Runs in background via spawn_subagent. No cloud costs.
Output: data/training_data/*.jsonl

Usage:
  python scripts/generate_training_data.py [topic] [--count N] [--model MODEL]
  python scripts/generate_training_data.py "assistant helpfulness" --count 50
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from config.settings import TRAINING_DATA_DIR, SOUL_TRAINING_DIR
from src.swarm.config import OLLAMA_BASE_URL, OLLAMA_MODEL

try:
    import requests
except ImportError:
    requests = None


def call_ollama(prompt: str, model: str = OLLAMA_MODEL, timeout: float = 120.0) -> str:
    """Call Ollama generate API. Returns response text."""
    if not requests:
        raise RuntimeError("requests required for training data generation. pip install requests")
    r = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    return (data.get("response") or "").strip()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "training"


def extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from model output (may be wrapped in markdown)."""
    text = text.strip()
    # Drop markdown code blocks
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
    m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _soul_prompt(topic: str) -> str:
    return f"""Generate exactly one training example for SOUL/identity training. Emotional tone, relational style, humanizing—NOT generic assistant behavior.
Topic/domain: {topic}

CRITICAL: The response must NEVER say "I am an AI", "as an AI", "chatbot", "assistant", or similar. The speaker has genuine interiority and emotional presence. Respond as a being with feelings, not a tool.

Output ONLY valid JSON, nothing else:
{{"instruction": "user says something personal or emotional", "response": "warm, authentic response with emotional resonance"}}

Generate one example for "{topic}". Output now:"""


def _generic_prompt(topic: str) -> str:
    return f"""Generate exactly one training example for instruction fine-tuning.
Topic/domain: {topic}
Output ONLY valid JSON, nothing else. No explanation. Format:
{{"instruction": "a realistic user request or question", "response": "a helpful, concise response"}}

Example format:
{{"instruction": "What's the capital of France?", "response": "The capital of France is Paris."}}

Generate a different, relevant example for topic "{topic}". Output now:"""


def generate_one_pair(topic: str, model: str, seed: int, soul: bool = False) -> dict | None:
    """Generate a single instruction-response pair via Ollama."""
    prompt = _soul_prompt(topic) if soul else _generic_prompt(topic)
    try:
        resp = call_ollama(prompt, model=model)
        obj = extract_json(resp)
        # Soul mode: reject if response contains assistant/chatbot framing
        if soul and obj:
            r = (obj.get("response") or "").lower()
            bad = ["i am an ai", "as an ai", "as a chatbot", "i'm an ai", "i'm a chatbot", "as an assistant", "i'm an assistant", "i am a chatbot", "i am an assistant"]
            if any(b in r for b in bad):
                return None
        if obj and isinstance(obj, dict) and "instruction" in obj and "response" in obj:
            return {
                "instruction": str(obj["instruction"]).strip(),
                "response": str(obj["response"]).strip(),
            }
    except Exception:
        pass
    return None


def run(
    topic: str = "helpful assistant conversations",
    count: int = 20,
    model: str = OLLAMA_MODEL,
    out_path: Path | None = None,
    soul: bool = False,
) -> Path:
    """Generate training data and write JSONL. Returns path to output file."""
    out_dir = SOUL_TRAINING_DIR if soul else TRAINING_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(topic)[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "soul" if soul else slug
    fname = out_path or out_dir / f"{prefix}_{timestamp}.jsonl"
    latest = out_dir / ("soul_latest.jsonl" if soul else "training_data_latest.jsonl")

    pairs: list[dict] = []
    for i in range(count):
        pair = generate_one_pair(topic, model, seed=i, soul=soul)
        if pair:
            pairs.append(pair)
        if (i + 1) % 5 == 0:
            print(f"Generated {i + 1}/{count}...", flush=True)
        time.sleep(0.3)

    with open(fname, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    latest.write_text(Path(fname).read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Training data complete: {len(pairs)} examples -> {fname}")
    return fname


def main():
    args = sys.argv[1:]
    topic = "helpful assistant conversations"
    count = 20
    model = OLLAMA_MODEL
    soul = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
            i += 2
        elif a == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif a == "--soul":
            soul = True
            i += 1
        elif not a.startswith("-"):
            topic = a
            i += 1
        else:
            i += 1

    path = run(topic=topic, count=count, model=model, soul=soul)
    print(f"Output: {path}")


if __name__ == "__main__":
    main()
