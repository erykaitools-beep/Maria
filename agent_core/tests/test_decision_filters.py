"""Tests for planner_decisions record filters (T-LEARN-003)."""

from agent_core.planner.decision_filters import (
    IDLE_ACTION_TYPES,
    is_idle_marker,
    is_skipped_attempt,
    is_real_action,
)


# -- Idle markers (PlannerCore._log_skip) --------------------------------

def test_skip_marker_is_idle():
    rec = {"action_type": "skip", "status": "no_goals", "result": {"reasons": []}}
    assert is_idle_marker(rec) is True
    assert is_real_action(rec) is False


def test_noop_marker_is_idle():
    rec = {"action_type": "noop", "status": "guard_blocked"}
    assert is_idle_marker(rec) is True
    assert is_real_action(rec) is False


def test_real_action_is_not_idle():
    rec = {"action_type": "learn", "status": "completed", "result": {"success": True}}
    assert is_idle_marker(rec) is False
    assert is_real_action(rec) is True


def test_idle_types_frozen():
    assert IDLE_ACTION_TYPES == frozenset({"skip", "noop"})


# -- Skipped attempts (executor declined before any work) ----------------

def test_skipped_attempt_detected():
    rec = {"action_type": "exam", "status": "failed",
           "result": {"success": False, "skipped": True}}
    assert is_skipped_attempt(rec) is True
    # A skipped attempt is neither idle nor a real (attempted) action.
    assert is_idle_marker(rec) is False
    assert is_real_action(rec) is False


def test_failed_attempt_is_real():
    # Genuinely attempted and failed -- this IS a real action.
    rec = {"action_type": "exam", "status": "failed",
           "result": {"success": False}}
    assert is_skipped_attempt(rec) is False
    assert is_real_action(rec) is True


def test_successful_action_is_real():
    rec = {"action_type": "fetch", "status": "completed",
           "result": {"success": True}}
    assert is_real_action(rec) is True


# -- Robustness against malformed records --------------------------------

def test_missing_result_is_not_skipped():
    rec = {"action_type": "learn", "status": "completed"}
    assert is_skipped_attempt(rec) is False
    assert is_real_action(rec) is True


def test_non_dict_result_is_safe():
    rec = {"action_type": "learn", "result": None}
    assert is_skipped_attempt(rec) is False
    assert is_real_action(rec) is True


def test_empty_record_is_real_action_safe():
    # No action_type -> not idle; no skipped flag -> treated as real.
    assert is_idle_marker({}) is False
    assert is_skipped_attempt({}) is False
    assert is_real_action({}) is True
