"""Operator-first pause preserves admitted work without autonomous reasoning."""
from types import SimpleNamespace

import pytest

from agent_core.homeostasis.core import HomeostasisCore
from agent_core.planner.planner_core import PlannerCore
from agent_core.runtime_profile import background_reasoning_enabled
from agent_core.tracing.episode import current_episode_id, get_current_trace


@pytest.mark.parametrize('value, expected', [(None, True), ('1', True), ('on', True),
                                             ('0', False), ('false', False)])
def test_background_reasoning_default_and_overrides(monkeypatch, value, expected):
    monkeypatch.delenv('MARIA_BACKGROUND_REASONING', raising=False)
    if value is not None:
        monkeypatch.setenv('MARIA_BACKGROUND_REASONING', value)
    assert background_reasoning_enabled() is expected


def test_invalid_pause_flag_fails_explicitly(monkeypatch):
    monkeypatch.setenv('MARIA_BACKGROUND_REASONING', 'typo')
    with pytest.raises(ValueError, match='MARIA_BACKGROUND_REASONING'):
        background_reasoning_enabled()


def test_paused_planner_records_pause_before_any_autonomous_work(tmp_path, monkeypatch):
    monkeypatch.setenv('MARIA_BACKGROUND_REASONING', '0')
    planner = PlannerCore(state_path=tmp_path / 'state.json',
                          decisions_path=tmp_path / 'decisions.jsonl')
    monkeypatch.setattr(planner, '_check_guard', lambda: (True, []))
    monkeypatch.setattr(planner, '_maybe_fs_write', lambda _: None)
    for method in ('_strategic_replan_due', '_gather_context', '_select_ranked_goals'):
        monkeypatch.setattr(planner, method, lambda *a: pytest.fail('autonomous work admitted'))
    from agent_core.homeostasis.state_model import SystemState, Mode
    events = []
    planner._homeostasis_core = SimpleNamespace(
        get_state=lambda: SystemState(mode=Mode.ACTIVE, health_score=1.0, last_mode_change_time=0), push_external_event=events.append,
    )
    assert planner.run_cycle(60) is None
    assert len(events) == 1
    assert events[0].payload['background_reasoning_paused'] is True
    assert planner.get_status()['background_reasoning_enabled'] is False
    assert planner._current_trace.result_summary == 'background_reasoning_paused'
    assert current_episode_id() == ''
    assert get_current_trace() is None


@pytest.mark.parametrize('guard_refuses', [False, True])
def test_paused_runtime_preserves_real_file_action_and_existing_guard(tmp_path, monkeypatch, guard_refuses):
    from agent_core.tests.test_ready_action_priority import (
        test_ready_file_task_precedes_replanning_and_reflection_but_keeps_guard,
    )
    monkeypatch.setenv('MARIA_BACKGROUND_REASONING', '0')
    test_ready_file_task_precedes_replanning_and_reflection_but_keeps_guard(
        tmp_path, monkeypatch, guard_refuses,
    )


def test_approved_effector_precedes_pause(tmp_path, monkeypatch):
    monkeypatch.setenv('MARIA_BACKGROUND_REASONING', '0')
    planner = PlannerCore(state_path=tmp_path / 'state.json',
                          decisions_path=tmp_path / 'decisions.jsonl')
    monkeypatch.setattr(planner, '_check_guard', lambda: (True, []))
    admitted, expected, seen = object(), object(), []
    planner._approval_queue = SimpleNamespace(
        expire_stale=lambda: seen.append('expired'), get_approved_ready=lambda: admitted,
    )
    def execute(request, trace):
        assert request is admitted
        seen.append('executed')
        return expected
    monkeypatch.setattr(planner, '_execute_approved_effector', execute)
    monkeypatch.setattr(planner, '_maybe_fs_write', lambda _: pytest.fail('continued past approved action'))
    assert planner.run_cycle(60) is expected
    assert seen == ['expired', 'executed']


def test_teacher_fallback_cannot_restart_autonomous_learning(monkeypatch):
    monkeypatch.setenv('MARIA_BACKGROUND_REASONING', '0')
    core = HomeostasisCore.__new__(HomeostasisCore)
    core._teacher_agent = object()
    core._check_teacher_trigger()


def test_telegram_is_explicitly_disabled_independent_of_reasoning(monkeypatch):
    from agent_core.runtime_profile import telegram_integration_enabled
    monkeypatch.delenv('MARIA_TELEGRAM_INTEGRATION', raising=False)
    assert telegram_integration_enabled()
    monkeypatch.setenv('MARIA_TELEGRAM_INTEGRATION', '0')
    assert not telegram_integration_enabled()
    monkeypatch.setenv('MARIA_TELEGRAM_INTEGRATION', 'typo')
    with pytest.raises(ValueError, match='MARIA_TELEGRAM_INTEGRATION'):
        telegram_integration_enabled()
