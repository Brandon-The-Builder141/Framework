# decision_layer

A standalone Python module that decides **whether a tool should be called, and if so, which one**, given an incoming user message and optional context. It learns from successes and failures over time and persists all state in human-readable JSON.

---

## What it does

1. Embeds an incoming message with `sentence-transformers` (or a hashed n-gram fallback).
2. Retrieves the nearest neighbours from its success and failure memories.
3. Scores every candidate tool with a weighted formula (see Scoring).
4. Returns a `Decision` — tool name to call or `no_tool` — with a confidence score and short reason.
5. After the framework executes the tool, you call `record_success` or `record_failure` to update the memory so future predictions improve.

**v1 scope:** tool-name routing only. Parameter prediction is v2.

---

## Quick start

```python
from decision_layer import DecisionLayer

dl = DecisionLayer()           # defaults to data/decision_layer/

# First call — cold start
d = dl.predict("search for the latest AI news")
print(d.action, d.tool)        # no_tool  None

# Teach it
dl.record_success("search for the latest AI news", "web_search")

# Now similar messages route correctly
d = dl.predict("find recent headlines about machine learning")
print(d.action, d.tool, d.confidence_label)   # use_tool  web_search  high
```

---

## Public API

### `DecisionLayer(memory_dir="data/decision_layer/")`

Create an instance. All JSON files are stored under `memory_dir`.  
Multiple instances with different dirs are fully independent.

---

### `predict(message, context=None) → Decision`

| Arg | Type | Description |
|-----|------|-------------|
| `message` | `str` | Raw user message |
| `context` | `dict \| None` | Optional context blob (see below) |

Recognised context keys:
- `available_tools: list[str]` — if provided (non-empty), only these tools may be returned.
- `recent_tool_calls: list[dict]` — recent calls with `{"tool", "success", "message_hash"}` for loop avoidance.
- `current_project`, `channel`, `tier` — logged but not used in scoring.

---

### `Decision` dataclass

```python
@dataclass
class Decision:
    action: str            # "use_tool" | "no_tool"
    tool: str | None       # tool name, or None
    confidence: float      # 0.0 – 1.0
    confidence_label: str  # "low" | "medium" | "high"
    reason: str            # short human-readable explanation
    candidates: list[dict] # top-3 scored candidates for debugging
```

---

### `record_success(message, tool, context=None)`

Call this after a tool call succeeded. Stores a success example that boosts this tool's score on similar future messages.

Duplicate `(normalized_message, tool)` pairs increment `use_count` instead of adding a new row.

---

### `record_failure(message, tool, error, context=None)`

Call this after a tool call failed (wrong tool, bad param, exception, timeout, …). Stores a failure example that penalises this tool on similar future messages.

The `error` string is auto-categorised:

| Category | Matched by |
|----------|------------|
| `wrong_tool` | "wrong tool", "not a valid tool" |
| `wrong_directory` | "directory", "no such file", "not found" |
| `wrong_param` | "param", "argument", "missing field" |
| `timeout` | "timeout", "timed out" |
| `exception` | "exception", "traceback", "error" |
| `other` | everything else |

---

### `record_no_tool_success(message, context=None)`

Call when the system correctly responded without calling any tool.

---

### `get_stats() → dict`

Returns per-tool counters and an overall summary:

```python
{
  "tool_stats": {
    "web_search": {"successes": 42, "failures": 3, "last_used": "...", ...}
  },
  "summary": {
    "total_successes": 42,
    "total_failures": 3,
    "overall_success_rate": 0.93,
    "tools_known": ["web_search", ...]
  }
}
```

---

### `clear_failures()`

Wipe failure memory and reset failure counts. Useful after bad training data.

---

## Scoring formula

For each candidate tool **t**:

```
score(t) = 0.40 × semantic_similarity
         + 0.25 × success_rate
         + 0.10 × recency
         - 0.25 × failure_penalty
         - loop_penalty
```

| Component | Description |
|-----------|-------------|
| `semantic_similarity` | Mean cosine similarity of query to top-10 success embeddings for *t* |
| `success_rate` | `successes / (successes + failures)` for *t* (defaults to 0.5 if unseen) |
| `recency` | Linear decay over 7 days since *t* was last used successfully |
| `failure_penalty` | Mean cosine similarity of query to top-10 failure embeddings for *t* |
| `loop_penalty` | 0.5 per recent failed call with the same message hash (window = 3) |

**Decision thresholds:**

| Score | action | confidence_label |
|-------|--------|-----------------|
| ≥ 0.65 | `use_tool` | `high` |
| 0.40 – 0.65 | `use_tool` | `medium` |
| < 0.40 | `no_tool` | `low` |

All weights and thresholds are top-of-file constants in `_scoring.py` — change them there to tune.

---

## File layout

```
data/decision_layer/
  success_memory.json      # learned success examples with embeddings
  failure_memory.json      # learned failure examples with embeddings
  no_tool_memory.json      # successful no-tool responses
  tool_stats.json          # rolled-up per-tool counters
  prediction_log.jsonl     # append-only log of every prediction + outcome
```

All files are human-readable, pretty-printed JSON. Safe to delete — the module regenerates empty versions on next run.

### Inspecting memory

```bash
# See what tools have been learned
python -c "import json; d=json.load(open('data/decision_layer/tool_stats.json')); print(list(d.keys()))"

# See failure reasons for a tool
python -c "
import json
for e in json.load(open('data/decision_layer/failure_memory.json')):
    if e['tool'] == 'web_search':
        print(e['normalized'], '|', e['error_category'])
"
```

---

## Embedding

- **Preferred:** `sentence-transformers` `all-MiniLM-L6-v2` (384-dim cosine similarity).
- **Fallback:** Hashed character-trigram vector (256-dim, L2-normalised). Loaded if `sentence-transformers` is not installed; a one-time warning is logged.

```bash
pip install sentence-transformers   # optional but recommended
```

---

## Running the tests

```bash
pytest tests/test_decision_layer.py -v
```

---

## Running the example

```bash
python example_usage.py
```
