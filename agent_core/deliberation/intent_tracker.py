"""
Intent Tracker for K8 Deliberation.

Tracks WHY the agent is doing something (intent chain).
v1: simple JSONL log of intents per goal.
v2 path: intent trees, causal chains, meta-reasoning.

Each intent records: what goal, what strategy, why chosen, when.
Used by Deliberator to avoid repeating failed approaches.

Kontrakt: docs/CONTRACTS.md - Kontrakt 8: Deliberation
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class IntentRecord:
    """A single intent entry - why a strategy was chosen for a goal."""

    goal_id: str
    strategy_id: str
    template_name: str
    reason: str  # Why this strategy (e.g. "weak_topics_detected", "new_files_available")
    timestamp: float = 0.0
    outcome: str = ""  # "completed", "abandoned", "in_progress"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "strategy_id": self.strategy_id,
            "template_name": self.template_name,
            "reason": self.reason,
            "timestamp": self.timestamp or time.time(),
            "outcome": self.outcome,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "IntentRecord":
        return IntentRecord(
            goal_id=d["goal_id"],
            strategy_id=d["strategy_id"],
            template_name=d.get("template_name", ""),
            reason=d.get("reason", ""),
            timestamp=d.get("timestamp", 0.0),
            outcome=d.get("outcome", ""),
            metadata=d.get("metadata", {}),
        )


class IntentTracker:
    """
    Tracks intent history for goal-strategy decisions.

    JSONL persistence with bounded reads (max 500 records).
    v2 path: intent trees, causal chain queries.
    """

    MAX_RECORDS = 500

    def __init__(self, path: Optional[Path] = None):
        self._path = path or Path("meta_data/deliberation_intents.jsonl")
        self._cache: List[IntentRecord] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").strip().split("\n")
            # Bounded read (OOM prevention)
            for line in lines[-self.MAX_RECORDS :]:
                if line.strip():
                    self._cache.append(IntentRecord.from_dict(json.loads(line)))
        except (json.JSONDecodeError, OSError):
            pass

    def record(
        self,
        goal_id: str,
        strategy_id: str,
        template_name: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IntentRecord:
        """Record a new intent (strategy chosen for a goal)."""
        self._ensure_loaded()
        rec = IntentRecord(
            goal_id=goal_id,
            strategy_id=strategy_id,
            template_name=template_name,
            reason=reason,
            timestamp=time.time(),
            outcome="in_progress",
            metadata=metadata or {},
        )
        self._cache.append(rec)
        self._append_jsonl(rec)
        return rec

    def update_outcome(self, strategy_id: str, outcome: str) -> bool:
        """Update the outcome of a tracked intent."""
        self._ensure_loaded()
        for rec in reversed(self._cache):
            if rec.strategy_id == strategy_id:
                rec.outcome = outcome
                self._rewrite_jsonl()
                return True
        return False

    def query_by_goal(self, goal_id: str) -> List[IntentRecord]:
        """Get all intents for a goal (most recent last)."""
        self._ensure_loaded()
        return [r for r in self._cache if r.goal_id == goal_id]

    def query_recent(self, limit: int = 10) -> List[IntentRecord]:
        """Get N most recent intents."""
        self._ensure_loaded()
        return self._cache[-limit:]

    def count_failed_template(self, goal_id: str, template_name: str) -> int:
        """Count how many times a template was abandoned for a goal recently (last 24h)."""
        self._ensure_loaded()
        cutoff = time.time() - 86400  # 24h window
        return sum(
            1
            for r in self._cache
            if r.goal_id == goal_id
            and r.template_name == template_name
            and r.outcome == "abandoned"
            and r.timestamp >= cutoff
        )

    def _append_jsonl(self, rec: IntentRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _rewrite_jsonl(self) -> None:
        """Rewrite full file (used after update_outcome)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                for rec in self._cache:
                    f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass
