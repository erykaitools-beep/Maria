"""Tests for the autonomous synthesis topic picker (Etap 2b, cegla E).

Pure policy -- no LLM, no daemon. Locks the selection rule (least-recently
synthesized, ties to richer source count), the cooldown, the learning-
window gate, and the restart-safe persisted state.
"""

import json

import pytest

from agent_core.synthesis.picker import (
    DEFAULT_COOLDOWN_SEC,
    decide_synthesis,
    load_state,
    record_pick,
    save_state,
)

DAY = 24 * 3600
NOW = 1_781_000_000.0


def _eligible(*pairs):
    return [{"topic": t, "sources": s} for t, s in pairs]


class TestDecideGates:
    def test_outside_window_skips(self):
        d = decide_synthesis(_eligible(("fizyka", 3)), {}, NOW, in_window=False)
        assert d == {"action": "skip", "reason": "outside_window"}

    def test_cooldown_skips(self):
        state = {"last_run_ts": NOW - 3600, "history": {}}  # 1h ago
        d = decide_synthesis(_eligible(("fizyka", 3)), state, NOW, in_window=True)
        assert d == {"action": "skip", "reason": "cooldown"}

    def test_cooldown_elapsed_allows(self):
        state = {"last_run_ts": NOW - DAY - 1, "history": {}}
        d = decide_synthesis(_eligible(("fizyka", 3)), state, NOW, in_window=True)
        assert d["action"] == "synthesize"

    def test_no_topics_skips(self):
        d = decide_synthesis([], {}, NOW, in_window=True)
        assert d == {"action": "skip", "reason": "no_topics"}


class TestSelection:
    def test_never_synthesized_preferred_over_recent(self):
        # "chemia" was synthesized yesterday; "fizyka" never -> pick fizyka
        state = {"last_run_ts": 0.0, "history": {"chemia": NOW - DAY}}
        d = decide_synthesis(
            _eligible(("chemia", 9), ("fizyka", 2)), state, NOW, in_window=True,
        )
        assert d["topic"] == "fizyka"  # never-touched beats a richer recent one

    def test_least_recently_synthesized_wins(self):
        state = {
            "last_run_ts": 0.0,
            "history": {"chemia": NOW - 10 * DAY, "fizyka": NOW - 2 * DAY},
        }
        d = decide_synthesis(
            _eligible(("chemia", 3), ("fizyka", 3)), state, NOW, in_window=True,
        )
        assert d["topic"] == "chemia"  # older synthesis -> due again first

    def test_tie_breaks_to_more_sources(self):
        # Both never synthesized -> richer topic (more sources) wins
        d = decide_synthesis(
            _eligible(("fizyka", 2), ("biologia", 7)), {}, NOW, in_window=True,
        )
        assert d["topic"] == "biologia"
        assert d["sources"] == 7


class TestStatePersistence:
    def test_record_pick_stamps_run_and_history(self):
        state = record_pick({"last_run_ts": 0.0, "history": {}}, "fizyka", NOW)
        assert state["last_run_ts"] == NOW
        assert state["history"]["fizyka"] == NOW

    def test_record_pick_preserves_other_history(self):
        state = {"last_run_ts": 0.0, "history": {"chemia": NOW - DAY}}
        state = record_pick(state, "fizyka", NOW)
        assert state["history"]["chemia"] == NOW - DAY
        assert state["history"]["fizyka"] == NOW

    def test_roundtrip_survives_save_load(self, tmp_path):
        path = tmp_path / "synthesis_picker_state.json"
        state = record_pick(load_state(path), "fizyka", NOW)
        save_state(path, state)
        # "restart" -- fresh load from disk
        reloaded = load_state(path)
        assert reloaded["last_run_ts"] == NOW
        assert reloaded["history"]["fizyka"] == NOW

    def test_cooldown_survives_restart(self, tmp_path):
        """The whole point: a restart must NOT re-arm the daily budget."""
        path = tmp_path / "state.json"
        save_state(path, record_pick(load_state(path), "fizyka", NOW))
        # Fresh process loads the stamp; 1h later still on cooldown.
        d = decide_synthesis(
            _eligible(("fizyka", 3)), load_state(path), NOW + 3600, in_window=True,
        )
        assert d == {"action": "skip", "reason": "cooldown"}

    def test_corrupt_state_loads_empty(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("nie-json{")
        state = load_state(path)
        assert state == {"last_run_ts": 0.0, "history": {}}
        # And an empty state means a cycle is allowed immediately.
        d = decide_synthesis(_eligible(("fizyka", 3)), state, NOW, in_window=True)
        assert d["action"] == "synthesize"
