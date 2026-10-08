"""Synapse: weighted pass-through from neuron A → B."""
from src.swarm.signal import Signal


def forward(signal: Signal, weight: float) -> Signal:
    """Apply weight and pass through."""
    return signal.weighted(weight)
