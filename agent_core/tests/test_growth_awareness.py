"""Tests for GrowthAwareness (K15.3) - limitations as growth targets."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.operator.capability_manifest import CapabilityManifest, CapabilityEntry
from agent_core.operator.honesty_protocol import HonestyProtocol
from agent_core.operator.growth_awareness import GrowthAwareness, GrowthTarget
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.tests.spec_helpers import specced


def _make_manifest(unavailable=None):
    """Mock CapabilityManifest with unavailable capabilities."""
    m = specced(CapabilityManifest)
    caps = []
    for name, reason in (unavailable or []):
        cap = specced(CapabilityEntry, name=name, description=f"Test {name}", reason_unavailable=reason)
        caps.append(cap)
    m.get_unavailable.return_value = caps
    return m


def _make_honesty(action_stats=None):
    """Mock HonestyProtocol with action stats."""
    h = specced(HonestyProtocol)
    h.get_action_stats.return_value = action_stats or {}
    return h


def _make_knowledge(new_count=0, hard_count=0):
    """Mock KnowledgeAnalyzer."""
    ka = specced(KnowledgeAnalyzer)
    ka.get_knowledge_snapshot.return_value = {
        "total_files": 30,
        "files_by_status": {
            "completed": ["f"] * 20,
            "new": ["f"] * new_count,
            "hard_topic": ["f"] * hard_count,
        },
    }
    return ka


class TestGrowthTarget:
    def test_to_dict(self):
        t = GrowthTarget(
            target_id="cap-effector",
            category="capability",
            description="Niedostepna: OpenClaw",
            current_state="Brak gateway",
            desired_state="OpenClaw connected",
            estimated_cost="medium",
            estimated_benefit="high",
            source="capability_manifest",
            created_at=1700000000,
        )
        d = t.to_dict()
        assert d["target_id"] == "cap-effector"
        assert d["category"] == "capability"
        assert d["status"] == "identified"

    def test_default_status(self):
        t = GrowthTarget(
            target_id="x", category="x", description="x",
            current_state="x", desired_state="x",
            estimated_cost="low", estimated_benefit="low", source="x",
        )
        assert t.status == "identified"


class TestGrowthAwareness:
    @pytest.fixture
    def targets_file(self, tmp_path):
        return tmp_path / "growth_targets.jsonl"

    @pytest.fixture
    def growth(self, targets_file):
        return GrowthAwareness(targets_path=targets_file)

    # -- refresh & targets from capabilities --

    def test_refresh_from_capabilities(self, growth):
        growth.set_capability_manifest(_make_manifest([
            ("effector", "brak: openclaw_client"),
            ("experiment", "brak: experiment_system"),
        ]))

        count = growth.refresh()
        assert count >= 2  # 2 capabilities + hardware
        targets = growth.get_targets(status="identified")
        names = [t.target_id for t in targets]
        assert "cap-effector" in names
        assert "cap-experiment" in names

    def test_refresh_no_duplicates(self, growth):
        growth.set_capability_manifest(_make_manifest([
            ("effector", "brak"),
        ]))

        count1 = growth.refresh()
        count2 = growth.refresh()
        assert count1 > 0
        assert count2 == 0  # no new targets on second refresh

    def test_refresh_updates_existing_in_place(self, growth):
        """Re-refresh must UPDATE descriptive fields of an existing target,
        not freeze them at first-scan values (the bug: append-only refresh
        discarded the freshly-generated target because the id already existed)."""
        ka = _make_knowledge(new_count=6)
        growth.set_knowledge_analyzer(ka)
        growth.refresh()
        backlog = [t for t in growth.get_targets() if t.target_id == "kn-backlog"]
        assert len(backlog) == 1
        assert "6" in backlog[0].description

        # Backlog grew to 9 -> a re-refresh must reflect the new number.
        ka.get_knowledge_snapshot.return_value = {
            "total_files": 30,
            "files_by_status": {
                "completed": ["f"] * 20, "new": ["f"] * 9, "hard_topic": [],
            },
        }
        new = growth.refresh()
        assert new == 0  # same target_id -> not counted as new
        backlog = [t for t in growth.get_targets() if t.target_id == "kn-backlog"]
        assert len(backlog) == 1            # not duplicated
        assert "9" in backlog[0].description  # number refreshed in place
        assert "6" not in backlog[0].description

    def test_refresh_preserves_operator_status(self, growth):
        """Operator-set status (deferred/achieved) must survive a refresh;
        only the descriptive fields update."""
        ka = _make_knowledge(new_count=6)
        growth.set_knowledge_analyzer(ka)
        growth.refresh()
        assert growth.mark_deferred("kn-backlog") is True

        ka.get_knowledge_snapshot.return_value = {
            "total_files": 30,
            "files_by_status": {
                "completed": ["f"] * 20, "new": ["f"] * 12, "hard_topic": [],
            },
        }
        growth.refresh()
        t = [g for g in growth.get_targets() if g.target_id == "kn-backlog"][0]
        assert t.status == "deferred"     # preserved, NOT reset to identified
        assert "12" in t.description      # but description refreshed

    def test_refresh_copies_hardware_globals(self, growth):
        """Hardware targets are module globals -- refresh must copy them, never
        mutate the shared instances (the old code stamped created_at on the
        global, leaking across GrowthAwareness instances)."""
        from agent_core.operator import growth_awareness as ga_mod
        growth.refresh()
        hw_persisted = [t for t in growth.get_targets() if t.target_id == "hw-gpu"][0]
        hw_global = ga_mod._HARDWARE_TARGETS[0]
        assert hw_persisted is not hw_global   # a copy, not the shared global
        assert hw_global.created_at == 0.0     # global never stamped
        assert hw_persisted.created_at > 0     # the copy got a timestamp

    # -- targets from reliability --

    def test_targets_from_low_confidence(self, growth):
        growth.set_honesty_protocol(_make_honesty({
            "fetch": {"count": 10, "success": 3, "failed": 7},
            "learn": {"count": 10, "success": 9, "failed": 1},
        }))

        count = growth.refresh()
        targets = growth.get_targets(status="identified")
        reliability = [t for t in targets if t.category == "reliability"]
        assert len(reliability) == 1
        assert "fetch" in reliability[0].description

    def test_no_target_for_good_reliability(self, growth):
        growth.set_honesty_protocol(_make_honesty({
            "learn": {"count": 10, "success": 9, "failed": 1},
        }))

        growth.refresh()
        targets = growth.get_targets(status="identified")
        reliability = [t for t in targets if t.category == "reliability"]
        assert len(reliability) == 0

    def test_no_target_for_few_attempts(self, growth):
        growth.set_honesty_protocol(_make_honesty({
            "fetch": {"count": 2, "success": 0, "failed": 2},
        }))

        growth.refresh()
        reliability = [t for t in growth.get_targets() if t.category == "reliability"]
        assert len(reliability) == 0  # not enough data

    # -- targets from knowledge --

    def test_targets_from_knowledge_backlog(self, growth):
        growth.set_knowledge_analyzer(_make_knowledge(new_count=8))

        growth.refresh()
        knowledge = [t for t in growth.get_targets() if t.category == "knowledge"]
        assert any("plikow czeka" in t.description for t in knowledge)

    def test_targets_from_hard_topics(self, growth):
        growth.set_knowledge_analyzer(_make_knowledge(hard_count=3))

        growth.refresh()
        knowledge = [t for t in growth.get_targets() if t.category == "knowledge"]
        assert any("trudnych" in t.description for t in knowledge)

    def test_no_knowledge_target_few_new(self, growth):
        growth.set_knowledge_analyzer(_make_knowledge(new_count=2))

        growth.refresh()
        knowledge = [t for t in growth.get_targets() if t.category == "knowledge"]
        backlog = [t for t in knowledge if "czeka" in t.description]
        assert len(backlog) == 0  # only 2, not worth a target

    # -- hardware targets --

    def test_hardware_targets_included(self, growth):
        growth.refresh()
        resource = [t for t in growth.get_targets() if t.category == "resource"]
        assert len(resource) >= 1
        assert any("GPU" in t.description for t in resource)

    # -- get_top_targets --

    def test_top_targets_sorted(self, growth):
        growth.set_capability_manifest(_make_manifest([
            ("effector", "brak"),
        ]))
        growth.set_honesty_protocol(_make_honesty({
            "fetch": {"count": 10, "success": 2, "failed": 8},
        }))

        growth.refresh()
        top = growth.get_top_targets(3)
        assert len(top) <= 3
        # High benefit / low cost should come first
        if len(top) >= 2:
            assert growth._score_target(top[0]) >= growth._score_target(top[1])

    # -- mark_achieved / mark_deferred --

    def test_mark_achieved(self, growth):
        growth.refresh()  # gets hardware targets at minimum
        targets = growth.get_targets()
        assert len(targets) > 0

        tid = targets[0].target_id
        assert growth.mark_achieved(tid) is True
        assert growth.get_targets(status="achieved")[0].target_id == tid

    def test_mark_deferred(self, growth):
        growth.refresh()
        tid = growth.get_targets()[0].target_id
        assert growth.mark_deferred(tid) is True
        assert growth.get_targets(status="deferred")[0].target_id == tid

    def test_mark_nonexistent(self, growth):
        assert growth.mark_achieved("nonexistent") is False

    # -- persistence --

    def test_persistence_save_load(self, targets_file):
        g1 = GrowthAwareness(targets_path=targets_file)
        g1.refresh()
        count1 = len(g1.get_targets())
        assert count1 > 0

        # New instance should load from file
        g2 = GrowthAwareness(targets_path=targets_file)
        targets = g2.get_targets()
        assert len(targets) == count1

    # -- get_summary_text --

    def test_summary_text(self, growth):
        growth.set_capability_manifest(_make_manifest([
            ("effector", "brak"),
        ]))
        growth.refresh()

        text = growth.get_summary_text()
        assert "Kierunki rozwoju" in text
        assert "capability" in text or "resource" in text

    def test_summary_no_targets(self, targets_file):
        g = GrowthAwareness(targets_path=targets_file)
        text = g.get_summary_text()
        assert "Nie zidentyfikowalam" in text

    # -- to_dict --

    def test_to_dict(self, growth):
        growth.set_capability_manifest(_make_manifest([("effector", "brak")]))
        growth.refresh()
        data = growth.to_dict()
        assert "targets" in data
        assert "total" in data
        assert data["total"] > 0
        assert data["identified"] > 0

    # -- _score_target --

    def test_score_high_benefit_low_cost(self):
        t = GrowthTarget(
            target_id="x", category="x", description="x",
            current_state="x", desired_state="x",
            estimated_cost="low", estimated_benefit="high", source="x",
        )
        score = GrowthAwareness._score_target(t)
        assert score == 3.0  # 3/1

    def test_score_low_benefit_high_cost(self):
        t = GrowthTarget(
            target_id="x", category="x", description="x",
            current_state="x", desired_state="x",
            estimated_cost="high", estimated_benefit="low", source="x",
        )
        score = GrowthAwareness._score_target(t)
        assert score < 1.0  # 1/3
