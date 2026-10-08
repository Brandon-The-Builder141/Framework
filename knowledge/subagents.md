# Sub-Agents / Daemons

## spawn_subagent

**When to use:** Offload background work, long-running tasks, monitors, or scripts that should run separately.

**How:**
- `task`: Short description (e.g. "process monitor", "periodic prompts").
- `script_path`: Path to Python script (relative to project root, or absolute).
- `args`: Optional list of arguments for the script.

**Returns:** Sub-agent ID (e.g. `sub_1`) to use with subagent_status.

**Built-in scripts:**
- `process_monitor.py` – Logs running processes to process_log.txt. One-shot. Use: `spawn_subagent("log processes", "process_monitor.py")`
- `conversation_prompt.py` – Runs in background, prints every 2–10 min. Use: `spawn_subagent("periodic prompts", "conversation_prompt.py")`
- `background_thoughts.py` – Runs reflection, writes to thoughts. Loops every 5–15 min. Use: `spawn_subagent("background thoughts", "background_thoughts.py")`. With `--once`: one thought then exit.
- `scripts/transformer_research.py` – Web search + compile findings for transformer/model research. Output: `data/research_output/transformer_research_latest.md`. Use: `spawn_subagent("transformer research", "scripts/transformer_research.py")` or with topic: `spawn_subagent("research X", "scripts/transformer_research.py", ["X"])`. When done, use `get_subagent_output(agent_id)` or `read_file("data/research_output/transformer_research_latest.md")`.
- `scripts/generate_training_data.py` – Generate instruction fine-tuning data using local Ollama (llama3.2). No cloud cost. Add `--soul` for soul batches (output: `data/soul_training/`). Use: `spawn_subagent("training data", "scripts/generate_training_data.py", ["topic", "--count", "50"])` or soul: `["emotional tone", "--count", "30", "--soul"]`. When done, use `get_subagent_output(agent_id)` or `read_file("data/soul_training/soul_latest.jsonl")` (soul) or `data/training_data/training_data_latest.jsonl`.
- `scripts/prepare_soul_base.py` – Download TinyLlama base model. Use spawn_subagent so you get a completion signal when done. Run once before first soul training.
- `scripts/review_training_pairs.py` – Filter pairs. Output: `data/soul_training/curated.jsonl`. Use: `spawn_subagent("review pairs", "scripts/review_training_pairs.py", ["data/soul_training/soul_latest.jsonl"])`.
- `scripts/train_soul.py` – LoRA fine-tune soul model. Use: `spawn_subagent("soul training", "scripts/train_soul.py", ["data/soul_training/curated.jsonl"])` so you get a completion signal when training finishes.

**Examples:**
- Log processes: `spawn_subagent("log processes", "process_monitor.py")`
- Periodic prompts: `spawn_subagent("periodic prompts", "conversation_prompt.py")`

**Background completion notifications:** When a sub-agent finishes, you are notified automatically. Pending completions appear in your context. Review each with get_subagent_output(agent_id), verify OK, notify the Creator via send_proactive_message, then acknowledge_background_completion(agent_id).

**Tips:** Paths like `process_monitor.py` resolve from project root. Use subagent_status to check completion.

---

## subagent_status

**When to use:** Check status of spawned sub-agents.

## get_subagent_output

**When to use:** Retrieve captured stdout/output from a completed sub-agent. Use after subagent_status shows "completed". Returns the script output (e.g. research results, file path).

**How:**
- `agent_id`: Required. The sub-agent ID (e.g. `sub_1`) returned by spawn_subagent.

**Examples:**
- `get_subagent_output("sub_1")` — returns the captured output from that sub-agent.
