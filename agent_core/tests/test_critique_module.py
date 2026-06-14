"""Tests for CritiqueModule REPL commands."""

import time
from unittest.mock import MagicMock, patch

import pytest

from agent_core.modules.critique_module import CritiqueModule
from agent_core.critic.critique_model import CritiqueReport, CritiqueFinding
from agent_core.critic import CriticAgent
from agent_core.registry.shared_context import SharedContext
from agent_core.tests.spec_helpers import specced


def _make_finding(**overrides):
    defaults = {
        "finding_id": "f-001",
        "category": "OVERCONFIDENT",
        "severity": "WARNING",
        "topic": "fizyka kwantowa",
        "topic_normalized": "fizyka_kwantowa",
        "description": "High confidence but weak evidence",
        "suggested_action": "verify",
        "evidence": {},
        "evidence_sources": ("beliefs",),
        "belief_ids": ("b-1",),
        "confidence_delta": -0.1,
        "dedupe_key": "overconfident::fizyka_kwantowa",
        "recommended_goal_title": "Zweryfikuj: fizyka kwantowa",
        "metadata": {},
    }
    defaults.update(overrides)
    return CritiqueFinding(**defaults)


def _make_report(**overrides):
    defaults = {
        "trigger": "manual",
        "findings": [_make_finding()],
        "goals_created": ["goal-1"],
        "duration_ms": 42.0,
        "findings_total": 3,
        "findings_by_category": {"OVERCONFIDENT": 1},
        "findings_by_severity": {"WARNING": 1},
        "suppressed_duplicates": 2,
    }
    defaults.update(overrides)
    return CritiqueReport(**defaults)


class TestCritiqueModule:
    def _make_module(self, critic=None):
        mod = CritiqueModule()
        ctx = specced(SharedContext, critic_agent=critic)
        mod.init(ctx)
        return mod

    def test_init(self):
        mod = self._make_module()
        assert mod.name == "critique"

    def test_get_commands(self):
        mod = self._make_module()
        cmds = mod.get_commands()
        assert len(cmds) == 1
        assert cmds[0].name == "/critique"

    def test_no_critic_shows_message(self, capsys):
        mod = self._make_module(critic=None)
        mod._cmd_critique([])
        out = capsys.readouterr().out
        assert "Nie zainicjalizowano" in out

    def test_no_report_shows_message(self, capsys):
        critic = specced(CriticAgent)
        critic.get_last_report.return_value = None
        mod = self._make_module(critic=critic)
        mod._cmd_critique([])
        out = capsys.readouterr().out
        assert "Brak raportow" in out

    def test_show_last_report(self, capsys):
        critic = specced(CriticAgent)
        critic.get_last_report.return_value = _make_report()
        mod = self._make_module(critic=critic)
        mod._cmd_critique([])
        out = capsys.readouterr().out
        assert "RAPORT KRYTYKI" in out
        assert "OVERCONFIDENT" in out
        assert "fizyka kwantowa" in out
        assert "verify" in out

    def test_show_report_with_error(self, capsys):
        critic = specced(CriticAgent)
        critic.get_last_report.return_value = _make_report(error="test error")
        mod = self._make_module(critic=critic)
        mod._cmd_critique([])
        out = capsys.readouterr().out
        assert "BLAD: test error" in out

    def test_show_report_with_summary(self, capsys):
        critic = specced(CriticAgent)
        critic.get_last_report.return_value = _make_report(
            llm_summary="Wiedza wymaga weryfikacji"
        )
        mod = self._make_module(critic=critic)
        mod._cmd_critique([])
        out = capsys.readouterr().out
        assert "Wiedza wymaga weryfikacji" in out

    def test_run_critique(self, capsys):
        critic = specced(CriticAgent)
        report = _make_report()
        critic.run_critique.return_value = report
        mod = self._make_module(critic=critic)
        mod._cmd_critique(["run"])
        out = capsys.readouterr().out
        assert "Gotowe" in out
        assert "1 findings" in out
        critic.run_critique.assert_called_once_with(trigger="manual")

    def test_run_critique_error(self, capsys):
        critic = specced(CriticAgent)
        critic.run_critique.return_value = _make_report(error="boom", findings=[])
        mod = self._make_module(critic=critic)
        mod._cmd_critique(["run"])
        out = capsys.readouterr().out
        assert "Blad: boom" in out

    def test_status(self, capsys):
        critic = specced(CriticAgent)
        critic.get_status.return_value = {
            "available": True,
            "last_critique_ts": time.time() - 3600,
            "cooldown_sec": 28800,
            "last_findings": 2,
            "last_findings_total": 5,
            "last_goals_created": 1,
        }
        mod = self._make_module(critic=critic)
        mod._cmd_critique(["status"])
        out = capsys.readouterr().out
        assert "Available" in out
        assert "True" in out
        assert "8h" in out

    def test_status_never_run(self, capsys):
        critic = specced(CriticAgent)
        critic.get_status.return_value = {
            "available": True,
            "last_critique_ts": 0,
            "cooldown_sec": 28800,
            "last_findings": 0,
            "last_findings_total": 0,
            "last_goals_created": 0,
        }
        mod = self._make_module(critic=critic)
        mod._cmd_critique(["status"])
        out = capsys.readouterr().out
        assert "nigdy" in out

    def test_findings_detail(self, capsys):
        critic = specced(CriticAgent)
        critic.get_last_report.return_value = _make_report()
        mod = self._make_module(critic=critic)
        mod._cmd_critique(["findings"])
        out = capsys.readouterr().out
        assert "FINDINGS DETAIL" in out
        assert "fizyka kwantowa" in out
        assert "b-1" in out
        assert "-0.10" in out
        assert "Zweryfikuj" in out

    def test_findings_empty(self, capsys):
        critic = specced(CriticAgent)
        critic.get_last_report.return_value = None
        mod = self._make_module(critic=critic)
        mod._cmd_critique(["findings"])
        out = capsys.readouterr().out
        assert "Brak findings" in out

    def test_cleanup(self):
        mod = self._make_module()
        mod.cleanup()  # should not raise
