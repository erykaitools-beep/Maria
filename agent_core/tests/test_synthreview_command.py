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


def test_synthreview_judge_stall_is_not_a_content_verdict(tmp_path):
    """Monday-legibility (Rank 1): a judge TIMEOUT must not read as "0 supported
    -> rejected" -- that misdiagnosis (judge latency mistaken for hallucination)
    is exactly what would corrupt a SYNTH_ENABLED go/no-go call."""
    append_synthesis_review(
        tmp_path / "synthesis_review.jsonl",
        {
            "success": False, "file_id": "synthesis_relatywizm_20260615",
            "topic": "teoria wzglednosci", "source_files": ["wiki_a", "wiki_b"],
            "summary": "Czas plynie wolniej w silnym polu grawitacyjnym.",
            "key_points": ["Dylatacja czasu", "Rownowaznosc masy i energii"],
            "reason": "unfaithful_to_sources",
            # judge timed out: 0/5 with reason=judge_failed (NOT a content ruling)
            "faithfulness": {"ok": False, "reason": "judge_failed",
                             "supported": 0, "unstated": 0, "contradicted": 0,
                             "total": 5},
        },
    )
    bridge = _bridge(tmp_path)
    out = bridge.handlers["synthreview"]("5")
    assert "SEDZIA NIE ZADZIALAL" in out      # stall surfaced as a stall
    assert "judge_failed" in out
    assert "0/5 poparte" not in out           # NOT rendered as a content verdict
    assert "-> ODRZUT" not in out


def test_synthreview_genuine_rejection_still_shows_odrzut(tmp_path):
    """The flip side: a real low-support/contradicted verdict must STILL read as
    a content rejection -- the stall fix must not swallow genuine failures."""
    append_synthesis_review(
        tmp_path / "synthesis_review.jsonl",
        {
            "success": False, "file_id": "synthesis_mit_20260615",
            "topic": "mit", "source_files": ["wiki_a", "wiki_b"],
            "summary": "Twierdzenie nie poparte zrodlami.",
            "key_points": ["Punkt A", "Punkt B"],
            "reason": "unfaithful_to_sources",
            "faithfulness": {"ok": False, "reason": "contradicted",
                             "supported": 2, "unstated": 0, "contradicted": 1,
                             "total": 5},
        },
    )
    bridge = _bridge(tmp_path)
    out = bridge.handlers["synthreview"]("5")
    assert "2/5 poparte" in out
    assert "-> ODRZUT" in out
    assert "SEDZIA NIE ZADZIALAL" not in out
