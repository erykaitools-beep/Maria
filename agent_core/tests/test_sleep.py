"""
Tests for SleepProcessor (new: belief-based) and DreamGenerator (legacy: graph-based).

Covers: NREM phases on real data, dream generation, persistence, integration.
"""

import json
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pytest

from agent_core.consciousness.dream_generator import DreamGenerator
from agent_core.consciousness.sleep_processor import SleepProcessor


@pytest.fixture(autouse=True)
def _isolate_dream_log(tmp_path, monkeypatch):
    """Never let SleepProcessor tests append to the live meta_data/dream_log.jsonl.
    A SleepProcessor built without dream_log_path falls back to DEFAULT_DREAM_LOG;
    redirect that default to a temp file so _save_dreams can't poison production."""
    from agent_core.consciousness import sleep_processor as _sp
    monkeypatch.setattr(_sp, "DEFAULT_DREAM_LOG", tmp_path / "dream_log.jsonl")


# ============================================================
# Mock BeliefStore (mirrors real BeliefStore API)
# ============================================================

@dataclass
class MockBelief:
    belief_id: str
    content: str
    belief_type: str = "observation"
    confidence: float = 0.5
    evidence: list = field(default_factory=list)
    entity: str = "koncept"  # real Belief has .entity (dream curiosity topic)


class MockBeliefStore:
    """Minimal BeliefStore mock for sleep testing (matches real API)."""

    def __init__(self, beliefs: Optional[Dict[str, MockBelief]] = None):
        self._beliefs = beliefs or {}
        self._saved = False
        self._compacted = False

    def get_current(self):
        return list(self._beliefs.values())

    def revise(self, belief_id, new_confidence, **kwargs):
        if belief_id in self._beliefs:
            self._beliefs[belief_id].confidence = new_confidence

    def compact(self):
        self._compacted = True

    def _enforce_cap(self):
        # Simulate pruning beliefs below floor
        to_remove = [bid for bid, b in self._beliefs.items() if b.confidence < 0.05]
        for bid in to_remove:
            del self._beliefs[bid]

    def save(self):
        self._saved = True


def _make_beliefs(n=5):
    """Create N mock beliefs."""
    store = MockBeliefStore()
    for i in range(n):
        b = MockBelief(
            belief_id=f"belief-{i:04d}",
            content=f"Test belief about topic {i} with enough content to dream about",
            confidence=0.3 + (i * 0.1),
            evidence=[("source", f"ref-{i}", 1.0)] if i % 2 == 0 else [],
        )
        store._beliefs[b.belief_id] = b
    return store


# ============================================================
# Legacy graph mock (for DreamGenerator tests)
# ============================================================

