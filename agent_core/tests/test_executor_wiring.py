"""C1 (2026-06-14 audit, Rank 5): the homeostasis self-regulation spine.

For ~4 months HomeostasisCore ran with executor=None, so every corrective
action was computed then silently dropped -- no effect, no trace. These guard
the incremental wiring: corrective actions are now (a) RECORDED to the event
log whether or not anything acts on them, (b) dispatched to a ModuleExecutor
with real/honest handlers, and (c) consolidate_episodic no longer fakes success.
"""
from types import SimpleNamespace

from agent_core.executor.module_executor import ModuleExecutor
from agent_core.homeostasis.actions import ActionType, CorrectiveAction, Urgency
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.event_logger import HomeostasisEventLogger
from agent_core.llm.manager import LLMManager
from agent_core.memory.manager import MemoryManager
from agent_core.modules.homeostasis_module import _wire_executor_modules
from agent_core.teacher.teacher_agent import TeacherAgent
from agent_core.tests.spec_helpers import specced


# -- consolidate_episodic honesty --------------------------------------------

def test_consolidate_episodic_reports_not_implemented_honestly():
    """Must NOT claim success while freeing nothing -- else a wired executor
    reads it as 'memory pressure handled' when nothing changed."""
    result = MemoryManager().consolidate_episodic(target_freed_mb=300)
    assert result["success"] is False
    assert result["reason"] == "not_implemented"
    assert result["freed_mb"] == 0


# -- executor wiring ----------------------------------------------------------

def _wire(teacher=None):
    ex = ModuleExecutor()
    core = SimpleNamespace(_teacher_agent=teacher)
    _wire_executor_modules(ex, core, MemoryManager(), object())
    return ex, core


def test_wire_registers_all_four_targets():
    ex, _ = _wire()
    assert set(ex.get_registered_modules()) == {
        "memory", "learning_engine", "llm", "metacontroller"
    }


def test_memory_consolidate_routes_to_honest_method():
    ex, _ = _wire()
    resp = ex.signal_module("memory", "consolidate_episodic", target_freed_mb=300)
    assert resp["success"] is False
    assert resp["reason"] == "not_implemented"


def test_learning_pause_stops_running_teacher():
    teacher = specced(TeacherAgent)
    ex, _ = _wire(teacher=teacher)
    resp = ex.signal_module("learning_engine", "pause")
    teacher.stop.assert_called_once()
    assert resp["paused"] is True
    assert resp["teacher_stopped"] is True


def test_learning_pause_is_safe_when_no_teacher():
    ex, _ = _wire(teacher=None)
    resp = ex.signal_module("learning_engine", "pause")
    assert resp["paused"] is True
    assert resp["teacher_stopped"] is False


def test_learning_pause_never_raises_on_teacher_error():
    teacher = specced(TeacherAgent)
    teacher.stop.side_effect = RuntimeError("boom")
    ex, _ = _wire(teacher=teacher)
    resp = ex.signal_module("learning_engine", "pause")
    assert resp["paused"] is False
    assert "boom" in resp["error"]


def test_llm_and_metacontroller_are_record_only():
    ex, _ = _wire()
    llm = ex.signal_module("llm", "reduce_batch_size", factor=0.5)
    meta = ex.signal_module("metacontroller", "interrupt_goal_refinement")
    assert llm["effect"] == "recorded_only"
    assert meta["effect"] == "recorded_only"


def test_signals_are_recorded_in_history():
    ex, _ = _wire()
    ex.signal_module("memory", "consolidate_episodic", target_freed_mb=10)
    ex.signal_module("llm", "minimize")
    history = ex.get_signal_history()
    assert len(history) == 2
    assert history[0]["module"] == "memory"
    assert history[1]["signal"] == "minimize"


# -- core visibility: every corrective action is logged + dispatched ----------

def _core_with_mock_logger():
    core = HomeostasisCore(
        memory_manager=specced(MemoryManager),
        llm_manager=specced(LLMManager),
        executor=specced(ModuleExecutor),
    )
    core.event_logger = specced(HomeostasisEventLogger)
    return core


def test_corrective_signal_action_is_logged_and_dispatched():
    core = _core_with_mock_logger()
    action = CorrectiveAction(
        action_type=ActionType.SIGNAL_MODULE,
        target="memory",
        action="consolidate_episodic",
        urgency=Urgency.SOON,
        reason="Memory pressure at 80%",
        parameters={"target_freed_mb": 300},
    )
    core._execute_corrective_actions([action])

    core.event_logger.log_corrective_action.assert_called_once()
    kwargs = core.event_logger.log_corrective_action.call_args.kwargs
    assert kwargs["target"] == "memory"
    assert kwargs["action"] == "consolidate_episodic"
    assert kwargs["urgency"] == "soon"
    core.executor.signal_module.assert_called_once_with(
        "memory", "consolidate_episodic", target_freed_mb=300
    )


def test_trigger_snapshot_action_is_logged_too():
    core = _core_with_mock_logger()
    snapshots = []
    core._trigger_snapshot = lambda: snapshots.append(True)
    action = CorrectiveAction(
        action_type=ActionType.TRIGGER_SNAPSHOT,
        target="homeostasis",
        action="checkpoint",
        urgency=Urgency.SOON,
        reason="ALERT condition detected",
    )
    core._execute_corrective_actions([action])

    core.event_logger.log_corrective_action.assert_called_once()
    assert snapshots == [True]
    # snapshot path must NOT also try to signal a module
    core.executor.signal_module.assert_not_called()
