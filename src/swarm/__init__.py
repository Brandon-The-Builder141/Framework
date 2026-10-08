"""Neuron swarm: hybrid brain-like structure (lightweight hidden + LLM output)."""
from src.swarm.signal import Signal
from src.swarm.graph import run, run_cloud, run_sync

__all__ = ["Signal", "run", "run_cloud", "run_sync"]
