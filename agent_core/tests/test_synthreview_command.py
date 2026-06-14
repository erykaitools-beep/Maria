"""Smoke: the /synthreview Telegram command (Brick 1 observability surface).

Registers the real command table with a fake bridge (the god-files split smoke
pattern) and drives the handler against a persisted review log -- so the
observe-window evidence path is wired end to end, not just unit-tested.
"""

from types import SimpleNamespace

from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)
from agent_core.synthesis import append_synthesis_review


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


def _ctx(meta_dir):
    core = SimpleNamespace(
        event_logger=SimpleNamespace(
            log_path=str(meta_dir / "homeostasis_events.jsonl")),
        set_synthesis_trigger=lambda cb: None,
    )
    return SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=core,
        planner_core=None, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, model_scheduler=None, sandbox_manager=None,
    )


def _bridge(meta_dir):
    b = _Bridge()
    _register(b, _ctx(meta_dir))
    return b


def test_synthreview_registered_and_empty(tmp_path):
    bridge = _bridge(tmp_path)
    assert "synthreview" in bridge.handlers
    out = bridge.handlers["synthreview"]("")
    assert "Brak recenzji" in out


def test_synthreview_shows_persisted_review(tmp_path):
    append_synthesis_review(
        tmp_path / "synthesis_review.jsonl",
        {
            "success": True, "file_id": "synthesis_kofeina_20260613",
            "topic": "kofeina", "source_files": ["wiki_a", "rss_b"],
            "summary": "Kofeina i sen lacza sie przez adenozyne i jej receptory.",
            "key_points": ["Punkt jeden", "Punkt dwa"],
            "exam": {"executed": True, "passed": True, "score": 0.82},
            "mode": "observe", "would_promote": True, "promoted": False,
            "faithfulness": {"ok": True, "supported": 3, "total": 3,
                             "contradicted": 0, "judge_model": "qwen3:8b"},
        },
    )
    bridge = _bridge(tmp_path)
    out = bridge.handlers["synthreview"]("5")
    assert "kofeina" in out
    assert "synthesis_kofeina_20260613" in out
    assert "Kofeina i sen" in out
    assert "wiernosc" in out  # faithfulness verdict surfaced
