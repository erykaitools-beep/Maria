"""Append-only JSONL persistence for Creative Module outputs.

Pattern: BeliefStore / GoalStore MERGE semantics.
6 JSONL stores as defined in spec section 9.

Stores:
    meta_data/creative_journal.jsonl         - strategic journal entries
    meta_data/conversation_memory.jsonl      - operator-dialogue memory
    meta_data/creative_meta_goals.jsonl      - generated meta-goals + status transitions
    meta_data/creative_workspace_sessions.jsonl - completed reflection session summaries
    meta_data/creative_events.jsonl          - module-level telemetry events
    meta_data/personality_signals.jsonl      - personality style adjustments
"""

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.creative.creative_model import (
    MetaGoal, MetaGoalStatus, DetectedTension, CreativeInsight,
    ExplorationProgram, PersonalitySignal, ReframeProposal,
    StrategicObservation, CreativeJournalEntry, ConversationMemoryEntry,
    ReflectionSession,
)

logger = logging.getLogger(__name__)

# Caps to prevent unbounded growth
MAX_JOURNAL_ENTRIES = 500
MAX_CONVERSATION_MEMORIES = 1000
MAX_META_GOALS = 500
MAX_WORKSPACE_SESSIONS = 200
MAX_PERSONALITY_SIGNALS = 200


