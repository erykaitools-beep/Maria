"""
Tests for personality evolution system:
- TraitCatalog (data integrity)
- ExperienceTracker (recording, counting, flushing)
- TraitEvolver (evolution logic)
- SelfModelBuilder trait_scores (persistence on node)
- Integration (full lifecycle)
"""

import json
import time
import threading
import pytest
from pathlib import Path
from collections import defaultdict

from agent_core.consciousness.trait_catalog import (
    TRAIT_CATALOG,
    EMERGENCE_THRESHOLD,
    DECAY_PER_SESSION,
    SCORE_MIN,
    SCORE_MAX,
    get_all_event_types,
)
from agent_core.consciousness.experience_tracker import ExperienceTracker
from agent_core.consciousness.trait_evolver import TraitEvolver
from agent_core.consciousness.self_model import SelfModelBuilder


# ============================================================
# Mock graph (same pattern as test_consciousness.py)
# ============================================================

class MockGraph:
    """Minimal SemanticGraph mock for testing."""

    def __init__(self):
        self.nodes = {}
        self._counter = 0

    def add_node(self, label, node_type="entity", attributes=None,
                 embedding=None, confidence=1.0, source="unknown"):
        # Dedup by label+type
        for nid, node in self.nodes.items():
            if node.get("label") == label and node.get("type") == node_type:
                return nid

        self._counter += 1
        node_id = f"node:{self._counter:05d}"
        self.nodes[node_id] = {
            "id": node_id,
            "label": label,
            "type": node_type,
            "attributes": attributes or {},
            "confidence": confidence,
            "source": source,
        }
        return node_id

    def add_edge(self, from_id, relation, to_id, weight=1.0,
                 confidence=1.0, source="unknown"):
        if from_id not in self.nodes or to_id not in self.nodes:
            raise ValueError(f"Node not found: {from_id} or {to_id}")

    def find_node_by_label(self, label, node_type=None):
        for node in self.nodes.values():
            if node["label"] == label:
                if node_type is None or node.get("type") == node_type:
                    return node
        return None

    def find_nodes_by_type(self, node_type):
        return [n for n in self.nodes.values() if n.get("type") == node_type]


# ============================================================
# TestTraitCatalog
# ============================================================

class TestTraitCatalog:
    """Tests for trait catalog data integrity."""

    def test_all_traits_have_required_fields(self):
        for name, definition in TRAIT_CATALOG.items():
            assert "description" in definition, f"{name} missing description"
            assert "positive_signals" in definition, f"{name} missing positive_signals"
            assert "negative_signals" in definition, f"{name} missing negative_signals"
            assert "initial_score" in definition, f"{name} missing initial_score"

    def test_initial_scores_in_valid_range(self):
        for name, definition in TRAIT_CATALOG.items():
            score = definition["initial_score"]
            assert SCORE_MIN <= score <= SCORE_MAX, f"{name} initial_score {score} out of range"

    def test_signal_format(self):
        for name, definition in TRAIT_CATALOG.items():
            for event, delta in definition["positive_signals"]:
                assert isinstance(event, str), f"{name} positive signal event not str"
                assert isinstance(delta, (int, float)), f"{name} positive signal delta not number"
                assert delta > 0, f"{name} positive signal delta should be positive"

            for event, delta in definition["negative_signals"]:
                assert isinstance(event, str), f"{name} negative signal event not str"
                assert isinstance(delta, (int, float)), f"{name} negative signal delta not number"
                assert delta < 0, f"{name} negative signal delta should be negative"

    def test_emergence_threshold_valid(self):
        assert 0 < EMERGENCE_THRESHOLD < 1

    def test_decay_valid(self):
        assert 0 < DECAY_PER_SESSION <= 1

    def test_has_minimum_traits(self):
        assert len(TRAIT_CATALOG) >= 5

    def test_get_all_event_types(self):
        events = get_all_event_types()
        assert isinstance(events, set)
        assert len(events) > 0
        assert "conversation_turn" in events
        assert "learning_completed" in events


