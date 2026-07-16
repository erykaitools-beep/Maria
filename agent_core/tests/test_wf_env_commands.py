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
            "llm_budget_multiplier": 1.0, "notification_level": "normal",
            "blocked_actions": [],
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