class MockGraph:
    """Minimal semantic graph mock for DreamGenerator testing."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self._edge_count = 0

    def add_node(self, label, node_type="entity", attributes=None,
                 embedding=None, confidence=1.0, source="test"):
        node_id = f"node:{len(self.nodes):05d}"
        self.nodes[node_id] = {
            "id": node_id,
            "label": label,
            "type": node_type,
            "attributes": attributes or {},
            "embedding": embedding,
            "confidence": confidence,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "access_count": 0,
            "importance": 0.5,
            "is_outdated": False,
        }
        return node_id

    def add_edge(self, from_id, relation, to_id, weight=1.0,
                 confidence=1.0, source="test"):
        if from_id not in self.nodes or to_id not in self.nodes:
            raise ValueError(f"Node not found: {from_id} or {to_id}")
        edge_key = (from_id, relation, to_id)
        self.edges[edge_key] = {
            "id": f"edge:{self._edge_count:05d}",
            "from": from_id,
            "relation": relation,
            "to": to_id,
            "weight": weight,
            "confidence": confidence,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "access_count": 0,
        }
        self._edge_count += 1


@pytest.fixture
def graph():
    g = MockGraph()
    n1 = g.add_node("homeostasis", node_type="entity")
    n2 = g.add_node("semantic_graph", node_type="entity")
    n3 = g.add_node("learning", node_type="entity")
    n4 = g.add_node("consciousness", node_type="entity")
    n5 = g.add_node("perception", node_type="entity")
    g.add_edge(n1, "related_to", n2, weight=1.0)
    g.add_edge(n2, "part_of", n3, weight=0.8)
    return g


@pytest.fixture
def empty_graph():
    return MockGraph()


@pytest.fixture
def belief_store():
    return _make_beliefs(5)


@pytest.fixture
def empty_belief_store():
    return MockBeliefStore()


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ============================================================
# TestDreamGenerator (legacy graph-based, unchanged)
# ============================================================

class TestDreamGenerator:

    def test_generate_dream_returns_dict(self, graph):
        gen = DreamGenerator(graph)
        dream = gen.generate_dream()
        assert dream is not None
        assert isinstance(dream, dict)

    def test_generate_dream_has_required_fields(self, graph):
        gen = DreamGenerator(graph)
        dream = gen.generate_dream()
        assert "timestamp" in dream
        assert "type" in dream
        assert "content" in dream

    def test_generate_dream_types(self, graph):
        gen = DreamGenerator(graph)
        types_seen = set()
        for _ in range(50):
            dream = gen.generate_dream()
            if dream:
                types_seen.add(dream["type"])
        assert len(types_seen) >= 2

    def test_generate_dream_empty_graph(self, empty_graph):
        gen = DreamGenerator(empty_graph)
        dream = gen.generate_dream()
        assert dream is None

    def test_generate_dream_single_node(self, empty_graph):
        empty_graph.add_node("lonely")
        gen = DreamGenerator(empty_graph)
        dream = gen.generate_dream()
        assert dream is None

    def test_generate_dreams_count(self, graph):
        gen = DreamGenerator(graph)
        dreams = gen.generate_dreams(count=3)
        assert len(dreams) <= 3
        assert len(dreams) > 0

    def test_generate_dream_content_in_polish(self, graph):
        gen = DreamGenerator(graph)
        dream = gen.generate_dream()
        assert dream is not None
        content = dream["content"].lower()
        polish_words = ["sni", "sen", "zbadac", "ciekawe", "polaczenie", "mozliwe", "wiecej"]
        assert any(w in content for w in polish_words)

    def test_save_dreams(self, graph, tmp_dir):
        path = Path(tmp_dir) / "dreams.jsonl"
        gen = DreamGenerator(graph, dream_log_path=path)
        dreams = gen.generate_dreams(count=2)
        gen.save_dreams(dreams, session_id=5)
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == len(dreams)

    def test_load_recent_dreams(self, graph, tmp_dir):
        path = Path(tmp_dir) / "dreams.jsonl"
        gen = DreamGenerator(graph, dream_log_path=path)
        dreams = gen.generate_dreams(count=3)
        gen.save_dreams(dreams, session_id=5)
        loaded = DreamGenerator.load_recent_dreams(limit=10, dream_log_path=path)
        assert len(loaded) == len(dreams)

    def test_load_dreams_empty(self, graph, tmp_dir):
        path = Path(tmp_dir) / "nonexistent.jsonl"
        loaded = DreamGenerator.load_recent_dreams(dream_log_path=path)
        assert loaded == []


# ============================================================
# TestSleepPhases (new: belief-based)
# ============================================================

class TestSleepPhases:

    def test_nrem1_belief_stats(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        result = proc._phase_nrem1()
        assert result["phase"] == "nrem1"
        assert result["beliefs_total"] == 5
        assert "beliefs_avg_confidence" in result
        assert "beliefs_weak" in result
        assert "beliefs_strong" in result

    def test_nrem1_no_belief_store(self):
        proc = SleepProcessor()
        result = proc._phase_nrem1()
        assert result["beliefs_total"] == 0
        assert "beliefs_skipped" in result

    def test_nrem1_knowledge_stats(self, belief_store, tmp_dir):
        ki_path = Path(tmp_dir) / "knowledge_index.jsonl"
        ki_path.write_text(
            '{"id": "f1", "status": "completed"}\n'
            '{"id": "f2", "status": "learning"}\n'
        )
        proc = SleepProcessor(belief_store=belief_store, knowledge_index_path=ki_path)
        result = proc._phase_nrem1()
        assert result["knowledge_total"] == 2
        assert result["knowledge_by_status"]["completed"] == 1

    def test_nrem2_boost_multi_evidence(self, belief_store):
        # Give belief-0002 multiple evidence sources
        b = belief_store._beliefs["belief-0002"]
        b.evidence = [("src1", "ref1", 1.0), ("src2", "ref2", 0.8)]
        old_conf = b.confidence

        proc = SleepProcessor(belief_store=belief_store)
        result = proc._phase_nrem2()
        assert result["beliefs_boosted"] >= 1
        assert b.confidence > old_conf

    def test_nrem2_no_boost_single_evidence(self):
        store = MockBeliefStore({
            "b1": MockBelief("b1", "test", confidence=0.5, evidence=[("a", "b", 1.0)]),
        })
        proc = SleepProcessor(belief_store=store)
        result = proc._phase_nrem2()
        assert result["beliefs_boosted"] == 0

    def test_nrem2_confidence_capped(self):
        store = MockBeliefStore({
            "b1": MockBelief("b1", "test", confidence=0.94,
                             evidence=[("a", "b", 1.0), ("c", "d", 0.5)]),
        })
        proc = SleepProcessor(belief_store=store)
        proc._phase_nrem2()
        assert store._beliefs["b1"].confidence <= 0.95

    def test_nrem3_runs_compact(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        result = proc._phase_nrem3()
        assert result["phase"] == "nrem3"
        assert "beliefs_pruned" in result
        assert belief_store._compacted

    def test_nrem3_no_belief_store(self):
        proc = SleepProcessor()
        result = proc._phase_nrem3()
        assert result["beliefs_pruned"] == 0

    # -- mutate_beliefs decoupling (2026-06-21): REM/NREM1 read, NREM2/3 mutate --

    def test_nrem2_skipped_when_throttled(self, belief_store):
        # mutate_beliefs=False: NREM2 must NOT boost (the 20h throttle protects
        # confidence calibration) even though a belief qualifies.
        b = belief_store._beliefs["belief-0002"]
        b.evidence = [("src1", "ref1", 1.0), ("src2", "ref2", 0.8)]
        old_conf = b.confidence
        proc = SleepProcessor(belief_store=belief_store, mutate_beliefs=False)
        result = proc._phase_nrem2()
        assert result["beliefs_boosted"] == 0
        assert result["skipped"] == "throttled"
        assert b.confidence == old_conf  # untouched

    def test_nrem3_skipped_when_throttled(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store, mutate_beliefs=False)
        result = proc._phase_nrem3()
        assert result["beliefs_pruned"] == 0
        assert result["skipped"] == "throttled"
        assert belief_store._compacted is False  # forgetting did NOT run

    def test_rem_dreams_fire_even_when_throttled(self, belief_store):
        # THE FIX: REM only READS beliefs, so dreams must still fire when belief
        # mutation is throttled -- this was broken for every overnight sleep.
        proc = SleepProcessor(belief_store=belief_store, mutate_beliefs=False)
        result = proc._phase_rem()
        assert result["phase"] == "rem"
        assert result["dreams_generated"] >= 1


# ============================================================
# TestSleepProcessor (full cycle)
# ============================================================

class TestSleepProcessor:

    def test_process_sleep_cycle_returns_report(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store, session_id=5)
        report = proc.process_sleep_cycle()
        assert isinstance(report, dict)
        assert "phases" in report
        assert "dreams" in report
        assert "duration_ms" in report
        assert report["session"] == 5

    def test_all_phases_run(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        report = proc.process_sleep_cycle()
        assert "nrem1" in report["phases"]
        assert "nrem2" in report["phases"]
        assert "nrem3" in report["phases"]
        assert "rem" in report["phases"]
        assert report["phases_completed"] >= 4

    def test_dreams_generated_from_beliefs(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        report = proc.process_sleep_cycle()
        assert isinstance(report["dreams"], list)
        # With 5 beliefs, should generate dreams
        assert len(report["dreams"]) >= 1

    def test_no_dreams_without_beliefs(self):
        proc = SleepProcessor()
        report = proc.process_sleep_cycle()
        assert report["dreams"] == []

    def test_duration_tracked(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        report = proc.process_sleep_cycle()
        assert report["duration_ms"] >= 0

    def test_dream_persistence(self, belief_store, tmp_dir):
        dream_path = Path(tmp_dir) / "dreams.jsonl"
        proc = SleepProcessor(
            belief_store=belief_store,
            session_id=7,
            dream_log_path=dream_path,
        )
        report = proc.process_sleep_cycle()
        if report["dreams"]:
            assert dream_path.exists()
            lines = dream_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == len(report["dreams"])

    def test_empty_belief_store_no_crash(self, empty_belief_store):
        proc = SleepProcessor(belief_store=empty_belief_store)
        report = proc.process_sleep_cycle()
        assert report["dreams"] == []
        assert report["phases_completed"] >= 4


# ============================================================
# TestIntegration
# ============================================================

class TestIntegration:

    def test_import_from_package(self):
        from agent_core.consciousness.dream_generator import DreamGenerator as DG
        from agent_core.consciousness.sleep_processor import SleepProcessor as SP
        assert DG is not None
        assert SP is not None

    def test_multiple_sleep_cycles(self, belief_store, tmp_dir):
        dream_path = Path(tmp_dir) / "dreams.jsonl"
        total_dreams = 0
        for session in range(3):
            proc = SleepProcessor(
                belief_store=belief_store,
                session_id=session,
                dream_log_path=dream_path,
            )
            report = proc.process_sleep_cycle()
            total_dreams += len(report["dreams"])
        assert total_dreams >= 3

    def test_sleep_report_serializable(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        report = proc.process_sleep_cycle()
        json_str = json.dumps(report, ensure_ascii=False)
        assert len(json_str) > 0

    def test_compact_called_in_nrem3(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        proc.process_sleep_cycle()
        assert belief_store._compacted

    def test_dream_has_belief_references(self, belief_store):
        proc = SleepProcessor(belief_store=belief_store)
        report = proc.process_sleep_cycle()
        for dream in report["dreams"]:
            assert "beliefs" in dream
            assert len(dream["beliefs"]) >= 1
            assert dream["beliefs"][0].startswith("belief-")


def test_curiosity_topics_only_topic_entities():
    """2026-06-20 (review MF1): dream curiosity topics come ONLY from TOPIC-type
    entities (clean tag labels); CONCEPT sentences and FILE ids are dropped."""
    from types import SimpleNamespace
    from agent_core.consciousness.sleep_processor import _curiosity_topics
    from agent_core.world_model.belief_model import EntityType

    topic_b = SimpleNamespace(entity="mechanika", entity_type=EntityType.TOPIC)
    sentence_b = SimpleNamespace(
        entity="Dla liczb nieparzystych: c_{n+1} = 3/2 * c_n",
        entity_type=EntityType.CONCEPT,
    )
    file_b = SimpleNamespace(entity="web_rss_x.txt", entity_type=EntityType.FILE)

    assert _curiosity_topics(topic_b, sentence_b, file_b) == ["mechanika"]
    assert _curiosity_topics(sentence_b, file_b) == []
