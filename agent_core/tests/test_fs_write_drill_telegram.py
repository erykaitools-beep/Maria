"""Telegram wiring for the /drill_fs_write drill (RED zone, B2 first AUTONOMOUS
hand): seed -> planner writes -> goal closes on external evidence, end to end
through register_telegram_commands. tmp_path isolated (no real meta_data write).

Unlike Rung 2 (/drill_outbox -> /approve_note, operator-gated each write), this
proves the AUTONOMOUS loop: Maria generates the plan, writes the file, and the
goal closes because the file exists on disk -- no operator approval in the loop.
The write is jailed to a tmp sandbox here; FS_WRITE_ENABLED is flipped on only
for the drill run and restored after.
"""

from pathlib import Path
from types import SimpleNamespace

from agent_core.goals.store import GoalStore
from agent_core.planner.planner_core import PlannerCore
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register_telegram_commands,
)


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, text, parse_mode=None):
        self.messages.append(text)
        return True


class FakeBridge:
    def __init__(self):
        self.handlers = {}
        self.bot = FakeBot()

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _harness(tmp_path):
    sandbox_root = str(tmp_path / "fs_sandbox")
    store = GoalStore(tmp_path / "goals.jsonl")
    planner = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    planner.set_goal_store(store)
    # Jail the write to tmp so the drill never touches the real meta_data/.
    planner._fs_sandbox_root = sandbox_root

    ctx = SimpleNamespace(
        planner_core=planner,
        goal_store=store,
        # attrs other registered handlers may read at call time
        outbox_store=None, homeostasis_core=None, telegram_notifier=None,
        knowledge_analyzer=None, bulletin_store=None, maria_conductor=None,
        self_perception=None, repair_task_creator=None,
    )
    bridge = FakeBridge()
    _register_telegram_commands(bridge, ctx)
    return bridge, ctx, store, Path(sandbox_root)


def test_drill_fs_write_registered(tmp_path):
    bridge, *_ = _harness(tmp_path)
    assert "drill_fs_write" in bridge.handlers


def test_drill_writes_file_and_closes_goal(tmp_path):
    bridge, ctx, store, sandbox_dir = _harness(tmp_path)

    resp = bridge.handlers["drill_fs_write"]("")

    # 1. Maria wrote a fresh file into the jailed sandbox.
    files = list(sandbox_dir.glob("maria_drill_*.txt"))
    assert len(files) == 1, f"expected one drill file, got {files}"
    assert files[0].is_file()
    assert files[0].stat().st_size > 0

    # 2. The goal closed on EXTERNAL evidence (the file), not a self-report.
    achieved = [g for g in store.get_all() if g.status.value == "achieved"]
    assert len(achieved) == 1
    outcome = achieved[0].outcome or {}
    assert outcome.get("closed_by") == "success_criteria"

    # 3. The response reports success.
    assert "OK" in resp
    assert "domkniety" in resp.lower() or "domkniety" in resp


def test_drill_jailed_to_sandbox(tmp_path):
    """The written file must be inside the tmp sandbox, never the real tree."""
    bridge, ctx, store, sandbox_dir = _harness(tmp_path)
    resp = bridge.handlers["drill_fs_write"]("")
    files = list(sandbox_dir.glob("maria_drill_*.txt"))
    assert files, resp
    # path is contained in the jailed sandbox
    assert sandbox_dir.resolve() in files[0].resolve().parents


def test_flag_restored_after_drill(tmp_path):
    """FS_WRITE_ENABLED is flipped on only for the run -> drill leaves it OFF."""
    bridge, ctx, store, sandbox_dir = _harness(tmp_path)
    assert ctx.planner_core._fs_write_enabled is False  # default OFF
    bridge.handlers["drill_fs_write"]("")
    assert ctx.planner_core._fs_write_enabled is False  # restored


def test_flag_restored_even_if_planner_raises(tmp_path, monkeypatch):
    """Regression (adversarial review 2026-06-21): the FS_WRITE flag must be
    restored even if the protected block raises -- the flip+restore lives in a
    try/finally so a transient error can't leave autonomous writes armed."""
    import pytest
    bridge, ctx, store, sandbox_dir = _harness(tmp_path)
    planner = ctx.planner_core
    assert planner._fs_write_enabled is False
    monkeypatch.setattr(
        planner, "_maybe_fs_write",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        bridge.handlers["drill_fs_write"]("")
    assert planner._fs_write_enabled is False  # finally restored despite the raise


def test_missing_subsystems_is_graceful(tmp_path):
    """No planner/goal store -> a clear message, not a crash."""
    ctx = SimpleNamespace(
        planner_core=None, goal_store=None,
        outbox_store=None, homeostasis_core=None, telegram_notifier=None,
        knowledge_analyzer=None, bulletin_store=None, maria_conductor=None,
        self_perception=None, repair_task_creator=None,
    )
    bridge = FakeBridge()
    _register_telegram_commands(bridge, ctx)
    resp = bridge.handlers["drill_fs_write"]("")
    assert "Brak" in resp
