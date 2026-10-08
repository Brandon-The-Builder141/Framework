"""One-shot: copy OpenRouter settings from Framework .env into quote-ai host config."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUOTE_AI = Path(r"C:\Users\Brandon\OneDrive\Desktop\quote-ai")
HOST_CONFIG = QUOTE_AI / ".quote-flow-host-config.json"


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    env = _load_env(ROOT / ".env")
    key = env.get("OPENROUTER_API_KEY", "")
    if not key:
        print("OPENROUTER_API_KEY not found in Framework .env", file=sys.stderr)
        return 1
    config = {
        "openRouterKey": key,
        "openRouterModel": env.get("OPENROUTER_MODEL", "openrouter/free"),
        "companyName": "Apex Estimate",
    }
    HOST_CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {HOST_CONFIG} (openRouterConfigured=True)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
