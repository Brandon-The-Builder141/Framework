from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger("decision_layer")

# Module-level lazy cache — read-only after load, safe under the GIL.
_model_cache: dict[str, Any] = {}


def _load_model() -> Any | None:
    if "checked" in _model_cache:
        return _model_cache.get("model")
    _model_cache["checked"] = True
    try:
        from sentence_transformers import SentenceTransformer

        m = SentenceTransformer("all-MiniLM-L6-v2")
        _model_cache["model"] = m
        logger.debug("sentence-transformers loaded (all-MiniLM-L6-v2, dim=384)")
    except (ImportError, Exception):
        logger.warning(
            "sentence-transformers not installed or failed to load — "
            "using hashed trigram fallback (dim=256). "
            "Install with: pip install sentence-transformers"
        )
        _model_cache["model"] = None
    return _model_cache.get("model")


def reset_model_cache() -> None:
    """Clear the module-level model cache.  Used in tests to force the fallback path."""
    _model_cache.clear()


def embed(text: str) -> list[float]:
    """Return a unit-length embedding vector for *text*.

    Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim) when available;
    falls back to a hashed character-trigram vector (256-dim) otherwise.

    Example:
        >>> v = embed("search for news")
        >>> abs(sum(x * x for x in v) - 1.0) < 1e-4
        True
    """
    model = _load_model()
    if model is not None:
        return model.encode(text, normalize_embeddings=True).tolist()
    return _ngram_embed(text)


def _ngram_embed(text: str, dim: int = 256) -> list[float]:
    vec = [0.0] * dim
    for i in range(max(len(text) - 2, 0)):
        h = hash(text[i : i + 3]) % dim
        vec[h] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors, clamped to [-1, 1].

    Example:
        >>> cosine_similarity([1.0, 0.0], [1.0, 0.0])
        1.0
        >>> cosine_similarity([1.0, 0.0], [0.0, 1.0])
        0.0
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
