"""Focused regression tests for ActionExecutor."""

import logging
from unittest.mock import MagicMock, patch

from agent_core.autonomy.incident_memory import IncidentMemory
from agent_core.planner.action_executor import ActionExecutor
from agent_core.planner.planner_model import ActionType, create_plan
from agent_core.tests.spec_helpers import specced


def test_incident_memory_failure_logs_warning(caplog):
    """B5 regression: incident-memory failure logs and does not re-raise."""
    executor = ActionExecutor()
    incident_memory = specced(IncidentMemory)
    incident_memory.record_incident.side_effect = RuntimeError("synthetic")
    executor.set_incident_memory(incident_memory)
    plan = create_plan("g1", "learn", ActionType.LEARN)

    caplog.set_level(logging.WARNING, logger="agent_core.planner.action_executor")
    result = executor.execute(plan)

    assert result["success"] is False
    incident_memory.record_incident.assert_called_once()
    assert "failed to record incident" in caplog.text
    assert "synthetic" in caplog.text


# --- "idle != failed": exhausted-material learn must not count as a failure ----

def _learn_executor(stats):
    """ActionExecutor with a teacher returning `stats`, window gate forced open."""
    executor = ActionExecutor()
    teacher = MagicMock()
    teacher.run_session.return_value = {"stats": stats}
    executor.set_teacher_agent(teacher)
    executor._is_outside_learning_window = lambda plan: False
    return executor


def test_idle_learn_marked_skipped_not_failed():
    """0 chunks + idle_reason (no fresh material) -> skipped, never a failure.

    Root cause of the learn-confidence collapse (=0.23 -> K9 'Spadek pewnosci'):
    once the corpus is fully learned, the topicless learn yields 0 chunks and was
    recorded success=False (a failure) despite being genuine planner *rest*.
    """
    executor = _learn_executor({
        "chunks_learned": 0,
        "idle_reason": "filtered_out_all_candidates",
        "filtered_out_count": 12,
    })
    plan = create_plan("g1", "learn", ActionType.LEARN)
    result = executor._exec_learn(plan)
    assert result["success"] is False
    assert result["skipped"] is True
    assert result["idle_reason"] == "filtered_out_all_candidates"


def test_failed_learn_without_idle_stays_failure():
    """0 chunks WITHOUT an idle_reason (a real teacher error) stays a failure."""
    executor = _learn_executor({"chunks_learned": 0})
    plan = create_plan("g1", "learn", ActionType.LEARN)
    result = executor._exec_learn(plan)
    assert result["success"] is False
    assert result.get("skipped") is not True


def test_productive_learn_is_success_not_skipped():
    executor = _learn_executor({"chunks_learned": 3})
    plan = create_plan("g1", "learn", ActionType.LEARN)
    result = executor._exec_learn(plan)
    assert result["success"] is True
    assert result.get("skipped") is not True


# --- yield-aware fetch: a 0-article fetch is idle rest, not a phantom win -------

def _fetch_executor():
    executor = ActionExecutor()
    executor._knowledge_analyzer = MagicMock()
    executor._is_outside_learning_window = lambda plan: False
    return executor


def test_dry_fetch_is_skipped_not_success():
    """0 articles + 0 errors = nothing NEW to fetch -> skipped (idle), not success.
    Stops the saturation fetch pump being falsely reinforced for dry fetches."""
    executor = _fetch_executor()
    with patch("agent_core.web_source.run_fetch_session") as m:
        m.return_value = {"articles_fetched": 0, "errors": 0,
                          "fetched_files": [], "topics_searched": 5}
        result = executor._exec_fetch(create_plan("g1", "fetch", ActionType.FETCH))
    assert result["success"] is False
    assert result["skipped"] is True


def test_productive_fetch_is_success():
    executor = _fetch_executor()
    executor._transition_bulletin_to_ready = lambda gid: None
    with patch("agent_core.web_source.run_fetch_session") as m:
        m.return_value = {"articles_fetched": 2, "errors": 0,
                          "fetched_files": [], "topics_searched": 5}
        result = executor._exec_fetch(create_plan("g1", "fetch", ActionType.FETCH))
    assert result["success"] is True
    assert result.get("skipped") is not True


def test_fetch_zero_articles_with_errors_is_failure_not_skipped():
    """0 articles WITH errors is a real failure (network/config), not idle rest."""
    executor = _fetch_executor()
    with patch("agent_core.web_source.run_fetch_session") as m:
        m.return_value = {"articles_fetched": 0, "errors": 3,
                          "fetched_files": [], "topics_searched": 5}
        result = executor._exec_fetch(create_plan("g1", "fetch", ActionType.FETCH))
    assert result["success"] is False
    assert result.get("skipped") is not True
