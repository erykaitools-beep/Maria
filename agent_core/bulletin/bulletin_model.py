"""
Cognitive Bulletin Board - data model.

Shared registry of Maria's cognitive needs. Each entry represents
an operational need (not just a topic), visible to planner, critic,
learning pipeline, and operator.

Follows project conventions: frozen dataclasses, Enum types, JSON serialization.
"""

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class EntryType(Enum):
    """What kind of cognitive need this entry represents."""
    NEED_MATERIAL = "need_material"       # Topic important, no input material
    NEED_TEST = "need_test"               # Knowledge exists, needs exam/validation
    NEED_REVIEW = "need_review"           # Quality problem (from critic/validation)
    READY_TO_LEARN = "ready_to_learn"     # Material and conditions ready for pipeline
    WAITING_HUMAN = "waiting_human"       # Needs operator decision or approval


class EntryStatus(Enum):
    """Lifecycle status of a bulletin entry."""
    OPEN = "open"                 # Newly posted, not yet acted on
    IN_PROGRESS = "in_progress"   # Being worked on (material fetching, etc.)
    BLOCKED = "blocked"           # Cannot proceed (rate-limited, missing dep)
    RESOLVED = "resolved"         # Need satisfied, entry closed


# Terminal statuses
TERMINAL_STATUSES = {EntryStatus.RESOLVED}

# Max entries to keep in memory (resolved are pruned first)
MAX_ENTRIES = 200

# Auto-resolve timeout for stale entries (7 days)
STALE_TIMEOUT_SEC = 7 * 24 * 3600


@dataclass
class BulletinEntry:
    """Single cognitive need on the bulletin board."""
    entry_id: str
    goal_id: Optional[str]        # Link to GoalStore goal (if any)
    entry_type: EntryType
    priority: float               # 0.0 - 1.0
    status: EntryStatus
    topic: str                    # Normalized topic string
    reason_code: str              # Why this need exists (e.g. "no_material", "low_confidence")
    summary: str                  # Human-readable description
    requested_by: str             # Module that created this entry
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_type"] = self.entry_type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BulletinEntry":
        return cls(
            entry_id=d["entry_id"],
            goal_id=d.get("goal_id"),
            entry_type=EntryType(d["entry_type"]),
            priority=d.get("priority", 0.5),
            status=EntryStatus(d.get("status", "open")),
            topic=d["topic"],
            reason_code=d.get("reason_code", ""),
            summary=d.get("summary", ""),
            requested_by=d.get("requested_by", "unknown"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            metadata=d.get("metadata", {}),
        )


def create_entry(
    entry_type: EntryType,
    topic: str,
    reason_code: str,
    summary: str,
    requested_by: str,
    goal_id: Optional[str] = None,
    priority: float = 0.5,
    metadata: Optional[Dict[str, Any]] = None,
) -> BulletinEntry:
    """Factory: create a new bulletin entry with generated ID."""
    return BulletinEntry(
        entry_id=f"cbb-{uuid.uuid4().hex[:12]}",
        goal_id=goal_id,
        entry_type=entry_type,
        priority=priority,
        status=EntryStatus.OPEN,
        topic=topic,
        reason_code=reason_code,
        summary=summary,
        requested_by=requested_by,
        created_at=time.time(),
        updated_at=time.time(),
        metadata=metadata or {},
    )
