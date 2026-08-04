"""Regression: Telegram /wf and /env subcommands (2026-06-14 audit, Rank 9).

TelegramBridge delivers args as a STRING (handler(args: str)). The handlers used
to index it as a LIST -- args[0] was the first CHARACTER -- so '/wf list' became
sub='l' and fell through to the usage text. Every documented subcommand was
unreachable; only the bare no-arg view worked. The absence of a string-args test
is exactly why it stayed dead. These drive the REAL command table with a fake
bridge, passing STRINGS like the live bridge does.
"""
from types import SimpleNamespace

from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)


class _Bot:
    def send_message(self, text, parse_mode=None):
        return True


class _Bridge:
    def __init__(self):
        self.handlers = {}
        self.bot = _Bot()

    def register_command(self, command, handler):
        self.handlers[command] = handler


class _FakeWfEngine:
    def list_workflows(self):
        return [{
            "workflow_id": "abcd1234efgh", "name": "demo",
            "status": "running", "progress_pct": 42.0,
        }]


class _FakeEnvMgr:
    def get_status(self):
        return {
            "mode": "default", "auto_detect_enabled": True,
        }

    def list_modes(self):
        return [
            {"mode": "default", "description": "normalny tryb", "active": True},
            {"mode": "focus", "description": "skupienie", "active": False},
        ]

    def switch(self, mode, by=None):
        return True


def _bridge():
    core = SimpleNamespace(
        event_logger=SimpleNamespace(log_path="/tmp/he.jsonl"),
        set_synthesis_trigger=lambda cb: None,
    )
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=core,
        planner_core=None, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, model_scheduler=None, sandbox_manager=None,
        workflow_engine=_FakeWfEngine(), environment_manager=_FakeEnvMgr(),
    )
    b = _Bridge()
    _register(b, ctx)
    return b


# -- /wf ----------------------------------------------------------------------

def test_wf_list_string_reaches_list_branch():
    """THE regression: '/wf list' (string) must hit the list branch, not usage."""
    out = _bridge().handlers["wf"]("list")
    assert "abcd1234" in out
    assert "Usage" not in out


def test_wf_no_arg_defaults_to_list():
    out = _bridge().handlers["wf"]("")
    assert "abcd1234" in out


def test_wf_unknown_subcommand_shows_usage():
    out = _bridge().handlers["wf"]("nonsense")
    assert "Usage" in out


def _bridge_without_engine():
    """Command table wired exactly like the live one, but with no engine."""
    core = SimpleNamespace(
        event_logger=SimpleNamespace(log_path="/tmp/he.jsonl"),
        set_synthesis_trigger=lambda cb: None,
    )
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=core,
        planner_core=None, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, model_scheduler=None, sandbox_manager=None,
        workflow_engine=None, environment_manager=_FakeEnvMgr(),
    )
    b = _Bridge()
    _register(b, ctx)
    return b


def test_wf_reports_closed_room_when_flag_is_off(monkeypatch):
    """A shut valve must not read as a broken subsystem.

    Both states produce workflow_engine=None; only the flag tells them apart,
    and the operator needs to know which one he is looking at.
    """
    monkeypatch.delenv("WORKFLOW_ENABLED", raising=False)
    out = _bridge_without_engine().handlers["wf"]("list")
    assert "WORKFLOW_ENABLED" in out
    assert "zamkniety" in out.lower()


def test_wf_reports_broken_mount_when_flag_is_on(monkeypatch):
    """Flag on but no engine == the mount failed. Say so, point at the logs."""
    monkeypatch.setenv("WORKFLOW_ENABLED", "true")
    out = _bridge_without_engine().handlers["wf"]("list")
    assert "montaz" in out.lower()
    assert "zamkniety" not in out.lower()


