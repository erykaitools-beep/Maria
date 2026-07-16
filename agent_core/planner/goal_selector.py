"""
GoalSelector - Rule-based goal selection with aging factor.

Selects the highest-priority feasible goal from GoalStore.
Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Aging: priority multiplier grows linearly with time pending
# After 1h pending: 1.0 + 0.1 = 1.1x
# After 24h pending: 1.0 + 2.4 = 3.4x
AGING_FACTOR_PER_HOUR = 0.1

# Max aging multiplier (clamp) to prevent runaway
MAX_AGING = 4.0

# Deadline urgency (Etap B): a goal nearing/past its deadline is boosted in
# selection, multiplicatively AFTER aging and INDEPENDENTLY clamped so it
# re-orders the feasible set without starving the queue. The deadline field is
# absolute Unix epoch seconds (TZ-safe, reminders convention); None = no
# deadline = multiplier 1.0 (the only behaviour for every goal today).
DEADLINE_URGENT_WINDOW_SEC = 24 * 3600  # within this window -> ramps 1.0 -> ~2.0
DEADLINE_OVERDUE_BOOST = 3.0            # past the deadline -> max urgency
DEADLINE_BOOST_CAP = 3.0               # clamp (aging already clamps at MAX_AGING)


def deadline_mode(env_value: Optional[str]) -> str:
    """Map a raw GOAL_DEADLINE_ENABLED value to off | observe | cutover.

    off     -> multiplier hardwired 1.0 (selection unchanged, default)
    observe -> compute + log the multiplier each deadlined goal WOULD get,
               ranking UNCHANGED
    cutover -> apply the multiplier so selection re-orders by urgency
    """
    v = (env_value or "").strip().lower()
    if v == "observe":
        return "observe"
    if v in ("cutover", "on", "1", "true", "yes", "armed"):
        return "cutover"
    return "off"


def deadline_multiplier(goal, now: float) -> float:
    """Urgency multiplier in [1.0, DEADLINE_BOOST_CAP] from a goal's deadline.

    None deadline -> 1.0. Overdue -> DEADLINE_OVERDUE_BOOST. Within the urgent
    window -> linear ramp from 1.0 (far edge) to ~2.0 (due now). Beyond the
    window -> 1.0. Pure, deterministic (ADR-013), no side effects.
    """
    deadline = getattr(goal, "deadline", None)
    if deadline is None:
        return 1.0
    remaining = deadline - now
    if remaining <= 0:
        mult = DEADLINE_OVERDUE_BOOST
    elif remaining <= DEADLINE_URGENT_WINDOW_SEC:
        mult = 1.0 + (1.0 - remaining / DEADLINE_URGENT_WINDOW_SEC)
    else:
        mult = 1.0
    return min(mult, DEADLINE_BOOST_CAP)

# META goals whose descriptions contain any of these markers require the
# learning window just like explicit LEARNING goals. Previously only "nauk"/
# "learn" were checked, which let meta goals like "eksploracja poza obecną
# domeną wiedzy" bypass the window and hammer the executor with 95% fail rate
# (2026-04-21 glm-5.1 test finding).
META_LEARNING_KEYWORDS = (
    "nauk", "learn", "wiedz", "ekspansj", "ekspl",
    "domen", "horyzont", "struktur", "material",
)


def is_saturation_meta_goal(goal, knowledge_snapshot: Optional[Dict[str, Any]]) -> bool:
    """True if this is a META-learning goal and the library is saturated.

    Used by the planner (D1.5c) to route such goals to FETCH instead of
    LEARN, since there are no materials left to consume locally.
    """
    if goal is None or goal.type.value != "meta":
        return False
    desc_lower = goal.description.lower()
    if not any(kw in desc_lower for kw in META_LEARNING_KEYWORDS):
        return False
    if not knowledge_snapshot:
        return False
    by_status = knowledge_snapshot.get("files_by_status", {})
    new_files = knowledge_snapshot.get("new_files_available", [])
    in_progress = by_status.get("learning", [])
    return not new_files and not in_progress


def is_fetch_handoff_goal(goal) -> bool:
    """True for persisted learning goals created after successful fetch."""
    if goal is None or goal.type.value != "learning":
        return False
    return goal.metadata.get("source") == "fetch_handoff" and bool(
        goal.metadata.get("file_ids") or goal.metadata.get("fetched_file_ids")
    )


class GoalSelector:
    """
    Selects the best goal to work on in this planner cycle.

    Scoring: effective_priority = priority * (1 + aging_factor)
    Feasibility: can this goal make progress right now?
    """

    def __init__(self) -> None:
        # [DEADLINE/*] log dedup: goal_id -> last logged multiplier (rounded
        # to 0.1). The live planner re-scores every goal each ~60s cycle and
        # inside the 24h ramp the multiplier moves a hair every pass; without
        # dedup that is ~1440 near-identical INFO lines/day/goal (the
        # ROLLUP/observe spam class). One line per 0.1 step is still ~10
        # lines across a goal's whole ramp -- signal kept, noise dropped.
        self._deadline_log_marks: Dict[str, float] = {}

    def select_goal(
        self,
        active_goals: list,
        evaluation_metrics: Dict[str, float],
        knowledge_snapshot: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
        world_summary: Optional[Dict[str, Any]] = None,
        off_window_learning_allowed: bool = False,
    ) -> Optional[Any]:
        """
        Select the highest effective-priority feasible goal.

        Args:
            active_goals: Active goals from GoalStore (PENDING + ACTIVE)
            evaluation_metrics: Latest K4 metrics
            knowledge_snapshot: From KnowledgeAnalyzer (optional)
            now: Current time (for testing)

        Returns:
            Selected Goal or None
        """
        if not active_goals:
            return None

        if now is None:
            now = time.time()

        dmode = deadline_mode(os.environ.get("GOAL_DEADLINE_ENABLED"))
        scored = []
        handoff_scored = []
        for goal in active_goals:
            score = self._compute_effective_priority(goal, now, dmode)
            feasible, reason = self._check_feasibility(
                goal, evaluation_metrics, knowledge_snapshot,
                off_window_learning_allowed=off_window_learning_allowed,
            )
            if feasible:
                if is_fetch_handoff_goal(goal):
                    handoff_scored.append((score, goal))
                else:
                    scored.append((score, goal))
            else:
                logger.debug(
                    f"Goal {goal.id} not feasible: {reason}"
                )

        if handoff_scored:
            handoff_scored.sort(key=lambda x: x[0], reverse=True)
            return handoff_scored[0][1]

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def prune_deadline_marks(self, active_ids) -> None:
        """Drop [DEADLINE/*] log-dedup marks for goals no longer active.

        Called from the live ranking pass. Keeps the dedup dict bounded on a
        daemon that runs for months -- marks must not outlive their goals
        (the BeliefStore unbounded-append lesson).
        """
        stale = [gid for gid in self._deadline_log_marks
                 if gid not in active_ids]
        for gid in stale:
            del self._deadline_log_marks[gid]

    def _compute_effective_priority(
        self, goal, now: float, dmode: Optional[str] = None
    ) -> float:
        """
        Compute priority with aging factor (and, when armed, deadline urgency).

        effective_priority = priority * (1 + hours_pending * AGING_FACTOR_PER_HOUR)
        Clamped to max aging of 4.0 to prevent runaway.

        When ``dmode`` is observe/cutover and the goal has a deadline, an urgency
        multiplier (:func:`deadline_multiplier`) is computed. ``observe`` only
        logs it (ranking unchanged); ``cutover`` applies it multiplicatively
        after aging. ``dmode=None`` (the default) reads the flag itself -- a
        caller that forgets to pass the mode gets LIVE flag behaviour, never a
        silently-dead deadline path (the 03-31..07-06 regression: the flag was
        wired only to entrypoints the daemon had abandoned). Callers on hot
        loops pass their once-per-cycle value instead.
        """
        hours_pending = (now - goal.created_at) / 3600.0
        aging = hours_pending * AGING_FACTOR_PER_HOUR
        effective = goal.priority * (1.0 + min(aging, MAX_AGING))

        if dmode is None:
            dmode = deadline_mode(os.environ.get("GOAL_DEADLINE_ENABLED"))

        if dmode != "off" and getattr(goal, "deadline", None) is not None:
            mult = deadline_multiplier(goal, now)
            if mult == 1.0:
                # Deadline pushed back out of the urgency ramp: clear the
                # mark so a later re-entry logs a fresh line (the observe
                # evidence must not be suppressed by a stale mark).
                self._deadline_log_marks.pop(goal.id, None)
            else:
                mark = round(mult, 1)
                if self._deadline_log_marks.get(goal.id) != mark:
                    self._deadline_log_marks[goal.id] = mark
                    logger.info(
                        "[DEADLINE/%s] goal %s urgency x%.2f (remaining %.1fh)",
                        dmode, goal.id, mult, (goal.deadline - now) / 3600.0,
                    )
            if dmode == "cutover":
                effective *= mult

        return effective

    def _check_feasibility(
        self,
        goal,
        evaluation_metrics: Dict[str, float],
        knowledge_snapshot: Optional[Dict[str, Any]],
        off_window_learning_allowed: bool = False,
    ) -> Tuple[bool, str]:
        """
        Check if a goal can make progress right now.

        Returns:
            (is_feasible, reason_if_not)
        """
        goal_type = goal.type.value

        # MAINTENANCE goals: only feasible when metric needs attention
        # progress >= 1.0 means metric is within threshold (satisfied)
        if goal_type == "maintenance":
            if goal.progress >= 1.0:
                return False, "metric within threshold"
            return True, ""

        # META goals: learning-related META goals respect learning window.
        # D1.5d (2026-04-21) originally blocked them when the library was
        # saturated to stop 791 unproductive learn attempts in 72h. D1.5c
        # (2026-04-22) loosens that: saturated META-learning goals stay
        # feasible so the planner can pick FETCH for them — blocking here
        # killed the only autonomous path that pulls new materials from the
        # web. Window check still short-circuits (no learn-family work
        # outside the window, including FETCH per LEARNING_WINDOW_ACTIONS).
        if goal_type == "meta":
            desc_lower = goal.description.lower()
            if any(kw in desc_lower for kw in META_LEARNING_KEYWORDS):
                try:
                    from agent_core.environment.environment_model import is_learning_window
                    if not is_learning_window() and not off_window_learning_allowed:
                        return False, "outside learning window"
                except Exception:
                    pass
            return True, ""

        # USER goals are always feasible
        if goal_type == "user":
            return True, ""

        # LEARNING goals: need materials to learn
        if goal_type == "learning":
            # User-requested goals are always feasible (will trigger FETCH if needed)
            if goal.metadata.get("source") == "conversation":
                return True, ""
            # Outside learning window: learning goals not feasible unless the
            # daily off-window budget still has room (8b rhythm/budget).
            try:
                from agent_core.environment.environment_model import is_learning_window
                if not is_learning_window() and not off_window_learning_allowed:
                    return False, "outside learning window"
            except Exception:
                pass
            if knowledge_snapshot:
                by_status = knowledge_snapshot.get("files_by_status", {})
                new_files = knowledge_snapshot.get("new_files_available", [])
                in_progress = by_status.get("learning", [])
                if not new_files and not in_progress:
                    return False, "no files to learn"
            return True, ""

        return True, ""

    def rank_goals(
        self,
        active_goals: list,
        evaluation_metrics: Dict[str, float],
        now: Optional[float] = None,
    ) -> List[Tuple[float, Any]]:
        """
        Rank all goals by effective priority (for /plan goals display).

        Returns:
            List of (effective_priority, goal) sorted descending
        """
        if now is None:
            now = time.time()

        dmode = deadline_mode(os.environ.get("GOAL_DEADLINE_ENABLED"))
        ranked = []
        for goal in active_goals:
            score = self._compute_effective_priority(goal, now, dmode)
            ranked.append((score, goal))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked
