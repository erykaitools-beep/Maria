"""Parent-goal rollup -- sub-goal tree completion (Digital Human Etap B).

Deterministic, zero-LLM aggregation of CHILD goal completion up to a PARENT.
The ``parent_goal_id`` field (revived by Etap B) lets a long-horizon project
goal own sub-goals; this module is the reader that makes the tree *alive*: when
children reach a terminal status, the parent advances.

Rules (rule-based, ADR-013 -- no LLM, no network, pure status aggregation):
  - progress: ``parent.progress = (children in a terminal status) / (children)``
  - completion fires only when ALL children are terminal:
      * every child ACHIEVED                 -> parent ACHIEVED
        (reason ``all_children_achieved``)
      * any child FAILED/ABANDONED/CANCELLED -> parent FAILED
        (reason ``child_failed:<id>``) under ``ANY_FAIL_FAILS_PARENT`` (default)

Boundaries that keep this from colliding with existing machinery:
  - MAINTENANCE parents are SKIPPED: they never auto-achieve and reset each
    session, so the live ``goal-maint-health <- ram/cpu`` seed tree must not be
    auto-completed by rollup (that would regress homeostasis).
  - Rollup keys ONLY on children already in ``TERMINAL_STATUSES`` -- which were
    closed by their own verified path (e.g. the 2026-05-31 independent-exam
    closer). It NEVER re-evaluates a leaf's ``success_criteria`` or exam record,
    so it cannot weaken the verified-"DONE" guarantee.
  - One level per call: a grandchild rolls into its child this tick, the child
    into the grandparent next tick. Idempotent (a terminal parent is excluded)
    and order-independent (each call reads a fresh child-status snapshot).

Modes (operator flag ``GOAL_ROLLUP_ENABLED``, resolved by :func:`rollup_mode`):
  off     -> the planner phase does not run
  observe -> :func:`compute_rollups` + log intended transitions, mutate NOTHING
  cutover -> :func:`apply_rollup` writes through ``store.update_status`` /
             ``update_progress`` (so ``_mark_dirty`` fires and the change
             survives a restart)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from agent_core.goals.goal_model import (
    Goal,
    GoalStatus,
    GoalType,
    TERMINAL_STATUSES,
)

# Open question #1 (operator-tunable, one-line change): when SOME children fail
# and the rest are terminal, does the parent FAIL (True, the default -- a
# project with a failed step is not "achieved") or still ACHIEVE on
# all-children-terminal regardless of outcome (False)?
ANY_FAIL_FAILS_PARENT = True

# Float tolerance for "progress unchanged" so a re-run is a true no-op.
_PROGRESS_EPS = 1e-9


def rollup_mode(env_value: Optional[str]) -> str:
    """Map a raw ``GOAL_ROLLUP_ENABLED`` value to ``off`` | ``observe`` | ``cutover``.

    Unknown / empty / explicit-off values resolve to ``off`` (safe default), so
    a typo never silently arms the writer.
    """
    v = (env_value or "").strip().lower()
    if v == "observe":
        return "observe"
    if v in ("cutover", "on", "1", "true", "yes", "armed"):
        return "cutover"
    return "off"


@dataclass
class RollupDecision:
    """One intended parent transition (the unit of both observe and cutover)."""

    parent_id: str
    ratio: float                          # terminal children / total children
    target_status: Optional[GoalStatus]   # ACHIEVED / FAILED, or None = progress-only
    reason: str
    children_total: int
    children_achieved: int
    children_failed: int

    @property
    def outcome(self) -> dict:
        """Audit blob recorded on the parent when a terminal rollup is applied."""
        return {
            "closed_by": "rollup",
            "children_total": self.children_total,
            "children_achieved": self.children_achieved,
            "children_failed": self.children_failed,
        }


def _decide(parent: Goal, children: List[Goal]) -> Optional[RollupDecision]:
    """Pure: the intended transition for one parent, or None if nothing changes."""
    total = len(children)
    if total == 0:
        return None
    terminal = [c for c in children if c.status in TERMINAL_STATUSES]
    achieved = [c for c in children if c.status == GoalStatus.ACHIEVED]
    failed = [c for c in terminal if c.status != GoalStatus.ACHIEVED]
    ratio = len(terminal) / total

    target: Optional[GoalStatus] = None
    reason = "partial_progress"
    if len(terminal) == total:
        if failed and ANY_FAIL_FAILS_PARENT:
            target = GoalStatus.FAILED
            reason = f"child_failed:{failed[0].id}"
        else:
            target = GoalStatus.ACHIEVED
            reason = "all_children_achieved"

    # No-op suppression: nothing to do when there is no terminal transition AND
    # the progress fraction is already what the parent records.
    if target is None and abs(ratio - parent.progress) < _PROGRESS_EPS:
        return None

    return RollupDecision(
        parent_id=parent.id,
        ratio=ratio,
        target_status=target,
        reason=reason,
        children_total=total,
        children_achieved=len(achieved),
        children_failed=len(failed),
    )


def compute_rollups(store) -> List[RollupDecision]:
    """Scan every parent-with-children, return the intended transitions. No writes.

    A parent is a candidate when it is non-terminal, not MAINTENANCE, and has at
    least one child. Reads only the in-memory index via the store's public
    getters, so it is safe to call from a planner-tick phase.
    """
    decisions: List[RollupDecision] = []
    for parent in store.get_all():
        if parent.status in TERMINAL_STATUSES:
            continue
        if parent.type == GoalType.MAINTENANCE:
            continue
        children = store.get_children(parent.id)
        if not children:
            continue
        decision = _decide(parent, children)
        if decision is not None:
            decisions.append(decision)
    return decisions


def apply_rollup(store, decision: RollupDecision) -> None:
    """Apply one decision through the store's audited setters (``_mark_dirty`` fires).

    Caller is responsible for ``store.save()`` afterwards (the planner phase saves
    once per cycle).
    """
    if decision.target_status in (GoalStatus.ACHIEVED, GoalStatus.FAILED):
        # Status FIRST: update_progress auto-ACHIEVES an ACTIVE goal at progress
        # >= 1.0, which would wrongly ACHIEVE a parent we mean to FAIL (all
        # children terminal, ratio == 1.0). Setting a terminal status first makes
        # the subsequent progress write inert (auto-achieve guards on ACTIVE).
        store.update_status(
            decision.parent_id, decision.target_status, decision.reason, "goal_rollup",
        )
        store.update_progress(decision.parent_id, decision.ratio)
        store.set_outcome(decision.parent_id, decision.outcome)
    else:
        store.update_progress(decision.parent_id, decision.ratio)
