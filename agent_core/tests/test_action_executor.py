"""Focused regression tests for ActionExecutor."""

import logging
from unittest.mock import MagicMock, patch

import pytest

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


class TestExpertSaveGuardOnFallbackPath:
    """The no-router fallback save must refuse garbage like the router copy.

    It had NO content check at all. That is how "yyyy..." and "Expert answer"
    reached input/ -- tests drive this copy directly, and it OVERWRITES
    (mode "w"), so each run replaced a corpus file. Measured 2026-07-26: 5 files
    with 29-40 exam attempts each carried nothing but such payloads, and 281 of
    1726 exams (16.3%) ran against them, scoring 0.851 vs 0.794 for the rest --
    metadata questions are easier than real material.

    Dead in production only while a CapabilityRouter is wired. An unguarded
    write path into the learning corpus is a landmine, not a non-issue.
    """

    def _executor(self, tmp_path, monkeypatch):
        from agent_core.routing import handlers

        monkeypatch.setattr(handlers, "EXPERT_INPUT_DIR", tmp_path)
        return ActionExecutor()

    @pytest.mark.parametrize("payload,marker", [
        ("y" * 300, "repeated_char"),
        ("Expert answer", "placeholder"),
        ("Legacy answer", "placeholder"),
        ("Fizyka to nauka o..." * 20, "repeated_phrase"),
    ])
    def test_garbage_is_refused_and_writes_nothing(
        self, tmp_path, monkeypatch, payload, marker
    ):
        executor = self._executor(tmp_path, monkeypatch)
        with pytest.raises(ValueError) as excinfo:
            executor._save_expert_response("fizyka", "pytanie", payload)
        assert marker in str(excinfo.value)
        assert list(tmp_path.glob("expert_*.txt")) == []

    def test_real_answer_is_still_saved(self, tmp_path, monkeypatch):
        executor = self._executor(tmp_path, monkeypatch)
        body = (
            "Fizyka to nauka o materii, energii i ich oddzialywaniach. "
            "Bada zjawiska od mikroskali kwantowej po skale kosmiczne. "
            "Kluczowe galezie to mechanika, termodynamika, elektromagnetyzm "
            "i fizyka kwantowa. Metoda laczy eksperyment z modelem "
            "matematycznym, a teorie sa falsyfikowalne."
        )
        executor._save_expert_response("fizyka", "pytanie", body)
        written = list(tmp_path.glob("expert_fizyka.txt"))
        assert len(written) == 1
        assert "materii" in written[0].read_text(encoding="utf-8")


def test_partial_fetch_with_upstream_errors_is_success(tmp_path):
    """Material arrived -> success, even if a sibling topic hit an upstream 429.

    The uncovered case that let the bug live: the three tests above pin 0+0,
    N+0 and 0+N, but nothing pinned N articles WITH errors. A session asks
    about ~6 topics and pl.wikipedia rate-limits one of them; the old
    `fetched > 0 and errors == 0` condemned the whole batch, auditing a
    productive fetch as a HARD failure (success=False, skipped=False).
    Measured on the live daemon 2026-07-26 (test-written rows excluded): 13
    fetch sessions, 7 audited as hard failures, 4 of those 7 carrying material.
    Session success rate 0.46 -> 0.77. That fed _is_real_failure() -> the
    action_failure_storm self-repair rule, and K12 filed bulletin
    cbb-6435c7bfccbc telling Maria her fetch STRATEGY was broken.
    """
    executor = _fetch_executor()
    executor._transition_bulletin_to_ready = lambda gid: None
    # Real temp paths, not bare MagicMock attributes: _register_fetch_handoff_goal
    # guards with isinstance(value, (str, os.PathLike)) -- and a MagicMock SATISFIES
    # os.PathLike (auto __fspath__), so an unset mock silently sends the knowledge
    # index to a literal "MagicMock/mock.index_path" directory in the repo root
    # instead of being rejected by the guard. Pinning real paths keeps the handoff
    # scan on a genuine (throwaway) index and keeps the repo clean.
    executor._knowledge_analyzer.input_dir = tmp_path / "input"
    executor._knowledge_analyzer.index_path = tmp_path / "knowledge_index.jsonl"
    (tmp_path / "input").mkdir()
    with patch("agent_core.web_source.run_fetch_session") as m:
        m.return_value = {"articles_fetched": 1, "errors": 1,
                          "fetched_files": ["web_wiki_finanse.txt"],
                          "topics_searched": 6}
        result = executor._exec_fetch(create_plan("g1", "fetch", ActionType.FETCH))
    assert result["success"] is True
    assert result.get("skipped") is not True
    # The error count must stay visible to callers that care -- the fix
    # reclassifies the verdict, it does not hide the upstream failure.
    assert result["errors"] == 1
