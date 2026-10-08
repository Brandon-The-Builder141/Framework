"""
Knowledge base - how-to guides for all tools. Use when unsure how to do something.
"""
from pathlib import Path

from config.settings import KNOWLEDGE_DIR


def _load_all_docs() -> dict[str, str]:
    """Load all .md files from knowledge dir. Key = stem (filename without .md)."""
    docs = {}
    if not KNOWLEDGE_DIR.exists():
        return docs
    for p in KNOWLEDGE_DIR.glob("*.md"):
        try:
            docs[p.stem.lower()] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return docs


def search_knowledge(query: str, max_results: int = 3) -> str:
    """
    Search the knowledge base for how-tos. Use when you don't know how to do something.
    Returns relevant docs. Then use the described tools.
    """
    docs = _load_all_docs()
    if not docs:
        return "Knowledge base is empty."

    query_lower = query.lower().strip()
    words = set(w for w in query_lower.split() if len(w) > 2)

    scored: list[tuple[float, str, str]] = []
    for name, content in docs.items():
        content_lower = content.lower()
        score = 0
        for w in words:
            if w in name:
                score += 3
            if w in content_lower:
                score += content_lower.count(w)
        if score > 0:
            scored.append((score, name, content))

    scored.sort(key=lambda x: -x[0])
    top = scored[:max_results]
    if not top:
        return (
            f"No matching docs for '{query}'. Available topics: "
            + ", ".join(sorted(docs.keys()))
        )

    parts = []
    for _, name, content in top:
        parts.append(f"--- {name}.md ---\n{content}")
    return "\n\n".join(parts)


def read_knowledge(topic: str) -> str:
    """
    Read a specific knowledge base topic by name. Use after list_knowledge_topics.
    topic: e.g. 'files', 'processes', 'build', 'dag'
    """
    docs = _load_all_docs()
    key = topic.lower().strip()
    if key in docs:
        return docs[key]
    # Fuzzy match
    for name in docs:
        if key in name or name in key:
            return docs[name]
    return f"Topic '{topic}' not found. Available: " + ", ".join(sorted(docs.keys()))


def list_knowledge_topics() -> str:
    """List available knowledge base topics. Use to see what guides exist."""
    docs = _load_all_docs()
    if not docs:
        return "Knowledge base is empty."
    return "Available topics: " + ", ".join(sorted(docs.keys()))
