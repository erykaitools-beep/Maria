"""Focused regression tests for ActionExecutor."""

import logging
from unittest.mock import MagicMock

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
