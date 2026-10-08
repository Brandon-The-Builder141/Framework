from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Decision:
    """Routing decision produced by DecisionLayer.predict().

    Example:
        >>> d = Decision(action="use_tool", tool="web_search", confidence=0.82,
        ...              confidence_label="high", reason="best match", candidates=[])
        >>> d.tool
        'web_search'
    """

    action: str             # "use_tool" | "no_tool"
    tool: str | None        # tool name if action == "use_tool", else None
    confidence: float       # 0.0 – 1.0
    confidence_label: str   # "low" | "medium" | "high"
    reason: str
    candidates: list[dict] = field(default_factory=list)
