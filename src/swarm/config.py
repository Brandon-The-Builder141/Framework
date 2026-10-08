"""Swarm topology and config."""
from typing import Any

# Default topology: input(3) -> hidden(4) -> output(1)
INPUT_NEURONS = ["N0", "N1", "N2"]
HIDDEN_NEURONS = ["N10", "N11", "N12", "N13"]
OUTPUT_NEURONS = ["N20"]

# Connections (from, to) with weight
SYNAPSES: list[tuple[str, str, float]] = [
    # Input -> Hidden (full connect, uniform init)
    ("N0", "N10", 0.6), ("N0", "N11", 0.5), ("N0", "N12", 0.4), ("N0", "N13", 0.3),
    ("N1", "N10", 0.5), ("N1", "N11", 0.6), ("N1", "N12", 0.5), ("N1", "N13", 0.4),
    ("N2", "N10", 0.4), ("N2", "N11", 0.5), ("N2", "N12", 0.6), ("N2", "N13", 0.5),
    # Hidden -> Output
    ("N10", "N20", 0.7), ("N11", "N20", 0.6), ("N12", "N20", 0.6), ("N13", "N20", 0.7),
]

# Threshold for lightweight neurons (fire if sum >= threshold)
HIDDEN_THRESHOLD = 0.5

# LLM output neuron
OLLAMA_MODEL = "llama3.2:latest"
OLLAMA_BASE_URL = "http://localhost:11434"