def _serialize_enum(obj: Any) -> Any:
    """JSON serializer for enum values in dataclass dicts."""
    if hasattr(obj, 'value'):
        return obj.value
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    """Append one JSON line to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=_serialize_enum) + "\n")


def _load_jsonl_merged(path: Path, key_field: str, max_records: int) -> Dict[str, Dict]:
    """Load JSONL with MERGE semantics (last record per key wins)."""
    records: Dict[str, Dict] = {}
    if not path.exists():
        return records
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    key = record.get(key_field, "")
                    if key:
                        records[key] = record
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning(f"[CREATIVE_STORE] Failed to read {path}: {e}")

    # Cap: keep most recent by timestamp
    if len(records) > max_records:
        sorted_keys = sorted(
            records.keys(),
            key=lambda k: records[k].get("created_ts", 0),
            reverse=True,
        )
        records = {k: records[k] for k in sorted_keys[:max_records]}

    return records


def _load_jsonl_append_only(path: Path, max_records: int) -> List[Dict]:
    """Load JSONL in append-only mode (no merge, keep last N)."""
    records: List[Dict] = []
    if not path.exists():
        return records
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning(f"[CREATIVE_STORE] Failed to read {path}: {e}")

    if len(records) > max_records:
        records = records[-max_records:]
    return records


class CreativeStore:
    """Centralized JSONL persistence for all Creative artifacts."""

    def __init__(self, data_dir: str = "meta_data"):
        self._dir = Path(data_dir)

        # Paths
        self._journal_path = self._dir / "creative_journal.jsonl"
        self._conv_memory_path = self._dir / "conversation_memory.jsonl"
        self._meta_goals_path = self._dir / "creative_meta_goals.jsonl"
        self._workspace_path = self._dir / "creative_workspace_sessions.jsonl"
        self._events_path = self._dir / "creative_events.jsonl"
        self._signals_path = self._dir / "personality_signals.jsonl"

        # In-memory caches (loaded on demand)
        self._journal: Optional[Dict[str, Dict]] = None
        self._meta_goals: Optional[Dict[str, Dict]] = None
        self._conv_memories: Optional[Dict[str, Dict]] = None

    # --- Journal ---

    def save_journal_entry(self, entry: CreativeJournalEntry) -> None:
        _append_jsonl(self._journal_path, asdict(entry))
        if self._journal is not None:
            self._journal[entry.entry_id] = asdict(entry)
        logger.info(f"[CREATIVE] Journal entry saved: {entry.entry_id}")

    def load_journal(self) -> List[Dict]:
        if self._journal is None:
            self._journal = _load_jsonl_merged(
                self._journal_path, "entry_id", MAX_JOURNAL_ENTRIES
            )
        return list(self._journal.values())

    # --- Meta-goals ---

    def save_meta_goal(self, mg: MetaGoal) -> None:
        _append_jsonl(self._meta_goals_path, asdict(mg))
        if self._meta_goals is not None:
            self._meta_goals[mg.goal_id] = asdict(mg)
        logger.info(f"[CREATIVE] Meta-goal saved: {mg.goal_id} ({mg.status.value})")

    def load_meta_goals(self) -> List[Dict]:
        if self._meta_goals is None:
            self._meta_goals = _load_jsonl_merged(
                self._meta_goals_path, "goal_id", MAX_META_GOALS
            )
        return list(self._meta_goals.values())

    def get_recent_meta_goals(self, hours: float = 24.0) -> List[Dict]:
        """Get meta-goals from last N hours (for dedup)."""
        cutoff = time.time() - hours * 3600
        return [
            mg for mg in self.load_meta_goals()
            if mg.get("created_ts", 0) > cutoff
        ]

    # --- Conversation memory ---

    def save_conversation_memory(self, entry: ConversationMemoryEntry) -> None:
        _append_jsonl(self._conv_memory_path, asdict(entry))
        if self._conv_memories is not None:
            self._conv_memories[entry.memory_id] = asdict(entry)

    def load_conversation_memories(self) -> List[Dict]:
        if self._conv_memories is None:
            self._conv_memories = _load_jsonl_merged(
                self._conv_memory_path, "memory_id", MAX_CONVERSATION_MEMORIES
            )
        return list(self._conv_memories.values())

    def get_memories_by_type(self, memory_type: str) -> List[Dict]:
        return [
            m for m in self.load_conversation_memories()
            if m.get("memory_type") == memory_type
        ]

    def get_memories_by_importance(self, min_importance: float = 0.5) -> List[Dict]:
        return sorted(
            [m for m in self.load_conversation_memories()
             if m.get("importance", 0) >= min_importance],
            key=lambda m: m.get("importance", 0),
            reverse=True,
        )

    # --- Workspace sessions ---

    def save_workspace_session(self, session: ReflectionSession) -> None:
        """Save completed reflection session summary."""
        summary = {
            "session_id": session.session_id,
            "trigger": session.trigger,
            "problem_statement": session.problem_statement,
            "tension_count": len(session.detected_tensions),
            "insight_count": len(session.insights),
            "meta_goal_count": len(session.candidate_meta_goals),
            "reframe_count": len(session.candidate_reframes),
            "observation_count": len(session.observations),
            "started_ts": session.started_ts,
            "closed_ts": time.time(),
            "tension_ids": [t.tension_id for t in session.detected_tensions],
            "insight_ids": [i.insight_id for i in session.insights],
            "meta_goal_ids": [mg.goal_id for mg in session.candidate_meta_goals],
        }
        _append_jsonl(self._workspace_path, summary)
        logger.info(f"[CREATIVE] Workspace session saved: {session.session_id}")

    def load_workspace_sessions(self) -> List[Dict]:
        return _load_jsonl_append_only(self._workspace_path, MAX_WORKSPACE_SESSIONS)

    # --- Telemetry events ---

    def log_event(self, event_name: str, payload: Dict[str, Any] = None) -> None:
        record = {
            "event": event_name,
            "timestamp": time.time(),
            "payload": payload or {},
        }
        _append_jsonl(self._events_path, record)

    def load_events(self, last_n: int = 50) -> List[Dict]:
        events = _load_jsonl_append_only(self._events_path, 1000)
        return events[-last_n:]

    # --- Personality signals ---

    def save_personality_signal(self, signal: PersonalitySignal) -> None:
        _append_jsonl(self._signals_path, asdict(signal))
        logger.info(f"[CREATIVE] Personality signal: {signal.dimension.value} -> {signal.direction}")

    def load_personality_signals(self) -> List[Dict]:
        return _load_jsonl_append_only(self._signals_path, MAX_PERSONALITY_SIGNALS)