def _bridge_with_real_engine(tmp_path):
    """Real WorkflowEngine + real store behind the real command table.

    No engine stand-in here on purpose: the point is to prove the approval
    deadlock is actually broken end to end, and a stand-in would only prove that
    the stand-in flips a flag.
    """
    from agent_core.workflow.workflow_store import WorkflowStore
    from agent_core.workflow.workflow_engine import WorkflowEngine
    from agent_core.workflow.delegation import DelegationManager

    store = WorkflowStore(path=str(tmp_path / "workflows.jsonl"))
    delegation = DelegationManager()
    delegation.disable_k7_gate("approval-deadlock regression, gate not under test")

    class OkRouter:
        def is_available(self, name):
            return True

        def dispatch(self, plan):
            return {"success": True}

    delegation.set_capability_router(OkRouter())
    delegation.set_plan_factory(lambda a, p, g: object())
    engine = WorkflowEngine(store, delegation)

    core = SimpleNamespace(
        event_logger=SimpleNamespace(log_path="/tmp/he.jsonl"),
        set_synthesis_trigger=lambda cb: None,
    )
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=core,
        planner_core=None, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, model_scheduler=None, sandbox_manager=None,
        workflow_engine=engine, environment_manager=_FakeEnvMgr(),
    )
    b = _Bridge()
    _register(b, ctx)
    return b, engine


def test_wf_approve_breaks_the_approval_deadlock(tmp_path):
    """ProgressReporter told operators to run a command that did not exist.

    A step with requires_approval paused the workflow with paused_by=
    'approval_needed'; /wf resume just re-paused on the same step, so the only
    way out was /wf cancel. approve_step() existed engine-side with zero
    production callers. This drives the real command table start to finish.
    """
    from agent_core.workflow.workflow_model import WorkflowStep

    bridge, engine = _bridge_with_real_engine(tmp_path)
    wf = engine.create("gated", "needs sign-off", [
        WorkflowStep(order=0, action="evaluate", params={},
                     description="gated step", requires_approval=True),
    ])
    engine.start(wf.workflow_id)

    engine.advance(wf.workflow_id)
    paused = engine.get_progress(wf.workflow_id)
    assert paused["status"] == "paused"
    assert paused["paused_by"] == "approval_needed"

    short = wf.workflow_id[:8]
    out = bridge.handlers["wf"](f"approve {short} 0")
    assert "Zatwierdzony" in out

    after = engine.get_progress(wf.workflow_id)
    assert after["status"] == "running", "approve did not release the pause"

    engine.advance(wf.workflow_id)
    done = engine.get_progress(wf.workflow_id)
    assert done["completed_steps"] == 1, (
        "approved step still did not run -- deadlock intact")


def test_wf_approve_rejects_a_non_numeric_step(tmp_path):
    bridge, engine = _bridge_with_real_engine(tmp_path)
    from agent_core.workflow.workflow_model import WorkflowStep
    wf = engine.create("gated", "x", [
        WorkflowStep(order=0, action="evaluate", params={}, description="s"),
    ])
    out = bridge.handlers["wf"](f"approve {wf.workflow_id[:8]} pierwszy")
    assert "liczba" in out


def test_wf_usage_mentions_approve():
    """The usage line is the only discovery surface for the subcommand."""
    out = _bridge().handlers["wf"]("nonsense")
    assert "approve" in out


# -- /env ---------------------------------------------------------------------

def test_env_list_string_reaches_list_branch():
    """'/env list' must show modes, not fall through to the no-arg status view."""
    out = _bridge().handlers["env"]("list")
    assert "normalny tryb" in out
    assert "<--" in out  # active marker on default


def test_env_status_default():
    out = _bridge().handlers["env"]("")
    assert "Mode: default" in out


def test_env_switch_multi_token_parses_second_token():
    """'/env switch <mode>' must reach the switch branch and read tokens[1];
    an invalid mode proves it got there (ValueError -> 'Nieznany tryb')."""
    out = _bridge().handlers["env"]("switch zzz-not-a-mode")
    assert "Nieznany tryb" in out
