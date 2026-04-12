"""Tests for HonestyProtocol (K15.2) - evidence-based capability claims."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.operator.honesty_protocol import HonestyProtocol, HonestyCheck


def _write_decisions(path: Path, records: list):
    """Write planner decisions JSONL for testing."""
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _make_decision(action_type: str, success: bool, status: str = None):
    """Create a minimal planner decision record."""
    return {
        "action_type": action_type,
        "status": status or ("completed" if success else "failed"),
        "result": {"success": success},
        "timestamp": 1700000000,
    }


class TestHonestyCheck:
    def test_fields(self):
        check = HonestyCheck(
            action="learn",
            verified=True,
            confidence=0.9,
            evidence_source="test",
            attempts=10,
            successes=9,
            qualifier="",
        )
        assert check.action == "learn"
        assert check.verified is True
        assert check.confidence == 0.9


class TestHonestyProtocol:
    @pytest.fixture
    def tmp_decisions(self, tmp_path):
        return tmp_path / "planner_decisions.jsonl"

    @pytest.fixture
    def protocol(self, tmp_decisions):
        return HonestyProtocol(decisions_path=tmp_decisions)

    # -- check_capability_claim --

    def test_no_handler_no_history(self, protocol):
        manifest = MagicMock()
        manifest.can_do.return_value = False
        protocol.set_capability_manifest(manifest)

        check = protocol.check_capability_claim("effector")
        assert check.verified is False
        assert check.confidence == 0.0
        assert check.qualifier == "nie wiem"

    def test_handler_no_history(self, protocol):
        manifest = MagicMock()
        manifest.can_do.return_value = True
        protocol.set_capability_manifest(manifest)

        check = protocol.check_capability_claim("learn")
        assert check.verified is True
        assert check.confidence == 0.6  # registered but untested
        assert check.qualifier == "prawdopodobnie"

    def test_handler_with_good_history(self, protocol, tmp_decisions):
        manifest = MagicMock()
        manifest.can_do.return_value = True
        protocol.set_capability_manifest(manifest)

        records = [_make_decision("learn", True) for _ in range(10)]
        _write_decisions(tmp_decisions, records)

        check = protocol.check_capability_claim("learn")
        assert check.verified is True
        assert check.confidence >= 0.9
        assert check.qualifier == ""  # high confidence
        assert check.attempts == 10
        assert check.successes == 10

    def test_handler_with_bad_history(self, protocol, tmp_decisions):
        manifest = MagicMock()
        manifest.can_do.return_value = True
        protocol.set_capability_manifest(manifest)

        records = [_make_decision("fetch", False) for _ in range(10)]
        _write_decisions(tmp_decisions, records)

        check = protocol.check_capability_claim("fetch")
        assert check.confidence < 0.5
        assert check.qualifier in ("nie jestem pewna, ale", "nie wiem")

    def test_mixed_history(self, protocol, tmp_decisions):
        manifest = MagicMock()
        manifest.can_do.return_value = True
        protocol.set_capability_manifest(manifest)

        records = (
            [_make_decision("exam", True) for _ in range(7)]
            + [_make_decision("exam", False) for _ in range(3)]
        )
        _write_decisions(tmp_decisions, records)

        check = protocol.check_capability_claim("exam")
        assert 0.5 <= check.confidence <= 0.85
        assert check.attempts == 10
        assert check.successes == 7

    def test_no_decisions_file(self, protocol):
        manifest = MagicMock()
        manifest.can_do.return_value = True
        protocol.set_capability_manifest(manifest)

        check = protocol.check_capability_claim("learn")
        assert check.confidence == 0.6  # untested

    def test_cache_is_used(self, protocol, tmp_decisions):
        _write_decisions(tmp_decisions, [_make_decision("learn", True)])
        stats1 = protocol.get_action_stats()
        stats2 = protocol.get_action_stats()
        assert stats1 is stats2  # same object from cache

    # -- get_evidence_based_confidence --

    def test_evidence_based_confidence(self, protocol, tmp_decisions):
        manifest = MagicMock()
        manifest.can_do.return_value = True
        protocol.set_capability_manifest(manifest)

        records = [_make_decision("learn", True) for _ in range(15)]
        _write_decisions(tmp_decisions, records)

        conf = protocol.get_evidence_based_confidence("learn")
        assert conf >= 0.9

    def test_evidence_based_confidence_no_handler(self, protocol):
        manifest = MagicMock()
        manifest.can_do.return_value = False
        protocol.set_capability_manifest(manifest)

        conf = protocol.get_evidence_based_confidence("nonexistent")
        assert conf == 0.0

    # -- qualify_statement --

    def test_qualify_high_confidence(self, protocol):
        result = protocol.qualify_statement("Umiem sie uczyc", 0.95)
        assert result == "Umiem sie uczyc"

    def test_qualify_medium_confidence(self, protocol):
        result = protocol.qualify_statement("Potrafie pobierac dane", 0.65)
        assert "Prawdopodobnie" in result

    def test_qualify_low_confidence(self, protocol):
        result = protocol.qualify_statement("Moge to zrobic", 0.3)
        assert "nie jestem pewna" in result.lower()

    def test_qualify_zero_confidence(self, protocol):
        result = protocol.qualify_statement("Cos tam", 0.0)
        assert result == "Nie wiem."

    # -- get_summary --

    def test_summary_with_history(self, protocol, tmp_decisions):
        records = (
            [_make_decision("learn", True) for _ in range(8)]
            + [_make_decision("learn", False) for _ in range(2)]
            + [_make_decision("exam", True) for _ in range(5)]
        )
        _write_decisions(tmp_decisions, records)

        manifest = MagicMock()
        manifest.can_do.return_value = True
        protocol.set_capability_manifest(manifest)

        summary = protocol.get_summary()
        assert "learn" in summary
        assert "exam" in summary
        assert "8/10" in summary or "80%" in summary

    def test_summary_no_history(self, protocol):
        summary = protocol.get_summary()
        assert "Brak historii" in summary

    # -- _compute_confidence --

    def test_compute_no_handler(self):
        assert HonestyProtocol._compute_confidence(False, 0, 0) == 0.0

    def test_compute_no_history(self):
        assert HonestyProtocol._compute_confidence(True, 0, 0) == 0.6

    def test_compute_perfect_history(self):
        conf = HonestyProtocol._compute_confidence(True, 20, 20)
        assert conf >= 0.95

    def test_compute_zero_success(self):
        conf = HonestyProtocol._compute_confidence(True, 20, 0)
        assert conf < 0.1

    def test_compute_few_attempts_blends(self):
        # With few attempts, should blend toward 0.6 prior
        conf_3 = HonestyProtocol._compute_confidence(True, 3, 3)
        conf_20 = HonestyProtocol._compute_confidence(True, 20, 20)
        assert conf_3 < conf_20  # more data = more confident

    # -- _qualifier_for_confidence --

    def test_qualifier_high(self):
        assert HonestyProtocol._qualifier_for_confidence(0.9) == ""

    def test_qualifier_medium(self):
        assert HonestyProtocol._qualifier_for_confidence(0.65) == "prawdopodobnie"

    def test_qualifier_low(self):
        assert "pewna" in HonestyProtocol._qualifier_for_confidence(0.3)

    def test_qualifier_none(self):
        assert HonestyProtocol._qualifier_for_confidence(0.0) == "nie wiem"
