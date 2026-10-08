"""Shared, cached LLM client factory.

``AsyncOpenAI`` (and the Anthropic adapter) wrap an httpx connection pool and
real OS file descriptors. Several background paths — the memory consolidator,
background thoughts, backend health probes, image generation — used to build a
brand-new client on every single call and never close it. Those pools piled up
for the whole lifetime of the process: a slow file-descriptor / socket leak.

Handing back one cached client per ``(provider, base_url, api_key, timeout)``
fixes the leak and reuses the warm connection pool, so repeated background calls
no longer pay TLS + pool setup every time.

Clients are safe to share across tasks and coroutines, so a process-wide cache
is the right granularity. Nothing here ever expires entries — the number of
distinct backends is tiny and bounded.
"""
from __future__ import annotations

import threading
from typing import Any

from openai import AsyncOpenAI

_lock = threading.Lock()
_clients: dict[tuple[str, str, str, float], Any] = {}


def get_client(
    provider: str,
    api_key: str,
    base_url: str,
    *,
    timeout: float | None = None,
) -> Any:
    """Return a cached client for the given backend.

    ``provider`` selects the implementation (``"anthropic"`` -> adapter, anything
    else -> OpenAI-compatible). ``timeout`` is part of the cache key so callers
    that need a longer timeout (e.g. image generation) get their own client
    rather than mutating a shared one.
    """
    key = (provider or "openai", base_url or "", api_key or "", float(timeout or 0.0))
    with _lock:
        client = _clients.get(key)
        if client is None:
            if provider == "anthropic":
                from src.provider_adapters import AsyncAnthropicAdapter

                client = AsyncAnthropicAdapter(api_key=api_key, base_url=base_url)
            elif timeout is not None:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            else:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            _clients[key] = client
        return client


async def close_all() -> None:
    """Close every cached client. For clean shutdown and tests."""
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for c in clients:
        try:
            close = getattr(c, "close", None) or getattr(c, "aclose", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        except Exception:
            pass
