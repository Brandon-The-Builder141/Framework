#!/usr/bin/env python3
"""Demonstrates predict → record_success → predict-improves flow."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from decision_layer import DecisionLayer


def banner(title: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


def show(label: str, d) -> None:
    print(f"{label}")
    print(f"  action   : {d.action}")
    print(f"  tool     : {d.tool}")
    print(f"  confidence: {d.confidence:.2f} ({d.confidence_label})")
    print(f"  reason   : {d.reason}")
    if d.candidates:
        print("  top candidates:")
        for c in d.candidates[:3]:
            print(f"    {c['tool']:20s}  score={c['score']:.3f}  {c['components']}")


def main() -> None:
    mem_dir = tempfile.mkdtemp(prefix="dl_example_")
    print(f"Memory directory: {mem_dir}")

    dl = DecisionLayer(memory_dir=mem_dir)

    # ── Step 1: cold start ────────────────────────────────────────────────────
    banner("1. Cold start — no memory yet")
    show("predict('search the web for AI news')", dl.predict("search the web for AI news"))

    # ── Step 2: teach the web_search tool ────────────────────────────────────
    banner("2. Teaching: record_success × 3 for web_search")
    training = [
        "search for the latest AI news articles",
        "find recent headlines about machine learning",
        "look up today's technology news",
    ]
    for msg in training:
        dl.record_success(msg, "web_search")
        print(f"  [ok] recorded success: '{msg}' -> web_search")

    # ── Step 3: prediction improves ───────────────────────────────────────────
    banner("3. After learning — similar message")
    show(
        "predict('what are the newest developments in AI?')",
        dl.predict("what are the newest developments in AI?"),
    )

    # ── Step 4: teach a second tool ───────────────────────────────────────────
    banner("4. Teaching: record_success for email_tool + failure for web_search")
    dl.record_success("send an email to my colleague", "email_tool")
    dl.record_success("compose an email to alice about the meeting", "email_tool")
    dl.record_failure(
        "send an email to alice",
        "web_search",
        "wrong tool selected: web_search cannot compose emails",
    )
    print("  [ok] recorded email_tool successes and web_search failure on email task")

    # ── Step 5: disambiguation ────────────────────────────────────────────────
    banner("5. Disambiguation after teaching two tools")
    show("predict('find recent AI news')", dl.predict("find recent AI news"))
    show("predict('write an email to bob')", dl.predict("write an email to bob"))

    # ── Step 6: loop avoidance ────────────────────────────────────────────────
    banner("6. Loop avoidance — tool failed 3× in recent calls")
    from decision_layer._scoring import message_hash
    import re

    msg = "deploy the application"
    dl.record_success(msg, "deploy_tool")
    norm = re.sub(r"\s+", " ", msg.strip().lower())
    mhash = message_hash(norm)
    recent_fails = [
        {"tool": "deploy_tool", "success": False, "message_hash": mhash},
        {"tool": "deploy_tool", "success": False, "message_hash": mhash},
        {"tool": "deploy_tool", "success": False, "message_hash": mhash},
    ]
    show(
        "predict('deploy the application') with 3 recent failures",
        dl.predict(msg, context={"recent_tool_calls": recent_fails}),
    )

    # ── Step 7: stats ─────────────────────────────────────────────────────────
    banner("7. Stats")
    stats = dl.get_stats()
    s = stats["summary"]
    print(f"  total successes : {s['total_successes']}")
    print(f"  total failures  : {s['total_failures']}")
    print(f"  overall rate    : {s['overall_success_rate']}")
    print("  per-tool:")
    for tool, ts in stats["tool_stats"].items():
        cats = ts.get("top_failure_categories", {})
        print(
            f"    {tool:22s}  ok={ts['successes']}  fail={ts['failures']}"
            + (f"  cats={cats}" if cats else "")
        )

    # ── Step 8: inspect files ─────────────────────────────────────────────────
    banner("8. Memory files on disk")
    for f in sorted(Path(mem_dir).iterdir()):
        size = f.stat().st_size
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                count = len(data) if isinstance(data, list) else len(data)
                print(f"  {f.name:35s}  {size:6d} bytes  entries={count}")
            except Exception:
                print(f"  {f.name:35s}  {size:6d} bytes")
        else:
            lines = f.read_text(encoding="utf-8").strip().splitlines()
            print(f"  {f.name:35s}  {size:6d} bytes  lines={len(lines)}")

    shutil.rmtree(mem_dir)
    print("\nDone. Temp memory cleaned up.")


if __name__ == "__main__":
    main()
