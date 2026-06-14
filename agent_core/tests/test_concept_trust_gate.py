"""Concept trust-gate (2026-06-13).

The CONCEPT belief path historically stamped FACT from ANY passing exam --
including the student grading its own answers -- while the FILE path was
hardened (2026-06-01) to admit FACT only from an INDEPENDENT grader. This
closes that asymmetry behind CONCEPT_TRUST_GATE (off/observe/armed) and adds a
read-only census for observe-first telemetry.

Tests use REAL BeliefStore + BeliefBuilder + tmp JSONL sources (no mocks): a
MagicMock store would silently swallow exactly the wiring this gate depends on
(related_entities vs source_file key match, exam grader_independent flag).
"""

import json

import pytest

from agent_core.world_model.belief_builder import BeliefBuilder
from agent_core.world_model.belief_model import (
    BeliefSource, BeliefType, EntityType, create_belief,
)
from agent_core.world_model.belief_store import BeliefStore


def _write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _clean_gate_env(monkeypatch):
    # .env on the dev box may set CONCEPT_TRUST_GATE; each test controls it.
    monkeypatch.delenv("CONCEPT_TRUST_GATE", raising=False)


def _make(tmp_path, longterm, exams):
    """Real store + builder over tmp JSONL sources."""
    ki = tmp_path / "knowledge_index.jsonl"
    lt = tmp_path / "longterm.jsonl"
    ex = tmp_path / "exam_results.jsonl"
    ki.write_text("", encoding="utf-8")
    _write_jsonl(lt, longterm)
    _write_jsonl(ex, exams)
    store = BeliefStore(tmp_path / "beliefs.jsonl")
    builder = BeliefBuilder(ki, lt, ex)
    return store, builder


def _concept_types(store):
    return {
        b.related_entities[0]: b.belief_type
        for b in store.get_by_entity_type(EntityType.CONCEPT)
    }


# Two concepts: one from a self-graded file, one from an independent file.
_LONGTERM = [
    {"source_file": "f_self.txt", "chunk_id": "cs",
     "key_points": ["Stolica Polski to Warszawa"], "tags": ["geografia"]},
    {"source_file": "f_indep.txt", "chunk_id": "ci",
     "key_points": ["Woda wrze w 100 stopni Celsjusza"], "tags": ["fizyka"]},
]
_EXAMS_MIXED = [
    {"file": "f_self.txt", "score": 0.9, "grader_independent": False},
    {"file": "f_indep.txt", "score": 0.9, "grader_independent": True},
]


# --- build_concept_beliefs: FACT decision under each mode ---------------------

def test_off_mode_preserves_legacy_fact(tmp_path):
    """Off (default): a self-graded pass still stamps FACT -- byte-identical
    to pre-gate behaviour, so shipping observe-first changes nothing live."""
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    builder.build_concept_beliefs(store)
    types = _concept_types(store)
    assert types["f_self.txt"] == BeliefType.FACT
    assert types["f_indep.txt"] == BeliefType.FACT


def test_observe_mode_preserves_legacy_fact(tmp_path, monkeypatch):
    """Observe: still no behaviour change -- it only enables the census."""
    monkeypatch.setenv("CONCEPT_TRUST_GATE", "observe")
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    builder.build_concept_beliefs(store)
    types = _concept_types(store)
    assert types["f_self.txt"] == BeliefType.FACT
    assert types["f_indep.txt"] == BeliefType.FACT


def test_armed_downgrades_self_graded_keeps_independent(tmp_path, monkeypatch):
    """Armed: the concept from the self-graded file drops to OBSERVATION; the
    one from the independent file keeps FACT."""
    monkeypatch.setenv("CONCEPT_TRUST_GATE", "armed")
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    builder.build_concept_beliefs(store)
    types = _concept_types(store)
    assert types["f_self.txt"] == BeliefType.OBSERVATION
    assert types["f_indep.txt"] == BeliefType.FACT


def test_armed_observe_safe_when_no_independent_exam_exists(tmp_path, monkeypatch):
    """Armed but ZERO independent exams anywhere: enforce must fall back to
    legacy behaviour, never strip FACT off the whole layer on a transient read.
    """
    monkeypatch.setenv("CONCEPT_TRUST_GATE", "armed")
    exams = [{"file": "f_self.txt", "score": 0.9, "grader_independent": False}]
    longterm = [_LONGTERM[0]]  # only the self-graded concept
    store, builder = _make(tmp_path, longterm, exams)
    builder.build_concept_beliefs(store)
    types = _concept_types(store)
    # No independent signal -> guard keeps FACT (fallback), not OBSERVATION.
    assert types["f_self.txt"] == BeliefType.FACT


