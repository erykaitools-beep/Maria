"""Tests for StateReporter (K15.1) - structured self-status reporting."""

from unittest.mock import MagicMock, PropertyMock

import pytest

from agent_core.operator.state_reporter import StateReporter, StateSnapshot
from agent_core.operator.capability_manifest import CapabilityManifest, CapabilityEntry
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.goals.store import GoalStore
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.consciousness.identity_store import IdentityStore
from agent_core.tests.spec_helpers import specced


def _make_manifest(available=5, total=8):
    """Mock CapabilityManifest."""
    m = specced(CapabilityManifest)
    caps = []
    for i in range(total):
        cap = specced(CapabilityEntry)
        cap.available = i < available
        caps.append(cap)
    m.get_capabilities.return_value = caps
    return m


def _make_core(mode="ACTIVE", health=0.85):
    """Mock homeostasis core."""
    c = specced(HomeostasisCore)
    c.get_state.return_value = {"mode": mode, "health_score": health}
    return c


def _make_goal_store(active=3, proposed=1):
    """Mock GoalStore."""
    gs = specced(GoalStore)
    gs.get_active.return_value = [MagicMock() for _ in range(active)]
    gs.get_proposed.return_value = [MagicMock() for _ in range(proposed)]
    return gs


def _make_knowledge(total=20, completed=15):
    """Mock KnowledgeAnalyzer."""
    ka = specced(KnowledgeAnalyzer)
    ka.get_knowledge_snapshot.return_value = {
        "total_files": total,
        "files_by_status": {
            "completed": ["f"] * completed,
            "new": ["f"] * (total - completed),
        },
    }
    return ka


class TestStateSnapshot:
    def test_to_dict(self):
        s = StateSnapshot(
            timestamp=1700000000,
            mode="ACTIVE",
            health_score=0.85,
            capabilities_available=5,
            capabilities_total=8,
            active_goals_count=3,
            proposed_goals_count=1,
            knowledge_files=20,
            knowledge_completed=15,
            recent_actions=[],
            alerts=[],
            uptime_hours=48.0,
        )
        d = s.to_dict()
        assert d["mode"] == "ACTIVE"
        assert d["health_score"] == 0.85
        assert d["capabilities_available"] == 5


class TestStateReporter:
    @pytest.fixture
    def reporter(self):
        r = StateReporter(cache_ttl=0)  # no cache for testing
        r.set_capability_manifest(_make_manifest())
        r.set_homeostasis_core(_make_core())
        r.set_goal_store(_make_goal_store())
        r.set_knowledge_analyzer(_make_knowledge())
        return r

    def test_get_snapshot(self, reporter):
        s = reporter.get_snapshot()
        assert s.mode == "ACTIVE"
        assert s.health_score == 0.85
        assert s.capabilities_available == 5
        assert s.capabilities_total == 8
        assert s.active_goals_count == 3
        assert s.proposed_goals_count == 1
        assert s.knowledge_files == 20
        assert s.knowledge_completed == 15

    def test_snapshot_cache(self):
        r = StateReporter(cache_ttl=999)  # long cache
        r.set_homeostasis_core(_make_core())
        s1 = r.get_snapshot()
        s2 = r.get_snapshot()
        assert s1 is s2  # same object from cache

    def test_get_summary_text(self, reporter):
        text = reporter.get_summary_text()
        assert "ACTIVE" in text
        assert "85%" in text
        assert "5/8" in text
        assert "15/20" in text
        assert "3 aktywnych" in text

    def test_get_compact_context(self, reporter):
        ctx = reporter.get_compact_context()
        assert "mode=ACTIVE" in ctx
        assert "health=85%" in ctx
        assert "caps=5/8" in ctx

    def test_no_subsystems(self):
        r = StateReporter(cache_ttl=0)
        s = r.get_snapshot()
        assert s.mode == "UNKNOWN"
        assert s.health_score == 0.0
        assert s.capabilities_available == 0

    def test_alerts_degraded_mode(self):
        r = StateReporter(cache_ttl=0)
        r.set_homeostasis_core(_make_core(mode="REDUCED", health=0.6))
        s = r.get_snapshot()
        assert len(s.alerts) >= 1
        assert any("REDUCED" in a for a in s.alerts)

    def test_alerts_low_health(self):
        r = StateReporter(cache_ttl=0)
        r.set_homeostasis_core(_make_core(health=0.4))
        s = r.get_snapshot()
        assert any("health" in a.lower() for a in s.alerts)

    def test_alerts_normal_state(self, reporter):
        s = reporter.get_snapshot()
        assert len(s.alerts) == 0

    def test_uptime(self):
        r = StateReporter(cache_ttl=0)
        # Bug #6 guard: real API is get_total_uptime_hours. specced() makes a
        # regression to the phantom get_uptime_hours go red.
        identity = specced(IdentityStore)
        identity.get_total_uptime_hours.return_value = 72.5
        r.set_identity_store(identity)
        r.set_homeostasis_core(_make_core())
        s = r.get_snapshot()
        assert s.uptime_hours == 72.5

    def test_summary_with_uptime_days(self):
        r = StateReporter(cache_ttl=0)
        identity = specced(IdentityStore)
        identity.get_total_uptime_hours.return_value = 72.0
        r.set_identity_store(identity)
        r.set_homeostasis_core(_make_core())
        text = r.get_summary_text()
        assert "3.0 dni" in text

    # -- Proactive reporting --

    def test_should_report_no_previous(self, reporter):
        # No previous report -> no proactive
        assert reporter.should_report_proactively() is False

    def test_should_report_mode_change(self, reporter):
        reporter._last_reported_mode = "ACTIVE"
        reporter._last_reported_health = 0.85

        # Change mode
        core = _make_core(mode="REDUCED", health=0.85)
        reporter.set_homeostasis_core(core)

        assert reporter.should_report_proactively() is True

    def test_should_report_health_drop(self, reporter):
        reporter._last_reported_mode = "ACTIVE"
        reporter._last_reported_health = 0.85

        core = _make_core(mode="ACTIVE", health=0.6)
        reporter.set_homeostasis_core(core)

        assert reporter.should_report_proactively() is True

    def test_proactive_cooldown(self, reporter):
        reporter._last_reported_mode = "ACTIVE"
        reporter._last_reported_health = 0.85

        core = _make_core(mode="REDUCED", health=0.85)
        reporter.set_homeostasis_core(core)

        msg = reporter.get_proactive_message()
        assert msg is not None
        assert "REDUCED" in msg

        # Second call within cooldown -> None
        core2 = _make_core(mode="SLEEP", health=0.5)
        reporter.set_homeostasis_core(core2)
        assert reporter.should_report_proactively() is False

    def test_get_proactive_message_none(self, reporter):
        assert reporter.get_proactive_message() is None
