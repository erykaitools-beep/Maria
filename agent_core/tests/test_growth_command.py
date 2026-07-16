"""Smoke: the /growth (alias /rozwoj) Telegram command surfaces GrowthAwareness.

Before this, GrowthAwareness (K15.3) was write-only -- get_summary_text() had
zero callers, so the operator could never see Maria's growth targets. This wires
the real command table with a fake bridge (god-files split smoke pattern) and
drives the handler against a REAL GrowthAwareness, end to end.
"""

from types import SimpleNamespace

from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)
from agent_core.operator.growth_awareness import GrowthAwareness


class _Bot:
    def __init__(self):
        self.messages = []

    def send_message(self, text, parse_mode=None):
        self.messages.append(text)
        return True


class _Bridge:
    def __init__(self):
        self.handlers = {}
        self.bot = _Bot()

    def register_command(self, command, handler):
        self.handlers[command] = handler


class _FakeKnowledge:
    """Duck-typed KnowledgeAnalyzer feeding a backlog target."""

    def get_knowledge_snapshot(self):
        return {
            "total_files": 30,
            "files_by_status": {
                "completed": ["f"] * 20, "new": ["f"] * 8, "hard_topic": [],
            },
        }


def _ctx(meta_dir, growth_awareness=None):
    core = SimpleNamespace(
        event_logger=SimpleNamespace(
            log_path=str(meta_dir / "homeostasis_events.jsonl")),
        set_synthesis_trigger=lambda cb: None,
    )
    return SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=core,
        planner_core=None, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, model_scheduler=None, sandbox_manager=None,
        growth_awareness=growth_awareness,
    )


def _bridge(meta_dir, growth_awareness=None):
    b = _Bridge()
    _register(b, _ctx(meta_dir, growth_awareness))
    return b


def test_growth_and_rozwoj_registered(tmp_path):
    bridge = _bridge(tmp_path)
    assert "growth" in bridge.handlers
    assert "rozwoj" in bridge.handlers
    # same handler behind both aliases
    assert bridge.handlers["growth"] is bridge.handlers["rozwoj"]


def test_growth_not_wired_message(tmp_path):
    bridge = _bridge(tmp_path, growth_awareness=None)
    out = bridge.handlers["growth"]("")
    assert "Brak GrowthAwareness" in out


def test_growth_surfaces_targets(tmp_path):
    g = GrowthAwareness(targets_path=tmp_path / "growth_targets.jsonl")
    g.set_knowledge_analyzer(_FakeKnowledge())
    g.refresh()

    bridge = _bridge(tmp_path, growth_awareness=g)
    out = bridge.handlers["growth"]("")
    assert "Kierunki rozwoju" in out          # summary header
    assert "plikow czeka" in out              # the backlog target surfaced
    # /rozwoj alias returns the same content
    assert bridge.handlers["rozwoj"]("") == out
