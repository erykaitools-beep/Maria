"""Tests for ResponseBuilder."""

import time

import pytest

from agent_core.introspection.evidence_collector import Evidence
from agent_core.introspection.query_router import ResponseMode
from agent_core.introspection.response_builder import (
    GroundedResponse,
    ResponseBuilder,
)


@pytest.fixture
def builder():
    return ResponseBuilder()


def _ev(key, value, source="test.jsonl", confidence="high"):
    return Evidence(key=key, value=value, source=source,
                    confidence=confidence, timestamp=time.time())


# -- GroundedResponse --

class TestGroundedResponse:
    def test_creation(self):
        r = GroundedResponse(
            mode=ResponseMode.GROUNDED_STATUS,
            evidence=[],
            text="test",
        )
        assert r.text == "test"
        assert r.formatted_text == ""
        assert r.sources == []


# -- Empty evidence --

class TestEmptyEvidence:
    def test_no_evidence(self, builder):
        resp = builder.build(ResponseMode.GROUNDED_STATUS, [])
        assert "Brak danych" in resp.text
        assert resp.evidence == []


# -- Status response --

class TestStatusResponse:
    def test_basic_status(self, builder):
        evidence = [
            _ev("homeostasis.mode", "active"),
            _ev("homeostasis.health", "0.95"),
            _ev("planner.last_action", "learn"),
            _ev("planner.last_goal", "Nauka homeostazy"),
            _ev("learning.total_files", "67"),
            _ev("learning.completed", "12"),
            _ev("llm.total_calls_24h", "42"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_STATUS, evidence)
        assert "active" in resp.text
        assert "0.95" in resp.text
        assert "learn" in resp.text
        assert "67" in resp.text
        assert "42" in resp.text
        assert resp.sources

    def test_partial_status(self, builder):
        evidence = [_ev("homeostasis.mode", "reduced")]
        resp = builder.build(ResponseMode.GROUNDED_STATUS, evidence)
        assert "reduced" in resp.text


# -- Error response --

class TestErrorResponse:
    def test_repeated_failures(self, builder):
        evidence = [
            _ev("planner.repeated_failure.exam",
                "2517 razy w ostatnich 20 decyzjach (consecutive_failures)"),
            _ev("homeostasis.mode", "active"),
            _ev("homeostasis.health", "0.90"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_ERROR, evidence)
        assert "2517" in resp.text
        assert "exam" in resp.text
        assert "Pewnosc" in resp.text

    def test_autonomy_blocks(self, builder):
        evidence = [
            _ev("autonomy.block.consecutive_failure_breaker",
                "5 blokad", source="autonomy_decisions.jsonl"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_ERROR, evidence)
        assert "consecutive_failure_breaker" in resp.text
        assert "5 blokad" in resp.text

    def test_llm_errors(self, builder):
        evidence = [
            _ev("llm.error", "model=llama3.1:8b role=chat response=''"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_ERROR, evidence)
        assert "llama3.1:8b" in resp.text

    def test_no_problems(self, builder):
        resp = builder.build(ResponseMode.GROUNDED_ERROR, [])
        assert "Brak danych" in resp.text


# -- Learning response --

class TestLearningResponse:
    def test_learning_progress(self, builder):
        evidence = [
            _ev("learning.total_files", "67"),
            _ev("learning.completed", "12"),
            _ev("learning.last_exam", "homeostaza.txt: 0.85 (zdany)"),
            _ev("evaluation.retention_rate", "0.78"),
            _ev("planner.last_action", "learn"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_LEARNING, evidence)
        assert "67" in resp.text
        assert "12" in resp.text
        assert "0.85" in resp.text
        assert "0.78" in resp.text


# -- Planner response --

class TestPlannerResponse:
    def test_planner_status(self, builder):
        evidence = [
            _ev("planner.last_action", "exam"),
            _ev("planner.last_goal", "Egzamin"),
            _ev("planner.last_status", "failed"),
            _ev("goal.goal-meta-learn", "[meta] Autonomiczna nauka"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_PLANNER, evidence)
        assert "exam" in resp.text
        assert "failed" in resp.text
        assert "Autonomiczna nauka" in resp.text


# -- Sources tracking --

class TestSources:
    def test_sources_in_response(self, builder):
        evidence = [
            _ev("planner.last_action", "learn", source="planner_decisions.jsonl"),
            _ev("homeostasis.mode", "active", source="homeostasis_events.jsonl"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_STATUS, evidence)
        assert "planner_decisions.jsonl" in resp.text
        assert "homeostasis_events.jsonl" in resp.text
        assert len(resp.sources) == 2

    def test_deduped_sources(self, builder):
        evidence = [
            _ev("planner.last_action", "learn", source="planner_decisions.jsonl"),
            _ev("planner.last_goal", "Nauka", source="planner_decisions.jsonl"),
        ]
        resp = builder.build(ResponseMode.GROUNDED_STATUS, evidence)
        assert resp.sources.count("planner_decisions.jsonl") == 1
