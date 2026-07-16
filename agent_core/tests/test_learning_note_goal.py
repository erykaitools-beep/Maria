"""Etap 2 (RED zone): autonomous "reason to write" -- on a passed exam Maria
seeds a goal to write a short self-authored learning note, which the FS_WRITE
hand then fulfils. Double-gated OFF (LEARNING_NOTES_ENABLED + fs_write armed) so
it is inert and litter-free by default.

tmp_path isolated; no real meta_data write. Verifies the goal-creation side
(the new "reason"); the write/close side is the existing /drill_fs_write loop.
"""

from types import SimpleNamespace

import pytest

from agent_core.goals.store import GoalStore
from agent_core.planner.planner_core import PlannerCore
from agent_core.modules.teacher_module import TeacherModule


def _module(tmp_path, *, notes_flag, fs_write):
    store = GoalStore(tmp_path / "goals.jsonl")
    planner = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    planner.set_goal_store(store)
    planner._fs_sandbox_root = str(tmp_path / "fs_sandbox")
    planner._fs_write_enabled = fs_write

    mod = TeacherModule()
    mod.ctx = SimpleNamespace(
        planner_core=planner, goal_store=store, proactive_scheduler=None,
    )
    return mod, store


def _note_goals(store):
    return [g for g in store.get_active()
            if (getattr(g, "metadata", None) or {}).get("b2_learning_note")]


def test_flag_off_creates_no_goal(tmp_path, monkeypatch):
    monkeypatch.delenv("LEARNING_NOTES_ENABLED", raising=False)
    mod, store = _module(tmp_path, notes_flag=False, fs_write=True)
    mod._maybe_seed_learning_note("astronomia.txt", 0.85)
    assert _note_goals(store) == []


def test_flag_on_but_fs_write_off_creates_no_goal(tmp_path, monkeypatch):
    """No litter: never create a write-goal the hand cannot fulfil."""
    monkeypatch.setenv("LEARNING_NOTES_ENABLED", "1")
    mod, store = _module(tmp_path, notes_flag=True, fs_write=False)
    mod._maybe_seed_learning_note("astronomia.txt", 0.85)
    assert _note_goals(store) == []


def test_both_armed_creates_note_goal(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_NOTES_ENABLED", "1")
    mod, store = _module(tmp_path, notes_flag=True, fs_write=True)
    mod._maybe_seed_learning_note("uklad_sloneczny.txt", 0.85)

    goals = _note_goals(store)
    assert len(goals) == 1
    g = goals[0]
    # file_exists criterion in the jailed sandbox
    crit = g.success_criteria[0]
    assert crit["type"] == "file_exists"
    assert "fs_sandbox" in crit["path"] and crit["path"].endswith(".txt")
    # self-authored content carries the topic + score
    content = g.metadata["fs_write_content"]
    assert "uklad sloneczny" in content
    assert "85%" in content


def test_dedup_same_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_NOTES_ENABLED", "1")
    mod, store = _module(tmp_path, notes_flag=True, fs_write=True)
    mod._maybe_seed_learning_note("astronomia.txt", 0.8)
    mod._maybe_seed_learning_note("astronomia.txt", 0.9)  # same file again
    assert len(_note_goals(store)) == 1


def test_distinct_files_each_get_a_goal(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_NOTES_ENABLED", "1")
    mod, store = _module(tmp_path, notes_flag=True, fs_write=True)
    mod._maybe_seed_learning_note("astronomia.txt", 0.8)
    mod._maybe_seed_learning_note("fotosynteza.txt", 0.7)
    assert len(_note_goals(store)) == 2


def test_special_char_file_id_goal_closes(tmp_path, monkeypatch):
    """Regression (2nd adversarial review): a file_id with special chars
    (e.g. 'report(final).txt') must NOT produce a criterion path that diverges
    from what sandbox_write actually writes -- else the goal never closes (goal
    litter, violating the anti-litter promise). The filename is now built from
    safe chars only, so the criterion path is a fixed point of the sanitizer."""
    from agent_core.hands.sandbox_writer import _sanitize_filename
    monkeypatch.setenv("LEARNING_NOTES_ENABLED", "1")
    mod, store = _module(tmp_path, notes_flag=True, fs_write=True)
    mod._maybe_seed_learning_note("report(final)!!.txt", 0.91)

    goals = _note_goals(store)
    assert len(goals) == 1
    crit_path = goals[0].success_criteria[0]["path"]
    name = crit_path.rsplit("/", 1)[-1]
    # criterion filename survives the engine's sanitizer unchanged (no divergence)
    sanitized = _sanitize_filename(name)
    if not sanitized.endswith(".txt"):
        sanitized += ".txt"
    assert sanitized == name

    # end-to-end: planner writes it and the goal closes on external evidence
    from agent_core.routing.handlers import close_goal_on_criteria
    planner = mod.ctx.planner_core
    plan = planner._maybe_fs_write({})
    assert plan is not None
    result = planner.executor.execute(plan) or {}
    close_goal_on_criteria(plan, result, store,
                           sandbox_root=plan.action_params.get("sandbox_root"))
    g = store.get(plan.goal_id)
    assert g.status.value == "achieved"
    assert (g.outcome or {}).get("closed_by") == "success_criteria"