# ============================================================
# TestExperienceTracker
# ============================================================

class TestExperienceTracker:
    """Tests for experience recording and counting."""

    def test_record_and_count(self):
        tracker = ExperienceTracker(session_id=1)
        tracker.record("conversation_turn")
        tracker.record("conversation_turn")
        tracker.record("learning_completed")

        counts = tracker.get_experience_counts()
        assert counts["conversation_turn"] == 2
        assert counts["learning_completed"] == 1

    def test_get_session_experiences(self):
        tracker = ExperienceTracker(session_id=5)
        tracker.record("test_event", {"key": "value"})

        exps = tracker.get_session_experiences()
        assert len(exps) == 1
        assert exps[0]["event"] == "test_event"
        assert exps[0]["details"] == {"key": "value"}
        assert exps[0]["session"] == 5
        assert "ts" in exps[0]

    def test_get_total_count(self):
        tracker = ExperienceTracker()
        assert tracker.get_total_count() == 0
        tracker.record("a")
        tracker.record("b")
        assert tracker.get_total_count() == 2

    def test_clear_session(self):
        tracker = ExperienceTracker()
        tracker.record("event1")
        tracker.record("event2")
        assert tracker.get_total_count() == 2

        tracker.clear_session()
        assert tracker.get_total_count() == 0
        assert tracker.get_experience_counts() == {}

    def test_empty_counts(self):
        tracker = ExperienceTracker()
        assert tracker.get_experience_counts() == {}

    def test_flush_creates_file(self, tmp_path):
        log_path = tmp_path / "experiences.jsonl"
        tracker = ExperienceTracker(log_path=log_path, session_id=3)
        tracker.record("test_event", {"data": 42})
        tracker.flush()

        assert log_path.exists()
        with open(log_path, "r") as f:
            line = f.readline()
            data = json.loads(line)
            assert data["event"] == "test_event"
            assert data["session"] == 3
            assert data["details"]["data"] == 42

    def test_flush_appends(self, tmp_path):
        log_path = tmp_path / "experiences.jsonl"
        tracker = ExperienceTracker(log_path=log_path)

        tracker.record("event1")
        tracker.flush()
        tracker.clear_session()  # Clear buffer before recording new events
        tracker.record("event2")
        tracker.flush()

        with open(log_path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_flush_empty_buffer(self, tmp_path):
        log_path = tmp_path / "experiences.jsonl"
        tracker = ExperienceTracker(log_path=log_path)
        tracker.flush()  # Should not create file
        assert not log_path.exists()

    def test_thread_safety(self):
        tracker = ExperienceTracker()
        errors = []

        def record_many():
            try:
                for _ in range(100):
                    tracker.record("thread_test")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert tracker.get_total_count() == 400

    def test_record_without_details(self):
        tracker = ExperienceTracker()
        tracker.record("simple_event")
        exps = tracker.get_session_experiences()
        assert exps[0]["details"] == {}


# ============================================================
# TestSelfModelTraitScores
# ============================================================

class TestSelfModelTraitScores:
    """Tests for trait score methods on SelfModelBuilder."""

    def test_get_trait_scores_empty(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        assert builder.get_trait_scores() == {}

    def test_get_trait_scores_after_init(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()
        # Initially no trait_scores (only static traits)
        assert builder.get_trait_scores() == {}

    def test_update_trait_scores(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        scores = {
            "ciekawska": {"score": 0.7, "evidence_count": 10, "last_updated": "2026-02-27"},
            "wytrwala": {"score": 0.3, "evidence_count": 2, "last_updated": "2026-02-27"},
        }
        builder.update_trait_scores(scores)

        # Check stored
        stored = builder.get_trait_scores()
        assert stored["ciekawska"]["score"] == 0.7
        assert stored["wytrwala"]["score"] == 0.3

    def test_update_trait_scores_updates_traits_list(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        scores = {
            "ciekawska": {"score": 0.8, "evidence_count": 10, "last_updated": ""},
            "wytrwala": {"score": 0.2, "evidence_count": 1, "last_updated": ""},
        }
        builder.update_trait_scores(scores)

        traits = builder.get_traits()
        assert "ciekawska" in traits  # >= 0.4
        assert "wytrwala" not in traits  # < 0.4

    def test_add_milestone_experience(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        exp_id = builder.add_milestone_experience({
            "event": "trait_emerged",
            "trait": "wytrwala",
            "score": 0.45,
        })
        assert exp_id is not None
        assert exp_id in graph.nodes

    def test_personality_description_with_scores(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        scores = {
            "ciekawska": {"score": 0.8, "evidence_count": 10, "last_updated": ""},
            "pomocna": {"score": 0.6, "evidence_count": 5, "last_updated": ""},
            "wytrwala": {"score": 0.2, "evidence_count": 1, "last_updated": ""},
        }
        builder.update_trait_scores(scores)

        desc = builder.get_personality_description()
        assert "ciekawska" in desc
        assert "pomocna" in desc
        assert "Cechy aktywne" in desc

    def test_personality_description_no_scores(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        desc = builder.get_personality_description()
        assert "Maria" in desc  # Falls back to basic description

    def test_get_self_summary_includes_trait_scores(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        scores = {"ciekawska": {"score": 0.8, "evidence_count": 5, "last_updated": ""}}
        builder.update_trait_scores(scores)

        summary = builder.get_self_summary()
        assert "trait_scores" in summary
        assert summary["trait_scores"]["ciekawska"]["score"] == 0.8


# ============================================================
# TestTraitEvolver
# ============================================================

class TestTraitEvolver:
    """Tests for trait evolution logic."""

    def _make_evolver(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()
        tracker = ExperienceTracker(session_id=1)
        evolver = TraitEvolver(builder, tracker)
        return evolver, tracker, builder

    def test_evolve_no_experiences(self):
        evolver, tracker, _ = self._make_evolver()
        changes = evolver.evolve()
        assert changes == {}

    def test_evolve_conversation_increases_helpful(self):
        evolver, tracker, builder = self._make_evolver()
        for _ in range(10):
            tracker.record("conversation_turn")

        changes = evolver.evolve()
        assert "pomocna" in changes
        assert changes["pomocna"] > 0

    def test_evolve_learning_increases_curiosity(self):
        evolver, tracker, builder = self._make_evolver()
        for _ in range(5):
            tracker.record("perception_processed")

        changes = evolver.evolve()
        assert "ciekawska" in changes
        assert changes["ciekawska"] > 0

    def test_scores_clamped(self):
        evolver, tracker, builder = self._make_evolver()
        # Massive number of events
        for _ in range(10000):
            tracker.record("conversation_turn")

        evolver.evolve()
        scores = builder.get_trait_scores()
        for name, data in scores.items():
            assert SCORE_MIN <= data["score"] <= SCORE_MAX

    def test_decay_applied(self):
        evolver, tracker, builder = self._make_evolver()

        # Initialize scores manually
        initial = {
            "ciekawska": {"score": 0.8, "evidence_count": 0, "last_updated": ""},
        }
        builder.update_trait_scores(initial)

        # Evolve with no experiences (only decay)
        evolver.evolve()
        scores = builder.get_trait_scores()
        # Score should decrease slightly due to decay
        assert scores["ciekawska"]["score"] < 0.8

    def test_trait_emergence(self):
        evolver, tracker, builder = self._make_evolver()

        # Initialize wytrwala below threshold
        initial = {
            "wytrwala": {"score": 0.38, "evidence_count": 0, "last_updated": ""},
        }
        builder.update_trait_scores(initial)

        # Add experiences that boost wytrwala
        tracker.record("long_session")  # +0.02
        tracker.record("long_session")  # +0.02
        evolver.evolve()

        scores = builder.get_trait_scores()
        assert scores["wytrwala"]["score"] >= EMERGENCE_THRESHOLD

    def test_trait_disappearance(self):
        evolver, tracker, builder = self._make_evolver()

        # Initialize just above threshold
        initial = {
            "spoleczna": {"score": 0.401, "evidence_count": 0, "last_updated": ""},
        }
        builder.update_trait_scores(initial)

        # No social experiences + decay should drop below threshold
        # We need many evolve cycles for decay to accumulate
        for _ in range(50):
            evolver.evolve()

        scores = builder.get_trait_scores()
        assert scores["spoleczna"]["score"] < EMERGENCE_THRESHOLD

    def test_evidence_count_accumulates(self):
        evolver, tracker, builder = self._make_evolver()
        tracker.record("conversation_turn")
        tracker.record("conversation_turn")
        tracker.record("conversation_turn")

        evolver.evolve()
        scores = builder.get_trait_scores()
        # conversation_turn affects pomocna and spoleczna
        assert scores["pomocna"]["evidence_count"] > 0
        assert scores["spoleczna"]["evidence_count"] > 0

    def test_negative_signals(self):
        evolver, tracker, builder = self._make_evolver()

        initial = {
            "systematyczna": {"score": 0.8, "evidence_count": 10, "last_updated": ""},
        }
        builder.update_trait_scores(initial)

        for _ in range(5):
            tracker.record("exam_failed")

        evolver.evolve()
        scores = builder.get_trait_scores()
        # exam_failed has -0.02 per event, 5 events = -0.10
        assert scores["systematyczna"]["score"] < 0.8

    def test_get_personality_description(self):
        evolver, tracker, builder = self._make_evolver()
        for _ in range(10):
            tracker.record("conversation_turn")
        evolver.evolve()

        desc = evolver.get_personality_description()
        assert isinstance(desc, str)
        assert "Maria" in desc

    def test_multiple_evolve_cycles(self):
        evolver, tracker, builder = self._make_evolver()

        # First cycle
        tracker.record("conversation_turn")
        evolver.evolve()
        tracker.clear_session()

        # Second cycle
        tracker.record("learning_completed")
        evolver.evolve()

        scores = builder.get_trait_scores()
        # Both events should have contributed
        assert scores["pomocna"]["evidence_count"] > 0
        assert scores["ciekawska"]["evidence_count"] > 0


# ============================================================
# TestIntegration
# ============================================================

class TestIntegration:
    """Integration tests for full personality lifecycle."""

    def test_full_lifecycle(self, tmp_path):
        """Record experiences -> evolve -> check traits -> persist."""
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        log_path = tmp_path / "exp.jsonl"
        tracker = ExperienceTracker(log_path=log_path, session_id=1)
        evolver = TraitEvolver(builder, tracker)

        # Simulate a session
        for _ in range(20):
            tracker.record("conversation_turn")
        for _ in range(5):
            tracker.record("perception_processed")
        tracker.record("learning_completed")

        # Evolve
        changes = evolver.evolve()
        assert len(changes) > 0

        # Check traits emerged
        traits = builder.get_traits()
        assert "pomocna" in traits or "spoleczna" in traits or "ciekawska" in traits

        # Check scores persisted to node
        scores = builder.get_trait_scores()
        assert len(scores) > 0

        # Flush experiences
        tracker.flush()
        assert log_path.exists()

    def test_persistence_across_sessions(self):
        """Trait scores survive save/restore via dict."""
        graph1 = MockGraph()
        builder1 = SelfModelBuilder(graph1)
        builder1.ensure_self_model()

        tracker = ExperienceTracker(session_id=1)
        evolver = TraitEvolver(builder1, tracker)

        for _ in range(20):
            tracker.record("conversation_turn")
        evolver.evolve()

        # "Save" scores (simulating IdentityStore persistence)
        saved_scores = builder1.get_trait_scores()

        # "New session" - fresh graph
        graph2 = MockGraph()
        builder2 = SelfModelBuilder(graph2)
        builder2.ensure_self_model()

        # Restore
        builder2.update_trait_scores(saved_scores)

        # Verify
        restored = builder2.get_trait_scores()
        for name in saved_scores:
            assert restored[name]["score"] == saved_scores[name]["score"]

    def test_empty_session_only_decays(self):
        """Session with no experiences should only apply decay."""
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()

        initial = {
            "ciekawska": {"score": 0.7, "evidence_count": 5, "last_updated": ""},
        }
        builder.update_trait_scores(initial)

        tracker = ExperienceTracker()
        evolver = TraitEvolver(builder, tracker)

        # No experiences recorded
        changes = evolver.evolve()
        assert changes == {}  # No event-based changes

        scores = builder.get_trait_scores()
        # But decay was applied
        assert scores["ciekawska"]["score"] < 0.7


# ============================================================
# C6 fix — last_updated stamp + record_experience helper
# ============================================================

class TestLastUpdatedOnDecay:
    """Decay shifts the score, so last_updated must reflect that
    (regression: ciekawska/pomocna had last_updated="" forever)."""

    def test_decay_only_pass_refreshes_last_updated(self):
        graph = MockGraph()
        builder = SelfModelBuilder(graph)
        builder.ensure_self_model()
        initial = {
            "ciekawska": {"score": 0.5, "evidence_count": 0, "last_updated": ""},
        }
        builder.update_trait_scores(initial)

        tracker = ExperienceTracker()
        evolver = TraitEvolver(builder, tracker)

        evolver.evolve()
        scores = builder.get_trait_scores()
        # last_updated stamped even with delta=0 (pure decay pass)
        assert scores["ciekawska"]["last_updated"] != ""
        # evidence_count still 0 (no signals)
        assert scores["ciekawska"]["evidence_count"] == 0


class TestRecordExperienceHelper:
    """None-safe wrapper + global consciousness accessor."""

    def test_none_consciousness_is_noop(self):
        from agent_core.consciousness import (
            record_experience, set_global_consciousness,
        )
        # Ensure no leftover global from earlier tests
        set_global_consciousness(None)
        # Should not raise
        record_experience(None, "learning_completed")

    def test_dispatches_to_explicit_consciousness(self):
        from agent_core.consciousness import record_experience
        from agent_core.consciousness.core import ConsciousnessCore
        from agent_core.tests.spec_helpers import specced

        consc = specced(ConsciousnessCore)
        record_experience(consc, "exam_passed", {"score": 0.9})
        consc.record_experience.assert_called_once_with(
            "exam_passed", {"score": 0.9},
        )

    def test_falls_back_to_global_when_no_explicit(self):
        from agent_core.consciousness import (
            record_experience, set_global_consciousness,
        )
        from agent_core.consciousness.core import ConsciousnessCore
        from agent_core.tests.spec_helpers import specced

        global_consc = specced(ConsciousnessCore)
        set_global_consciousness(global_consc)
        try:
            record_experience(None, "conversation_turn", {"source": "web"})
            global_consc.record_experience.assert_called_once_with(
                "conversation_turn", {"source": "web"},
            )
        finally:
            set_global_consciousness(None)

    def test_swallows_exceptions_from_consciousness(self):
        from agent_core.consciousness import record_experience
        from agent_core.consciousness.core import ConsciousnessCore
        from agent_core.tests.spec_helpers import specced

        consc = specced(ConsciousnessCore)
        consc.record_experience.side_effect = RuntimeError("boom")
        # Must not raise — trait scoring is non-critical
        record_experience(consc, "introspection_run")
