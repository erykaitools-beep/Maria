"""Etap 1 (RED zone observability): /learning_notes is a READ-ONLY view of the
autonomous learning notes Maria's FS_WRITE hand writes on a passed exam. After
the morning restart it is the operator's only Telegram window onto whether the
armed Etap 2 actually fired -- so it must surface the note files + their backing
goals WITHOUT mutating anything.

Uses the REAL Etap-2 chain (seed -> planner _maybe_fs_write -> executor -> close)
in a tmp sandbox; no real meta_data touch.
"""

import glob
import os
from types import SimpleNamespace

from agent_core.goals.store import GoalStore
from agent_core.planner.planner_core import PlannerCore
from agent_core.modules.teacher_module import TeacherModule
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands,
)


class _FakeBot:
    def __init__(self):
        self.sent = []

    def send_message(self, *a, **k):
        self.sent.append((a, k))


class _FakeBridge:
    def __init__(self):
        self.handlers = {}
        self.bot = _FakeBot()

    def register_command(self, cmd, handler):
        self.handlers[cmd] = handler


class _Ctx:
    """Permissive ctx: set attrs win, anything else reads None so registering
    all ~60 command closures never trips on an unrelated attribute."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):  # only on miss
        return None


def _wire(tmp_path):
    store = GoalStore(tmp_path / "goals.jsonl")
    planner = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    planner.set_goal_store(store)
    sandbox = tmp_path / "fs_sandbox"
    planner._fs_sandbox_root = str(sandbox)
    planner._fs_write_enabled = True

    mod = TeacherModule()
    mod.ctx = SimpleNamespace(
        planner_core=planner, goal_store=store, proactive_scheduler=None,
    )
    bridge = _FakeBridge()
    register_telegram_commands(bridge, _Ctx(planner_core=planner, goal_store=store))
    return bridge, mod, store, planner, sandbox


def _seed_and_write(mod, store, planner, monkeypatch):
    """Real Etap-2 path: seed a note-goal, the FS_WRITE hand writes it, the goal
    closes on file_exists evidence (the same loop /drill_fs_write proves)."""
    from agent_core.routing.handlers import close_goal_on_criteria

    monkeypatch.setenv("LEARNING_NOTES_ENABLED", "1")
    mod._maybe_seed_learning_note("uklad_sloneczny.txt", 0.85)
    plan = planner._maybe_fs_write({})
    assert plan is not None
    result = planner.executor.execute(plan) or {}
    close_goal_on_criteria(
        plan, result, store, sandbox_root=plan.action_params.get("sandbox_root")
    )


def test_command_registered(tmp_path):
    bridge, *_ = _wire(tmp_path)
    assert "learning_notes" in bridge.handlers


def test_empty_is_well_formed_not_error(tmp_path):
    bridge, *_ = _wire(tmp_path)
    out = bridge.handlers["learning_notes"]("")
    assert "Notatki z nauki" in out
    assert "0 domkniete" in out
    assert "pliki na dysku: 0" in out


def test_shows_note_file_goal_and_content(tmp_path, monkeypatch):
    bridge, mod, store, planner, sandbox = _wire(tmp_path)
    _seed_and_write(mod, store, planner, monkeypatch)

    out = bridge.handlers["learning_notes"]("")

    notes = glob.glob(os.path.join(str(sandbox), "maria_note_*.txt"))
    assert len(notes) == 1
    # the actual file on disk is listed
    assert os.path.basename(notes[0]) in out
    # the backing goal is counted as closed
    assert "1 domkniete" in out
    # the self-authored content (topic + score) is shown
    assert "uklad sloneczny" in out
    assert "85%" in out


def test_is_read_only(tmp_path, monkeypatch):
    bridge, mod, store, planner, sandbox = _wire(tmp_path)
    _seed_and_write(mod, store, planner, monkeypatch)
    cmd = bridge.handlers["learning_notes"]

    goals_file = tmp_path / "goals.jsonl"
    before_goals = goals_file.read_bytes() if goals_file.exists() else b""
    before_listing = sorted(os.listdir(str(sandbox)))

    cmd("")
    cmd("")  # twice, to be sure nothing accumulates

    after_goals = goals_file.read_bytes() if goals_file.exists() else b""
    after_listing = sorted(os.listdir(str(sandbox)))
    assert before_goals == after_goals  # no store rewrite
    assert before_listing == after_listing  # no file created/removed
