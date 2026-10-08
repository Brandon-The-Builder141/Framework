# Neuron Swarm Architecture

A brain-like structure where **neurons = orchestrator agents** and **synapses = worker sub-agents**. Signals propagate through the swarm; emergent behavior arises from coordination.

---

## Core Concepts

| Concept | Role | Responsibility |
|--------|------|-----------------|
| **Neuron** | Orchestrator agent | Receives signals, decides whether to "fire," routes outputs to downstream neurons |
| **Synapse** | Sub-agent | Carries a weighted signal from neuron A → B; can amplify, dampen, or gate |
| **Signal** | Payload | Structured message: `{type, content, strength, metadata}` |

---

## Minimal Architecture (v0)

### Graph Structure

```
Input Layer          Hidden Layer           Output Layer
[N0, N1, N2]  --->  [N10, N11, N12]  --->  [N20]
     |                    |                     
     v                    v                     
  Synapses S0→10, S1→10, S2→11, etc.
```

- **Neurons** have IDs and a "layer" (input=0, hidden=1..L-1, output=L).
- **Synapses** connect `(from_neuron, to_neuron)` with a configurable weight.
- One synapse sub-agent per connection (or pool per layer to limit cost).

### Neuron Agent Behavior

1. **Receive** – Collect signals from incoming synapses (from previous layer).
2. **Aggregate** – Sum weighted inputs (or use a simple threshold).
3. **Decide** – Fire or not: `fire = aggregate > threshold` (or use LLM for richer "decision").
4. **Broadcast** – If firing, send signal to all outgoing synapses.

### Synapse Sub-Agent Behavior

1. **Receive** – Get signal from upstream neuron.
2. **Weight** – Apply weight: `output = signal * weight`.
3. **Forward** – Pass to downstream neuron.

---

## Data Flow (One "Thought")

```
1. User/System injects signals into Input neurons (N0, N1, N2).
2. Input neurons aggregate → fire → send to synapses.
3. Synapses weight and forward to Hidden neurons.
4. Hidden neurons aggregate → fire → send to synapses.
5. Repeat until Output layer.
6. Output neurons produce final "response" signal.
```

---

## Implementation Sketch

### Option A: Lightweight (No LLM per neuron)

- Neurons = pure functions: `fire(inputs, weights, threshold) -> 0|1`
- Synapses = `forward(signal, weight) -> weighted_signal`
- Run in-process, fast. Good for testing topology and learning rules.
- **Outcome**: Neural net with swappable propagation logic.

### Option B: LLM Neurons (Heavy)

- Each neuron = agent with system prompt: "You receive these signals. Fire or not. If firing, produce output."
- Synapses = sub-agents that "carry" the message (could add summarization, filtering).
- **Outcome**: Emergent, unpredictable behavior; high cost.
- **Scale**: Start with ~10 neurons, 20 synapses.

### Option C: Hybrid (implemented)

- Hidden neurons = lightweight (threshold + aggregate).
- Output neuron(s) = LLM via Ollama (`llama3.2:latest`): "Given these activations, produce a response."
- Synapses = weighted pass-through.
- **Run**: `python run_swarm.py "input 1" "input 2" "input 3"`

---

## File Layout (If Built)

```
src/swarm/
├── __init__.py
├── neuron.py      # Neuron agent (orchestrator)
├── synapse.py     # Synapse sub-agent (worker)
├── graph.py       # Build and run the graph
├── signal.py      # Signal payload type
└── config.py      # Topology, weights, thresholds
```

---

## Learning / Plasticity (Future)

- **Hebbian**: If neuron A fires and B fires soon after, increase weight A→B.
- **Reward**: If output leads to positive feedback, reinforce active path.
- **Pruning**: Decay unused synapses; spawn new ones for novel pathways.

---

## What Could Emerge

- **Attention**: Some neurons consistently fire for certain input types → "specialists."
- **Chains**: Repeated patterns (A→B→C) → "concepts" or "habits."
- **Oscillation**: Feedback loops → rhythm, periodic behavior.
- **Bottlenecks**: Few neurons gate many paths → "decision points."

---

## Implementation

- `src/swarm/` – signal, synapse, neuron, graph, config
- `run_swarm.py` – CLI to run the swarm
- Model: Ollama `llama3.2:latest` (configurable in `config.py`)

## Next Steps

1. Wire swarm output into the main agent as a "reflection" or "suggestion" source.
2. Experiment with topology (more neurons, different weights).
3. Add learning rules (Hebbian, reward-based).
