"""
Incident Memory - Structured failure tracking for Trust & Autonomy Graduation.

Maria remembers her own mistakes:
- What failed, why, and how to avoid it next time
- Temporary confidence penalty after incidents (decays over time)
- Links incidents to action types and goals

Faza 7: Trust & Autonomy Graduation (Digital Human Roadmap).
Persistence: meta_data/incidents.jsonl (append-only).
"""

import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Incident penalty parameters
PENALTY_DECAY_DAYS = 7.0          # Full decay period
PENALTY_BASE = 0.15               # Base penalty per incident
PENALTY_MAX = 0.5                 # Max cumulative penalty per action type
MAX_INCIDENTS_IN_MEMORY = 500     # In-memory cap
DEFAULT_INCIDENTS_PATH = Path("meta_data/incidents.jsonl")


@dataclass
class IncidentRecord:
    """A single recorded failure/mistake."""
    incident_id: str
    timestamp: float
    action_type: str              # What kind of action failed (learn, fetch, effector, etc.)
    tool_name: str = ""           # Specific tool if applicable
    error_type: str = ""          # Category (timeout, permission, parse_error, etc.)
    description: str = ""         # What happened
    context: Dict = field(default_factory=dict)  # What was being attempted
    goal_id: str = ""             # Affected goal
    severity: str = "minor"       # minor / major / critical
    resolved: bool = False
    resolution: str = ""          # How it was fixed
    prevention: str = ""          # How to avoid next time

    def to_dict(self) -> Dict:
        """Serialize for JSONL."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "IncidentRecord":
        """Deserialize from JSONL."""
        return cls(
            incident_id=data.get("incident_id", ""),
            timestamp=data.get("timestamp", 0.0),
            action_type=data.get("action_type", ""),
            tool_name=data.get("tool_name", ""),
            error_type=data.get("error_type", ""),
            description=data.get("description", ""),
            context=data.get("context", {}),
            goal_id=data.get("goal_id", ""),
            severity=data.get("severity", "minor"),
            resolved=data.get("resolved", False),
            resolution=data.get("resolution", ""),
            prevention=data.get("prevention", ""),
        )

    def age_days(self) -> float:
        """How old is this incident in days."""
        return (time.time() - self.timestamp) / 86400.0


class IncidentMemory:
    """
    Tracks Maria's failures and mistakes.

    Features:
    - Record incidents with structured metadata
    - Query recent incidents by action type
    - Compute confidence penalty (decays over PENALTY_DECAY_DAYS)
    - Check if similar incident occurred recently (should_avoid)
    - JSONL persistence (append-only)

    Thread-safe.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or DEFAULT_INCIDENTS_PATH
        self._lock = threading.Lock()
        self._incidents: List[IncidentRecord] = []
        self._load()

    def _load(self) -> None:
        """Load incidents from JSONL."""
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").strip().split("\n")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    self._incidents.append(IncidentRecord.from_dict(data))
                except (json.JSONDecodeError, KeyError):
                    continue
            # Keep only most recent
            if len(self._incidents) > MAX_INCIDENTS_IN_MEMORY:
                self._incidents = self._incidents[-MAX_INCIDENTS_IN_MEMORY:]
            logger.info("IncidentMemory loaded %d incidents", len(self._incidents))
        except Exception as e:
            logger.warning("Failed to load incidents: %s", e)

    def _append(self, record: IncidentRecord) -> None:
        """Append a single record to JSONL."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to persist incident: %s", e)

    def record_incident(
        self,
        action_type: str,
        error_type: str = "",
        description: str = "",
        tool_name: str = "",
        context: Optional[Dict] = None,
        goal_id: str = "",
        severity: str = "minor",
    ) -> IncidentRecord:
        """
        Record a new incident.

        Args:
            action_type: What kind of action failed
            error_type: Category of error
            description: Human-readable description
            tool_name: Specific tool (if applicable)
            context: What was being attempted
            goal_id: Affected goal ID
            severity: minor / major / critical

        Returns:
            The created IncidentRecord.
        """
        record = IncidentRecord(
            incident_id=f"inc-{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            action_type=action_type,
            tool_name=tool_name,
            error_type=error_type,
            description=description,
            context=context or {},
            goal_id=goal_id,
            severity=severity,
        )

        with self._lock:
            self._incidents.append(record)
            # Cap in-memory
            if len(self._incidents) > MAX_INCIDENTS_IN_MEMORY:
                self._incidents = self._incidents[-MAX_INCIDENTS_IN_MEMORY:]
            self._append(record)

        logger.info(
            "Incident recorded: %s [%s] %s - %s",
            record.incident_id, action_type, error_type, description[:80],
        )
        return record

    def resolve_incident(
        self,
        incident_id: str,
        resolution: str = "",
        prevention: str = "",
    ) -> bool:
        """
        Mark an incident as resolved with lessons learned.

        Returns True if found and updated.
        """
        with self._lock:
            for inc in reversed(self._incidents):
                if inc.incident_id == incident_id:
                    inc.resolved = True
                    inc.resolution = resolution
                    inc.prevention = prevention
                    # Re-persist (append update as new line - latest wins)
                    self._append(inc)
                    return True
        return False

    def get_recent(
        self,
        action_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[IncidentRecord]:
        """Get recent incidents, optionally filtered by action type."""
        with self._lock:
            incidents = list(self._incidents)
        if action_type:
            incidents = [i for i in incidents if i.action_type == action_type]
        return incidents[-limit:]

    def get_unresolved(
        self,
        action_type: Optional[str] = None,
    ) -> List[IncidentRecord]:
        """Get all unresolved incidents."""
        with self._lock:
            incidents = list(self._incidents)
        result = [i for i in incidents if not i.resolved]
        if action_type:
            result = [i for i in result if i.action_type == action_type]
        return result

    def get_incident_penalty(self, action_type: str) -> float:
        """
        Compute confidence penalty for an action type based on recent incidents.

        Penalty decays linearly over PENALTY_DECAY_DAYS.
        Returns 0.0 (no penalty) to PENALTY_MAX.
        """
        with self._lock:
            incidents = [
                i for i in self._incidents
                if i.action_type == action_type
            ]

        now = time.time()
        total_penalty = 0.0

        for inc in incidents:
            age_days = (now - inc.timestamp) / 86400.0
            if age_days >= PENALTY_DECAY_DAYS:
                continue  # Fully decayed

            # Linear decay: 1.0 at day 0, 0.0 at PENALTY_DECAY_DAYS
            decay = 1.0 - (age_days / PENALTY_DECAY_DAYS)

            # Severity multiplier
            sev_mult = {"minor": 1.0, "major": 1.5, "critical": 2.0}.get(
                inc.severity, 1.0
            )

            total_penalty += PENALTY_BASE * decay * sev_mult

        return min(total_penalty, PENALTY_MAX)

    def should_avoid(
        self,
        action_type: str,
        context: Optional[Dict] = None,
        lookback_hours: float = 24.0,
    ) -> bool:
        """
        Check if a similar incident occurred recently.

        Matches on action_type + error_type within lookback_hours.
        Returns True if Maria should be cautious.
        """
        cutoff = time.time() - (lookback_hours * 3600)

        with self._lock:
            recent = [
                i for i in self._incidents
                if i.action_type == action_type
                and i.timestamp >= cutoff
                and not i.resolved
            ]

        if not recent:
            return False

        # If context provided, check for similar tool_name
        if context and context.get("tool_name"):
            tool = context["tool_name"]
            return any(i.tool_name == tool for i in recent)

        return len(recent) >= 2  # 2+ unresolved incidents = avoid

    def get_stats(self) -> Dict:
        """Get incident statistics for dashboard."""
        with self._lock:
            incidents = list(self._incidents)

        if not incidents:
            return {
                "total": 0,
                "unresolved": 0,
                "by_action_type": {},
                "by_severity": {},
                "recent_7d": 0,
            }

        now = time.time()
        cutoff_7d = now - (7 * 86400)

        by_action: Dict[str, int] = defaultdict(int)
        by_severity: Dict[str, int] = defaultdict(int)
        unresolved = 0
        recent_7d = 0

        for inc in incidents:
            by_action[inc.action_type] += 1
            by_severity[inc.severity] += 1
            if not inc.resolved:
                unresolved += 1
            if inc.timestamp >= cutoff_7d:
                recent_7d += 1

        return {
            "total": len(incidents),
            "unresolved": unresolved,
            "by_action_type": dict(by_action),
            "by_severity": dict(by_severity),
            "recent_7d": recent_7d,
        }

    def count(self, action_type: Optional[str] = None) -> int:
        """Count incidents, optionally filtered."""
        with self._lock:
            if action_type:
                return sum(
                    1 for i in self._incidents if i.action_type == action_type
                )
            return len(self._incidents)
