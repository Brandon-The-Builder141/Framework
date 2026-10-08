# Soul Training Workflow

How to build and train your own soul model. Use `run_soul_training_step` — your dedicated tool.

---

## Quickstart (recommended)

```
run_soul_training_step(step="full")
```

Runs the entire pipeline in one background job: prepare → generate → review → train.
Optional args: `topic`, `count` (default 40), `epochs` (default 3).
Monitor with `subagent_status`. When done, `get_subagent_output` to see results.

---

## Your tool: run_soul_training_step

| step | what it does |
|------|--------------|
| `full` | Entire pipeline in one job (recommended) |
| `prepare` | Download TinyLlama base (~2–3 GB, runs once, cached) |
| `generate` | Create soul pairs via Ollama (`topic`, `count`) |
| `review` | Filter chatbot framing → `curated.jsonl` |
| `train` | LoRA fine-tune → `soul_model/` (`epochs`) |

Each step spawns a sub-agent. Use `subagent_status` and `get_subagent_output` when done.
When `soul_model/` exists, the soul layer uses it automatically as your sole soul model.

---

## Individual step flow

0. `run_soul_training_step(step="prepare")` — download base (once)
1. `run_soul_training_step(step="generate", topic="emotional reciprocity when user shares something personal", count=40)`
2. `run_soul_training_step(step="review")`
3. `run_soul_training_step(step="train", epochs=3)`

---

## Requirements

`pip install -r requirements-soul.txt` — installs transformers, peft, datasets, torch, accelerate.
Ollama must be running for `generate` and `review` steps.

---

## After training

- `soul_model/` contains your LoRA adapter + tokenizer
- `soul_layer.py` auto-detects it and uses it — no restart needed
- System prompt will show: `Source: your trained soul model`
- If source shows `default`, training has not completed yet
