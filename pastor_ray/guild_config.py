"""Per-guild configuration for multi-server hosting.

One bot instance serves many Discord servers. Global settings (Ollama URL,
models, owner) live in config.json; everything server-shaped lives here,
persisted in the ``guilds`` table by :class:`pastor_ray.storage.Store`.
"""
import json
import time
from dataclasses import asdict, dataclass, field


@dataclass
class GuildConfig:
    guild_id: int
    text_channel_id: int | None = None
    voice_channel_id: int | None = None
    timezone: str = "America/New_York"
    prayer_hours: list = field(default_factory=lambda: [8, 13, 20])
    prayers_enabled: bool = True
    public_context_channel_ids: list = field(default_factory=list)
    music_controller_ids: list = field(default_factory=list)
    startup_announced: bool = False
    created_at: float = field(default_factory=time.time)

    def sched(self):
        """Dict view for schedule.due_slot / next_prayer (their API is unchanged)."""
        return {"timezone": self.timezone, "prayer_hours": self.prayer_hours}

    def to_json(self):
        return json.dumps(asdict(self))

    @classmethod
    def from_row(cls, guild_id, raw):
        """Rebuild from a guilds-table row. Unknown keys are ignored so old
        rows keep loading after the dataclass grows."""
        data = json.loads(raw) if raw else {}
        data["guild_id"] = int(guild_id)
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})
