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
from typing import Callable, Dict, List, Optional

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
    MAX_HIERARCHY_DEPTH,
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
        # Observers fired on a real status transition (e.g. ACTIVE -> ACHIEVED).
        # Callback signature: (goal, old_status: str, new_status: str). Used by
        # the proactive scheduler to fire GOAL_ACHIEVED contacts live.
        self._status_observers: List[Callable] = []
        self._observer_failure_logged = False  # one-shot WARNING throttle

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

    # ---- Hierarchy guard (Plank B0) ----

    def _hierarchy_violation(self, goal: Goal) -> Optional[str]:
        """Return a reason string if ``goal``'s parent link is invalid, else None.

        Pure read over the in-memory index; MUST run BEFORE the goal is inserted
        (so its own id is not yet an ancestor). Enforces three invariants of the
        sub-goal tree:
          - the parent id exists (no dangling reference),
          - no cycle (the goal is not its own ancestor, no repeated ancestor id),
          - the ancestor chain length stays within ``MAX_HIERARCHY_DEPTH``.

        A flat goal (``parent_goal_id is None``) is always valid -- this is the
        only behaviour for every goal in the system today, so the guard is a
        no-op for the existing population and only constrains NEW trees.
        """
        parent_id = goal.parent_goal_id
        if parent_id is None:
            return None
        if parent_id == goal.id:
            return f"self-parent ({goal.id})"
        parent = self._goals.get(parent_id)
        if parent is None:
            return f"parent {parent_id} does not exist"
        # Walk up from the parent. The new goal sits one level below it, so start
        # the depth count at 1 and seed ``seen`` with the new goal's id to catch a
        # link that would route back through it.
        depth = 1
        seen = {goal.id}
        cursor: Optional[Goal] = parent
        while cursor is not None:
            depth += 1
            if cursor.id in seen:
                return f"cycle through {cursor.id}"
            seen.add(cursor.id)
            if depth > MAX_HIERARCHY_DEPTH:
                return (
                    f"depth {depth} exceeds MAX_HIERARCHY_DEPTH={MAX_HIERARCHY_DEPTH}"
                )
            cursor = (
                self._goals.get(cursor.parent_goal_id)
                if cursor.parent_goal_id
                else None
            )
        return None

    def _enforce_hierarchy(self, goal: Goal) -> None:
        """Drop an invalid parent link (orphan the goal flat) with a loud log.

        Fail-SAFE rather than fail-closed: ``create()``/``propose()`` keep their
        total return contract (callers always get an id), but a too-deep or
        cyclic tree can never be persisted -- the goal is created flat instead.
        The operator-facing producer (e.g. /project) validates strictly upfront,
        so a dropped link here only ever signals a buggy producer.
        """
        if goal.parent_goal_id is None:
            return
        violation = self._hierarchy_violation(goal)
        if violation:
            logger.error(
                "[GOALS] hierarchy violation for %s: %s -> orphaning (parent dropped)",
                goal.id,
                violation,
            )
            goal.parent_goal_id = None

    # ---- Status observers ----

    def register_status_observer(self, callback: Callable) -> None:
        """Register a callback fired on every real status transition.

        Callback signature: (goal, old_status: str, new_status: str), where the
        statuses are GoalStatus.value strings. Fired only when the status
        actually changes (no-op re-sets are skipped). Observer exceptions are
        swallowed so a subscriber can never corrupt a store write.

        IMPORTANT: observers run synchronously inside the class-level _io_lock
        critical section (shared by the daemon and every per-request Web-UI
        GoalStore). They MUST be non-blocking and MUST NOT perform external I/O
        or call back into a GoalStore -- a slow observer serializes every goal
        write process-wide. The intended pattern is a cheap in-memory enqueue
        (see ProactiveScheduler.bind_goal_store).
        """
        self._status_observers.append(callback)

    def _notify_status_observers(self, goal: Goal, old_status: str, new_status: str) -> None:
        for cb in self._status_observers:
            try:
                cb(goal, old_status, new_status)
            except Exception as e:  # observers must never break store writes
                # First failure at WARNING so a permanently-broken observer is
                # discoverable in journalctl; later ones at DEBUG to avoid spam.
                if not self._observer_failure_logged:
                    logger.warning("Goal status observer failed: %s", e)
                    self._observer_failure_logged = True
                else:
                    logger.debug("Goal status observer failed: %s", e)

    # ---- Create ----

    @_synchronized
    def create(self, goal: Goal) -> str:
        """Add a goal (PENDING or ACTIVE). Returns id.

        Enforces MAX_ACTIVE_GOALS: if at limit, abandons lowest PENDING.
        """
        self._enforce_hierarchy(goal)
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
        self._enforce_hierarchy(goal)
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
    def get_recently_achieved(self, hours: float = 24.0) -> List[Goal]:
        """Goals that reached ACHIEVED within the last `hours`, newest first.

        Ordered by the audit-trail achievement time, so "recent" means recent in
        time rather than late in the store: goals are keyed by id, and a goal
        finished ten days ago can sit anywhere in insertion order.
        """
        cutoff = time.time() - hours * 3600
        recent = [
            (g.achieved_at, g)
            for g in self._goals.values()
            if g.status == GoalStatus.ACHIEVED
            and g.achieved_at is not None
            and g.achieved_at >= cutoff
        ]
        return [g for _, g in sorted(recent, key=lambda pair: pair[0], reverse=True)]

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

        # Notify observers only on a genuine transition (e.g. ACTIVE -> ACHIEVED),
        # so a redundant re-set never re-fires a proactive contact.
        if old_status != status.value:
            self._notify_status_observers(goal, old_status, status.value)

        return True

    # Perpetual goals never auto-achieve at progress 1.0: MAINTENANCE recurs each
    # session, and META is the always-on learning MISSION. Letting META "complete"
    # when the library is fully learned made it terminal -> no active META -> the
    # saturation->FETCH supply pump stalled until the next boot (2026-06-16 ->
    # 06-23 throughput regression). A mission is never "done"; when material runs
    # out it stays active so it can FETCH more.
    _NEVER_AUTO_ACHIEVE = (GoalType.MAINTENANCE, GoalType.META)

    @_synchronized
    def update_progress(self, goal_id: str, progress: float) -> bool:
        """Update progress. Auto-ACHIEVED at >= 1.0 for ACTIVE non-perpetual goals."""
        goal = self._goals.get(goal_id)
        if not goal:
            return False

        goal.progress = max(0.0, min(1.0, progress))
        goal.updated_at = time.time()
        self._mark_dirty(goal_id)

        # Auto-ACHIEVED (perpetual MAINTENANCE / META missions are exempt).
        if goal.progress >= 1.0 and goal.status == GoalStatus.ACTIVE:
            if goal.type not in self._NEVER_AUTO_ACHIEVE:
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

    @_synchronized
    def ensure_meta_goal(self) -> bool:
        """Guarantee the always-on META mission goal is active (self-heal on boot).

        seed_if_empty() only seeds an EMPTY store, so a META mission that was
        abandoned (e.g. by the non-productive-loop detector before it was exempted)
        would never return -- silently disabling the saturation->FETCH supply pump
        and leaving the learner to idle on no_goals once the backlog drained. This
        reactivates the canonical seed META goal (or recreates it) whenever no META
        goal is currently active. Returns True if it had to restore the mission."""
        if any(g.type == GoalType.META and g.is_active
               for g in self._goals.values()):
            return False
        existing = self._goals.get("goal-meta-learn")
        if existing is not None:
            self.update_status(
                "goal-meta-learn", GoalStatus.ACTIVE,
                "restored always-on mission (was inactive)", "system",
            )
            logger.warning("[GOALS] Reactivated META mission goal-meta-learn")
            return True
        meta = create_goal(
            goal_type=GoalType.META,
            description="Autonomiczna nauka i strukturyzacja wiedzy z plikow tekstowych",
            priority=1.0,
            status=GoalStatus.ACTIVE,
            created_by="system",
            goal_id="goal-meta-learn",
        )
        self.create(meta)
        logger.warning("[GOALS] Recreated missing META mission goal-meta-learn")
        return True

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
