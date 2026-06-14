"""Synthesis belief blast-radius cap (hardening 2026-06-13).

A synthesized record is gated only by a CLOSED-LOOP exam (questions authored
from its own text), which verifies recall, never truth/groundedness. So a
synthesis must NEVER mint a near-unprunable FACT -- its beliefs stay low-trust
OBSERVATION (confidence <= _SYNTHESIS_BELIEF_CEIL) until an INDEPENDENT,
non-synthesis source/exam corroborates. This cap holds in ALL three build
paths (file, concept, runtime update) and is independent of CONCEPT_TRUST_GATE.

Real BeliefStore + BeliefBuilder + tmp JSONL (no mocks): a MagicMock store
would swallow exactly the folder/id provenance match this cap depends on.
"""

import json

import pytest

from agent_core.world_model.belief_builder import (
    BeliefBuilder,
    _SYNTHESIS_BELIEF_CEIL,
    _is_synthetic_source,
)
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
    monkeypatch.delenv("CONCEPT_TRUST_GATE", raising=False)


def _make(tmp_path, index, longterm, exams):
    ki = tmp_path / "knowledge_index.jsonl"
    lt = tmp_path / "longterm.jsonl"
    ex = tmp_path / "exam_results.jsonl"
    _write_jsonl(ki, index)
    _write_jsonl(lt, longterm)
    _write_jsonl(ex, exams)
    store = BeliefStore(tmp_path / "beliefs.jsonl")
    builder = BeliefBuilder(ki, lt, ex)
    return store, builder


# --- _is_synthetic_source detection ------------------------------------------

def test_is_synthetic_source_signals():
    assert _is_synthetic_source({"folder": "synthesis"}) is True
    assert _is_synthetic_source({"id": "synthesis_kofeina_20260613"}) is True
    assert _is_synthetic_source({"source_file": "synthesis_x_1"}) is True
    assert _is_synthetic_source({"file": "synthesis_y_2"}) is True
    assert _is_synthetic_source({"folder": "general", "id": "wiki_a"}) is False
    assert _is_synthetic_source({}) is False


# --- build_file_beliefs: synthesis capped, real file not ----------------------

def test_build_file_synthesis_capped_to_observation(tmp_path):
    index = [{
        "id": "synthesis_kofeina_1", "folder": "synthesis", "status": "completed",
        "last_scores": [0.85], "tags": ["synthesis", "kofeina"],
    }]
    exams = [{"file": "synthesis_kofeina_1", "score": 0.85,
              "grader_independent": True}]
    store, builder = _make(tmp_path, index, [], exams)
    builder.build_file_beliefs(store)
    files = store.get_by_entity_type(EntityType.FILE)
    assert len(files) == 1
    b = files[0]
    # High score + independent + completed would be FACT for a real file --
    # but a synthesis is capped.
    assert b.belief_type == BeliefType.OBSERVATION
    assert b.confidence <= _SYNTHESIS_BELIEF_CEIL


def test_build_file_real_file_still_fact(tmp_path):
    index = [{
        "id": "real_a.txt", "folder": "general", "status": "completed",
        "last_scores": [0.85], "tags": ["fizyka"],
    }]
    exams = [{"file": "real_a.txt", "score": 0.85, "grader_independent": True}]
    store, builder = _make(tmp_path, index, [], exams)
    builder.build_file_beliefs(store)
    b = store.get_by_entity_type(EntityType.FILE)[0]
    assert b.belief_type == BeliefType.FACT  # control: cap touches only synthesis


# --- build_concept_beliefs: synthesis never FACT, in any gate mode -----------

_SYNTH_LT = [{
    "source_file": "synthesis_kofeina_1", "folder": "synthesis",
    "chunk_id": "synthesis_kofeina_1#chunk_0",
    "key_points": ["Kofeina trwale niszczy konsolidacje pamieci"],
    "tags": ["synthesis", "kofeina"],
}]
_REAL_LT = [{
    "source_file": "f_indep.txt", "folder": "general", "chunk_id": "ci",
    "key_points": ["Woda wrze w 100 stopni Celsjusza"], "tags": ["fizyka"],
}]


@pytest.mark.parametrize("gate", [None, "observe", "armed"])
def test_build_concept_synthesis_stays_observation(tmp_path, monkeypatch, gate):
    if gate:
        monkeypatch.setenv("CONCEPT_TRUST_GATE", gate)
    exams = [{"file": "synthesis_kofeina_1", "score": 0.9,
              "grader_independent": True}]
    store, builder = _make(tmp_path, [], _SYNTH_LT, exams)
    builder.build_concept_beliefs(store)
    concept = store.get_by_entity_type(EntityType.CONCEPT)[0]
    # Score 0.9 + independent would be FACT for a real concept; synthesis caps.
    assert concept.belief_type == BeliefType.OBSERVATION


def test_build_concept_real_source_still_fact(tmp_path):
    exams = [{"file": "f_indep.txt", "score": 0.9, "grader_independent": True}]
    store, builder = _make(tmp_path, [], _REAL_LT, exams)
    builder.build_concept_beliefs(store)
    concept = store.get_by_entity_type(EntityType.CONCEPT)[0]
    assert concept.belief_type == BeliefType.FACT  # control


# --- update_from_exam: runtime path also capped ------------------------------

def _add_observation_concept(store, file_id):
    b = create_belief(
        entity="Pojecie X", entity_type=EntityType.CONCEPT,
        belief_type=BeliefType.OBSERVATION, content="Pojecie X",
        confidence=0.5, source=BeliefSource.MEMORY_FACT,
        source_id=f"concept:{file_id}#chunk_0:0", related_entities=[file_id],
    )
    store.add(b)
    return b


def test_update_from_exam_synthesis_never_promotes(tmp_path):
    store, builder = _make(tmp_path, [], _SYNTH_LT, [])
    _add_observation_concept(store, "synthesis_kofeina_1")
    builder.update_from_exam(
        store,
        {"file": "synthesis_kofeina_1", "score": 0.95, "grader_independent": True},
    )
    got = store.get_by_entity_type(EntityType.CONCEPT)[0]
    # Even an independent high pass cannot promote a synthesis concept.
    assert got.belief_type == BeliefType.OBSERVATION
    assert got.confidence <= _SYNTHESIS_BELIEF_CEIL


def test_update_from_exam_real_file_still_promotes(tmp_path):
    store, builder = _make(tmp_path, [], _REAL_LT, [])
    _add_observation_concept(store, "f_indep.txt")
    builder.update_from_exam(
        store, {"file": "f_indep.txt", "score": 0.95, "grader_independent": True},
    )
    got = store.get_by_entity_type(EntityType.CONCEPT)[0]
    assert got.belief_type == BeliefType.FACT  # control
