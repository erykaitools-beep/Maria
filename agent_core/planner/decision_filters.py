"""Shared filters for interpreting planner_decisions.jsonl records.

Several self-analysis sensors read ``planner_decisions.jsonl`` to compute action
distributions and success rates:

- K12 ``state_collector._collect_action_distribution``
- K13 ``strategic_context._collect_action_pattern`` / ``identity_profile``
- operator ``honesty_protocol._get_action_stats``

Two kinds of records must NOT be mistaken for real, attempted actions:

1. **Idle markers** -- written by ``PlannerCore._log_skip`` when the planner wakes
   with nothing to do (outside the learning window, guard-blocked, or no ready
   goals). ``action_type`` is ``"skip"`` (or ``"noop"``). These represent *rest*,
   not work. Most ticks fall here by design (learning runs only inside windows).

2. **Skipped attempts** -- a real action the executor declined before doing any
   work (outside window, no material). ``result["skipped"]`` is ``True``. The
   executor never attempted it, so it is neither a success nor a failure.

Counting either as a "0% success action" is what drove the multi-week
"skip dominates / 0% success" bulletin storm (T-LEARN-003): the self-analysis
brain kept "discovering" a phantom failure and filing improvement bulletins,
meta-goals and experiments against planner *rest*. Route every sensor through
these helpers so they all measure the same reality -- attempted actions only.
"""

from typing import Any, Dict

# Planner idle markers (PlannerCore._log_skip). Not real actions.
IDLE_ACTION_TYPES = frozenset({"skip", "noop"})


def is_idle_marker(record: Dict[str, Any]) -> bool:
    """True if the record is a planner idle marker rather than a real action."""
    return record.get("action_type") in IDLE_ACTION_TYPES


def is_skipped_attempt(record: Dict[str, Any]) -> bool:
    """True if the record is a real action the executor declined (not attempted)."""
    result = record.get("result")
    return bool(result.get("skipped")) if isinstance(result, dict) else False


def is_real_action(record: Dict[str, Any]) -> bool:
    """True if the executor actually attempted this action.

    Excludes planner idle markers (rest) and skipped attempts (declined before
    any work). Use this to decide whether a record belongs in an action
    distribution or a success-rate computation.
    """
    return not is_idle_marker(record) and not is_skipped_attempt(record)