def test_armed_independent_evidence_carries_independent_score(tmp_path, monkeypatch):
    """Armed FACT cites the INDEPENDENT score in its exam evidence, not a
    higher self-graded one for the same file."""
    monkeypatch.setenv("CONCEPT_TRUST_GATE", "armed")
    exams = [
        {"file": "f_indep.txt", "score": 0.72, "grader_independent": True},
        {"file": "f_indep.txt", "score": 0.99, "grader_independent": False},
    ]
    longterm = [_LONGTERM[1]]
    store, builder = _make(tmp_path, longterm, exams)
    builder.build_concept_beliefs(store)
    belief = store.get_by_entity_type(EntityType.CONCEPT)[0]
    exam_ev = [e for e in belief.evidence if e[0] == BeliefSource.EXAM.value]
    assert exam_ev and exam_ev[0][2] == 0.72  # independent, not 0.99


# --- scan_concept_trust: read-only census ------------------------------------

def test_scan_counts_independent_vs_self_graded(tmp_path):
    """Census splits standing concept-FACTs by exam independence."""
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    builder.build_concept_beliefs(store)  # off mode: both FACT
    census = builder.scan_concept_trust(store)
    assert census == {"total_fact": 2, "independent": 1, "self_graded": 1}


def test_scan_is_read_only(tmp_path):
    """The census never mutates the store."""
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    builder.build_concept_beliefs(store)
    before = {b.belief_id for b in store.get_current()}
    builder.scan_concept_trust(store)
    after = {b.belief_id for b in store.get_current()}
    assert before == after


def test_scan_observe_safe_on_empty_exam_log(tmp_path):
    """Empty exam log -> no report (avoids a misleading 'all self-graded')."""
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    builder.build_concept_beliefs(store)
    # Blank the exam file after building.
    (tmp_path / "exam_results.jsonl").write_text("", encoding="utf-8")
    assert builder.scan_concept_trust(store) == {}


def test_scan_observe_safe_when_no_independent_set(tmp_path):
    """No independent exams -> verified set empty -> no report."""
    exams = [{"file": "f_self.txt", "score": 0.9, "grader_independent": False}]
    store, builder = _make(tmp_path, [_LONGTERM[0]], exams)
    builder.build_concept_beliefs(store)
    assert builder.scan_concept_trust(store) == {}


# --- update_from_exam: runtime promotion path --------------------------------

def _add_observation_concept(store, file_id):
    b = create_belief(
        entity="Pojecie X", entity_type=EntityType.CONCEPT,
        belief_type=BeliefType.OBSERVATION, content="Pojecie X",
        confidence=0.5, source=BeliefSource.MEMORY_FACT,
        source_id=f"concept:{file_id}:0", related_entities=[file_id],
    )
    store.add(b)
    return b


def test_update_from_exam_off_promotes_on_self_graded(tmp_path):
    """Off: a self-graded pass still promotes OBSERVATION -> FACT (legacy)."""
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    _add_observation_concept(store, "f_self.txt")
    builder.update_from_exam(
        store, {"file": "f_self.txt", "score": 0.9, "grader_independent": False}
    )
    got = store.get_by_entity_type(EntityType.CONCEPT)[0]
    assert got.belief_type == BeliefType.FACT


def test_update_from_exam_armed_blocks_self_graded_promotion(tmp_path, monkeypatch):
    """Armed: a self-graded pass must NOT stamp FACT."""
    monkeypatch.setenv("CONCEPT_TRUST_GATE", "armed")
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    _add_observation_concept(store, "f_self.txt")
    builder.update_from_exam(
        store, {"file": "f_self.txt", "score": 0.9, "grader_independent": False}
    )
    got = store.get_by_entity_type(EntityType.CONCEPT)[0]
    assert got.belief_type == BeliefType.OBSERVATION


def test_update_from_exam_armed_promotes_on_independent(tmp_path, monkeypatch):
    """Armed: an INDEPENDENT pass still promotes to FACT."""
    monkeypatch.setenv("CONCEPT_TRUST_GATE", "armed")
    store, builder = _make(tmp_path, _LONGTERM, _EXAMS_MIXED)
    _add_observation_concept(store, "f_indep.txt")
    builder.update_from_exam(
        store, {"file": "f_indep.txt", "score": 0.9, "grader_independent": True}
    )
    got = store.get_by_entity_type(EntityType.CONCEPT)[0]
    assert got.belief_type == BeliefType.FACT
