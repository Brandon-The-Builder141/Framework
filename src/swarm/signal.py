"""Signal payload: what propagates through the swarm."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Signal:
    type: str = "activation"
    content: str = ""
    strength: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def weighted(self, w: float) -> "Signal":
        return Signal(
            type=self.type,
            content=self.content,
            strength=self.strength * w,
            metadata=dict(self.metadata),
        )
