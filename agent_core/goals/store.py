"""
GoalStore - CRUD + persistence for Goal System.

Kontrakt: docs/CONTRACTS.md - Kontrakt 3: Goal System
Persistence: meta_data/goals.jsonl (append-only, last record per id wins).
"""

import functools
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from agent_core.goals.goal_model import (
    Goal,
    GoalType,
    GoalStatus,
    AuditEntry,
    create_goal,
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    MAX_ACTIVE_GOALS,
    MAX_PROPOSED_GOALS,
    PROPOSED_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


def _synchronized(method):
    """Serialize a GoalStore method on the shared class-level I/O lock.

    The Web UI creates its own GoalStore instance per request in the same
    process as the daemon, so the lock is class-level (shared by all
    instances) to serialize concurrent access to goals.jsonl.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._io_lock:
            return method(self, *args, **kwargs)
    return wrapper


class GoalStore:
    """CRUD + persistence for goals."""

    # Shared across all instances in this process (daemon + per-request UI).
    _io_lock = threading.RLock()

    def __init__(self, goals_path: Path):
        """
        Args:
            goals_path: Path to goals.jsonl (append-only).
        """
        self._goals_path = goals_path
        self._goals: Dict[str, Goal] = {}  # id -> Goal (in-memory cache)
        self._dirty_ids: set = set()  # ids that need saving

    # ---- Load / Save ----

    @_synchronized
    def load(self) -> None:
        """Load goals from JSONL. Last record per id wins."""
        self._goals.clear()
        if not self._goals_path.exists():
            return

        try:
            with open(self._goals_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        goal = Goal.from_dict(data)
                        self._goals[goal.id] = goal
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(f"goals.jsonl line {line_no}: {e}")
        except OSError as e:
            logger.error(f"Cannot read goals.jsonl: {e}")

        self._dirty_ids.clear()

    @_synchronized
    def save(self) -> None:
        """Append dirty goals to JSONL."""
        if not self._dirty_ids:
            return

        self._goals_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self._goals_path, "a", encoding="utf-8") as f:
                for gid in self._dirty_ids:
                    goal = self._goals.get(gid)
                    if goal:
                        line = json.dumps(goal.to_dict(), ensure_ascii=False)
                        f.write(line + "\n")
            self._dirty_ids.clear()
            self._compact_if_needed()
        except OSError as e:
            logger.error(f"Cannot write goals.jsonl: {e}")

    @_synchronized
    def compact(self) -> None:
        """Rewrite goals.jsonl to one latest record per goal id.

        Merges records from disk first so a rewrite from our (possibly stale)
        cache never drops goals another in-process instance appended.
        """
        if not self._goals_path.exists():
            return

        self._merge_from_disk()
        line_count = self._count_nonempty_lines()
        unique_count = len(self._goals)
        tmp_path = self._goals_path.with_suffix(self._goals_path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for goal in self._goals.values():
                    line = json.dumps(goal.to_dict(), ensure_ascii=False)
                    f.write(line + "\n")
            tmp_path.replace(self._goals_path)
            logger.info(
                "Compacted goals.jsonl: %s lines -> %s unique goals",
                line_count,
                unique_count,
            )
        except OSError as e:
            logger.error(f"Cannot compact goals.jsonl: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _merge_from_disk(self) -> None:
        """Merge file records into the cache; newer updated_at wins.

        Guards against another in-process GoalStore (the Web UI builds one
        per request) having appended status changes our cache predates.
        """
        if not self._goals_path.exists():
            return
        try:
            with open(self._goals_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        goal = Goal.from_dict(json.loads(line))
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
                    cached = self._goals.get(goal.id)
                    if cached is None or goal.updated_at >= cached.updated_at:
                        self._goals[goal.id] = goal
        except OSError as e:
            logger.error(f"Cannot merge goals.jsonl: {e}")

    def _count_nonempty_lines(self) -> int:
        """Count non-empty JSONL rows in goals file."""
        if not self._goals_path.exists():
            return 0
        try:
            with open(self._goals_path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except OSError as e:
            logger.error(f"Cannot inspect goals.jsonl for compaction: {e}")
            return 0

    def _compact_if_needed(self) -> None:
        """Run compaction when lines exceed 2x unique in-memory records."""
        unique_count = len(self._goals)
        if unique_count == 0:
            return
        line_count = self._count_nonempty_lines()
        if line_count > (2 * unique_count):
            self.compact()

    def _mark_dirty(self, goal_id: str) -> None:
        self._dirty_ids.add(goal_id)

    # ---- Create ----

    @_synchronized
    def create(self, goal: Goal) -> str:
        """Add a goal (PENDING or ACTIVE). Returns id.

        Enforces MAX_ACTIVE_GOALS: if at limit, abandons lowest PENDING.
        """
        if goal.status in ACTIVE_STATUSES:
            active_count = sum(1 for g in self._goals.values() if g.is_active)
            if active_count >= MAX_ACTIVE_GOALS:
                abandoned = self.abandon_lowest()
                if abandoned:
                    logger.info(f"Overflow: abandoned {abandoned} to make room")

        self._goals[goal.id] = goal
        self._mark_dirty(goal.id)
        return goal.id

    # Sources whose PROPOSED goals are auto-confirmed (low risk learning)
    AUTO_CONFIRM_SOURCES = {"creative", "critic", "self_analysis"}

    @_synchronized
    def propose(self, goal: Goal) -> Optional[str]:
        """Create a PROPOSED goal (awaiting user confirmation).

        Auto-confirm: goals from creative/critic/self_analysis with risk_level
        "low" (or unset) and type LEARNING/META skip PROPOSED and go straight
        to PENDING. Experiments (K11) always require manual approval.

        Enforces MAX_PROPOSED_GOALS. If at limit, replaces the lowest-priority
        PROPOSED goal when the new goal has higher priority (displacement).
        Returns None only if new goal cannot displace any existing one.
        """
        # Auto-confirm low-risk learning goals
        if self._should_auto_confirm(goal):
            goal.status = GoalStatus.PENDING
            goal.audit_trail.append(AuditEntry(
                timestamp=time.time(),
                old_status=None,
                new_status="pending",
                reason="auto-confirmed (low risk)",
                actor="system",
            ))
            goal.updated_at = time.time()
            self._goals[goal.id] = goal
            self._mark_dirty(goal.id)
            logger.info(
                f"[GOALS] Auto-confirmed {goal.id} "
                f"(source={goal.created_by}, type={goal.type.value})"
            )
            return goal.id

        proposed = [
            g for g in self._goals.values()
            if g.status == GoalStatus.PROPOSED
        ]
        if len(proposed) >= MAX_PROPOSED_GOALS:
            # Find lowest-priority proposed goal
            lowest = min(proposed, key=lambda g: g.priority)
            if goal.priority > lowest.priority:
                # Displace: abandon lowest to make room
                self.update_status(
                    lowest.id, GoalStatus.ABANDONED,
                    f"displaced by higher-priority proposal ({goal.priority:.2f} > {lowest.priority:.2f})",
                    "creative",
                )
                logger.info(
                    f"[GOALS] Displaced PROPOSED {lowest.id} "
                    f"(pri={lowest.priority:.2f}) for {goal.id} (pri={goal.priority:.2f})"
                )
            else:
                return None

        goal.status = GoalStatus.PROPOSED
        # Ensure audit trail reflects PROPOSED status
        if not goal.audit_trail or goal.audit_trail[-1].new_status != "proposed":
            goal.audit_trail.append(AuditEntry(
                timestamp=time.time(),
                old_status=None,
                new_status="proposed",
                reason="auto-suggested",
                actor=goal.created_by,
            ))
        goal.updated_at = time.time()

        self._goals[goal.id] = goal
        self._mark_dirty(goal.id)
        return goal.id

    def _should_auto_confirm(self, goal: Goal) -> bool:
        """Check if goal qualifies for auto-confirmation."""
        # Only auto-confirm from known safe sources
        if goal.created_by not in self.AUTO_CONFIRM_SOURCES:
            return False
        # Only learning and meta goals (not experiment/maintenance)
        if goal.type not in (GoalType.LEARNING, GoalType.META):
            return False
        # High risk goals still need approval
        risk = goal.metadata.get("risk_level", "low")
        if risk in ("medium", "high"):
            return False
        return True

    # ---- Read ----

    @_synchronized
    def get(self, goal_id: str) -> Optional[Goal]:
        """Get goal by id."""
        return self._goals.get(goal_id)

    @_synchronized
    def get_all(self) -> List[Goal]:
        """Get all goals (including terminal)."""
        return list(self._goals.values())

    @_synchronized
    def get_active(self, goal_type: Optional[GoalType] = None) -> List[Goal]:
        """Get active goals (PENDING + ACTIVE), optionally filtered by type."""
        result = [g for g in self._goals.values() if g.is_active]
        if goal_type is not None:
            result = [g for g in result if g.type == goal_type]
        return sorted(result, key=lambda g: g.priority, reverse=True)

    @_synchronized
    def get_proposed(self) -> List[Goal]:
        """Get goals awaiting user confirmation (PROPOSED)."""
        return [
            g for g in self._goals.values()
            if g.status == GoalStatus.PROPOSED
        ]

    @_synchronized
    def get_children(self, parent_goal_id: str) -> List[Goal]:
        """Get child goals of a parent."""
        return [
            g for g in self._goals.values()
            if g.parent_goal_id == parent_goal_id
        ]

    @_synchronized
    def find_by_topic(self, topic: str) -> List[Goal]:
        """Find LEARNING goals matching a topic (case-insensitive substring)."""
        topic_lower = topic.lower()
        results = []
        for g in self._goals.values():
            if g.type != GoalType.LEARNING:
                continue
            meta_topic = (g.metadata.get("topic") or "").lower()
            meta_topics = [t.lower() for t in g.metadata.get("topics", [])]
            desc_lower = g.description.lower()
            if (topic_lower in meta_topic
                    or any(topic_lower in t for t in meta_topics)
                    or topic_lower in desc_lower):
                results.append(g)
        return sorted(results, key=lambda g: g.created_at, reverse=True)

    @_synchronized
    def set_outcome(self, goal_id: str, outcome: dict) -> bool:
        """Set outcome dict on a goal (typically on completion)."""
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        goal.outcome = outcome
        goal.updated_at = __import__('time').time()
        self._mark_dirty(goal_id)
        return True

    # ---- Update ----

    @_synchronized
    def confirm(self, goal_id: str) -> bool:
        """User confirms PROPOSED goal -> PENDING."""
        goal = self._goals.get(goal_id)
        if not goal or goal.status != GoalStatus.PROPOSED:
            return False
        return self.update_status(goal_id, GoalStatus.PENDING, "user confirmed", "user")

    @_synchronized
    def reject(self, goal_id: str) -> bool:
        """User rejects PROPOSED goal -> ABANDONED."""
        goal = self._goals.get(goal_id)
        if not goal or goal.status != GoalStatus.PROPOSED:
            return False
        return self.update_status(goal_id, GoalStatus.ABANDONED, "user rejected", "user")

    @_synchronized
    def update_status(
        self, goal_id: str, status: GoalStatus, reason: str, actor: str
    ) -> bool:
        """Change goal status with audit trail."""
        goal = self._goals.get(goal_id)
        if not goal:
            return False

        now = time.time()
        old_status = goal.status.value

        goal.audit_trail.append(AuditEntry(
            timestamp=now,
            old_status=old_status,
            new_status=status.value,
            reason=reason,
            actor=actor,
        ))
        goal.status = status
        goal.updated_at = now
        self._mark_dirty(goal_id)
        return True

    @_synchronized
    def update_progress(self, goal_id: str, progress: float) -> bool:
        """Update progress. Auto-ACHIEVED at >= 1.0 for ACTIVE goals."""
        goal = self._goals.get(goal_id)
        if not goal:
            return False

        goal.progress = max(0.0, min(1.0, progress))
        goal.updated_at = time.time()
        self._mark_dirty(goal_id)

        # Auto-ACHIEVED
        if goal.progress >= 1.0 and goal.status == GoalStatus.ACTIVE:
            # MAINTENANCE goals never auto-achieve
            if goal.type != GoalType.MAINTENANCE:
                self.update_status(
                    goal_id, GoalStatus.ACHIEVED,
                    "progress >= 1.0", "system"
                )

        return True

    # ---- Cleanup ----

    @_synchronized
    def abandon_lowest(self) -> Optional[str]:
        """Abandon lowest priority PENDING goal. Returns id or None."""
        pending = [
            g for g in self._goals.values()
            if g.status == GoalStatus.PENDING
        ]
        if not pending:
            return None

        lowest = min(pending, key=lambda g: g.priority)
        self.update_status(
            lowest.id, GoalStatus.ABANDONED,
            "overflow: max active goals exceeded", "system"
        )
        return lowest.id

    @_synchronized
    def expire_proposed(self) -> int:
        """Auto-ABANDON PROPOSED goals older than 24h. Returns count."""
        now = time.time()
        count = 0
        for goal in list(self._goals.values()):
            if goal.status == GoalStatus.PROPOSED:
                age = now - goal.created_at
                if age > PROPOSED_TIMEOUT_SECONDS:
                    self.update_status(
                        goal.id, GoalStatus.ABANDONED,
                        "proposed timeout (24h)", "system"
                    )
                    count += 1
        return count

    @_synchronized
    def reset_maintenance(self) -> int:
        """Reset MAINTENANCE goals for new session. Returns count."""
        count = 0
        for goal in self._goals.values():
            if goal.type == GoalType.MAINTENANCE and goal.is_active:
                goal.progress = 0.0
                goal.updated_at = time.time()
                self._mark_dirty(goal.id)
                count += 1
        return count

    # ---- Seed Goals ----

    @_synchronized
    def seed_if_empty(self) -> int:
        """Create seed goals (META + MAINTENANCE) if store is empty. Returns count."""
        if self._goals:
            return 0

        count = 0
        now = time.time()

        # META goal
        meta = create_goal(
            goal_type=GoalType.META,
            description="Autonomiczna nauka i strukturyzacja wiedzy z plikow tekstowych",
            priority=1.0,
            status=GoalStatus.ACTIVE,
            created_by="system",
            goal_id="goal-meta-learn",
        )
        self.create(meta)
        count += 1

        # MAINTENANCE: health
        health = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description="Utrzymaj health_score >= 0.7",
            priority=1.0,
            status=GoalStatus.ACTIVE,
            created_by="homeostasis",
            goal_id="goal-maint-health",
            metadata={"metric": "health_score", "threshold": 0.7},
        )
        self.create(health)
        count += 1

        # MAINTENANCE: RAM (sub-goal of health)
        ram = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description="RAM dostepny > 20%",
            priority=0.95,
            status=GoalStatus.ACTIVE,
            created_by="homeostasis",
            parent_goal_id="goal-maint-health",
            goal_id="goal-maint-ram",
            metadata={"metric": "ram_available_pct", "threshold": 20},
        )
        self.create(ram)
        count += 1

        # MAINTENANCE: CPU (sub-goal of health)
        cpu = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description="CPU < 75%",
            priority=0.95,
            status=GoalStatus.ACTIVE,
            created_by="homeostasis",
            parent_goal_id="goal-maint-health",
            goal_id="goal-maint-cpu",
            metadata={"metric": "cpu_load", "threshold": 75},
        )
        self.create(cpu)
        count += 1

        return count

    # ---- Stats ----

    @_synchronized
    def stats(self) -> dict:
        """Return summary statistics."""
        by_status = {}
        by_type = {}
        for goal in self._goals.values():
            by_status[goal.status.value] = by_status.get(goal.status.value, 0) + 1
            by_type[goal.type.value] = by_type.get(goal.type.value, 0) + 1

        return {
            "total": len(self._goals),
            "active": sum(1 for g in self._goals.values() if g.is_active),
            "proposed": sum(1 for g in self._goals.values() if g.status == GoalStatus.PROPOSED),
            "terminal": sum(1 for g in self._goals.values() if g.is_terminal),
            "by_status": by_status,
            "by_type": by_type,
        }
