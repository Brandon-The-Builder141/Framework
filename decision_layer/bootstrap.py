"""Seed examples for the decision layer.

Call :func:`seed_all` once during agent startup (or whenever the decision
layer's memory directory is empty) to give it enough signal to route common
tool calls without requiring live training data.

Example:
    >>> from decision_layer import DecisionLayer
    >>> from decision_layer.bootstrap import seed_all
    >>> dl = DecisionLayer()
    >>> seed_all(dl)        # idempotent — use_count increments, no duplicates
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decision_layer.core import DecisionLayer

# ── Seed corpus ───────────────────────────────────────────────────────────────
# Each entry is (message, tool_name).  Kept intentionally sparse — the goal is
# to break the cold-start, not to hard-code every possible phrasing.  The agent
# learns from real usage over time and will outgrow these seeds quickly.

_RECALL_SEEDS: list[tuple[str, str]] = [
    ("what did we talk about last time?", "recall"),
    ("do you remember when I mentioned the project deadline?", "recall"),
    ("look up what I told you about the database setup", "recall"),
    ("what was the decision we made about the API design?", "recall"),
    ("remind me what we discussed yesterday", "recall"),
    ("search your memory for anything about the budget", "recall"),
    ("have I mentioned my address before?", "recall"),
    ("find anything in memory about Travis's preferences", "recall"),
    ("what do you know about my work schedule?", "recall"),
    ("recall what happened in our last session", "recall"),
]

_WEB_SEARCH_SEEDS: list[tuple[str, str]] = [
    ("search the web for recent AI news", "search_web"),
    ("look up the latest headlines about machine learning", "search_web"),
    ("find recent news about Python 3.13", "search_web"),
    ("what are the newest developments in quantum computing?", "search_web"),
    ("google how to fix a segfault in C", "search_web"),
    ("look online for the best practices for SQLite WAL mode", "search_web"),
]

_FILE_SEEDS: list[tuple[str, str]] = [
    ("read the contents of config.py", "read_file"),
    ("show me what is in the settings file", "read_file"),
    ("open data/memory/profiles and show me the files", "read_file"),
    ("write a new Python script to automate backups", "write_file"),
    ("save this content to a markdown file", "write_file"),
    ("list all files in the src directory", "list_dir"),
    ("show me what is in the data folder", "list_dir"),
]

_SCHEDULE_SEEDS: list[tuple[str, str]] = [
    ("what is on my schedule for today?", "get_schedule"),
    ("show me my upcoming reminders", "get_schedule"),
    ("add a reminder for tomorrow at 9am", "add_schedule"),
    ("schedule a meeting with alice on friday", "add_schedule"),
    ("what appointments do I have this week?", "get_schedule"),
]

_CODE_SEEDS: list[tuple[str, str]] = [
    ("run the test suite", "run_command"),
    ("execute the build script", "run_command"),
    ("run pytest and show me the results", "run_command"),
    ("check if the server is running with ps aux", "run_command"),
]

_LIST_BACKENDS_SEEDS: list[tuple[str, str]] = [
    ("pull up your providers", "list_backends"),
    ("list all backends", "list_backends"),
    ("show all configured backends", "list_backends"),
    ("what providers do you have available", "list_backends"),
    ("which AI providers are active", "list_backends"),
    ("show your backend registry", "list_backends"),
    ("display all available models and providers", "list_backends"),
    ("what backends are healthy right now", "list_backends"),
    ("show me which models you can use", "list_backends"),
    ("list providers", "list_backends"),
]

_LIST_MODELS_SEEDS: list[tuple[str, str]] = [
    ("list openai models", "list_models"),
    ("show me models for xai", "list_models"),
    ("what ollama models are configured", "list_models"),
    ("list models for the anthropic backend", "list_models"),
    ("show gemini models", "list_models"),
    ("what models does mistral have configured", "list_models"),
    ("show details for xai/grok-4.3", "list_models"),
    ("what are the openai backends", "list_models"),
]

ALL_SEEDS: list[tuple[str, str]] = (
    _RECALL_SEEDS
    + _WEB_SEARCH_SEEDS
    + _FILE_SEEDS
    + _SCHEDULE_SEEDS
    + _CODE_SEEDS
    + _LIST_BACKENDS_SEEDS
    + _LIST_MODELS_SEEDS
)


def seed_recall_examples(dl: "DecisionLayer") -> int:
    """Seed only recall-routing examples. Returns number of entries recorded.

    Example:
        >>> from decision_layer import DecisionLayer
        >>> dl = DecisionLayer("/tmp/test_bootstrap")
        >>> n = seed_recall_examples(dl)
        >>> n == len(_RECALL_SEEDS)
        True
    """
    for message, tool in _RECALL_SEEDS:
        dl.record_success(message, tool)
    return len(_RECALL_SEEDS)


def seed_list_backends_examples(dl: "DecisionLayer") -> int:
    """Seed routing examples for list_backends and list_models. Returns count recorded.

    Example:
        >>> from decision_layer import DecisionLayer
        >>> dl = DecisionLayer("/tmp/test_bootstrap")
        >>> n = seed_list_backends_examples(dl)
        >>> n == len(_LIST_BACKENDS_SEEDS) + len(_LIST_MODELS_SEEDS)
        True
    """
    for message, tool in _LIST_BACKENDS_SEEDS + _LIST_MODELS_SEEDS:
        dl.record_success(message, tool)
    return len(_LIST_BACKENDS_SEEDS) + len(_LIST_MODELS_SEEDS)


def seed_all(dl: "DecisionLayer") -> int:
    """Seed the decision layer with examples for all common tools.

    Idempotent — calling it again increments ``use_count`` on existing entries
    rather than creating duplicates.  Returns total number of seed messages
    recorded.

    Example:
        >>> from decision_layer import DecisionLayer
        >>> dl = DecisionLayer("/tmp/test_seed_all")
        >>> seed_all(dl) == len(ALL_SEEDS)
        True
    """
    for message, tool in ALL_SEEDS:
        dl.record_success(message, tool)
    return len(ALL_SEEDS)
