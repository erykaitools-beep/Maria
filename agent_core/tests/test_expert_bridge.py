"""
Tests for Expert Bridge (Phase 4 of Learning Upgrade).

ExpertBridge: audit -> gap plan -> targeted LLM call.
"""

import pytest

from agent_core.bulletin.expert_bridge import (
    ExpertBridge,
    ExpertResponse,
    MIN_RESPONSE_LENGTH,
    _SYSTEM_WRAPPER,
)
from agent_core.bulletin.knowledge_auditor import (
    AuditReport,
    KnowledgeGap,
    GapType,
)
from agent_core.bulletin.gap_planner import (
    GapPlanner,
    GapPlan,
    GapAction,
)


# ═══════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════


def _make_audit(
    topic="fizyka",
    known=True,
    gaps=None,
    avg_confidence=0.6,
    files_count=3,
    freshness=0.8,
    beliefs_count=5,
):
    """Create a test AuditReport."""
    return AuditReport(
        topic=topic,
        known=known,
        files_count=files_count,
        beliefs_count=beliefs_count,
        avg_confidence=avg_confidence,
        freshness=freshness,
        gaps=gaps or [],
        suggested_actions=[],
    )


def _make_gap(gap_type=GapType.LOW_CONFIDENCE, description="low conf"):
    return KnowledgeGap(
        gap_type=gap_type,
        topic="fizyka",
        severity=0.6,
        description=description,
    )


def _long_response(n=200):
    """Generate response longer than MIN_RESPONSE_LENGTH."""
    return "Fizyka to nauka o prawach przyrody. " * n


def _short_response():
    return "Krotka."


@pytest.fixture(autouse=True)
def _isolate_expert_input(monkeypatch):
    """Isolate ExpertBridge tests from local input/expert_*.txt state.

    _expert_file_exists() hardcodes the real repo input/ dir, so a pre-existing
    input/expert_fizyka.txt (real learning material on this box) makes
    ask_about_topic short-circuit with expert_material_already_exists and the
    LLM-pipeline tests fail -- a test-isolation gap, not a regression from any
    commit. Default to "no local material" so tests exercise the pipeline
    regardless of what input/ contains.
    """
    monkeypatch.setattr(
        "agent_core.bulletin.expert_bridge.ExpertBridge._expert_file_exists",
        staticmethod(lambda topic="": False),
    )


class FakeAuditor:
    def __init__(self, report):
        self._report = report

    def audit_topic(self, topic):
        return self._report


class FakeGapPlanner:
    def __init__(self, plan):
        self._plan = plan

    def plan_for_topic(self, audit, goal_desc=""):
        return self._plan


# ═══════════════════════════════════════════════════════
# ExpertResponse
# ═══════════════════════════════════════════════════════


class TestExpertResponse:
    def test_to_dict(self):
        r = ExpertResponse(
            success=True, topic="fizyka", response="abc" * 50,
            context_prompt="prompt", gap_action="ask_expert",
            reason="no_knowledge_exists", duration_ms=123.4,
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["topic"] == "fizyka"
        assert d["response_length"] == 150
        assert d["duration_ms"] == 123.4

    def test_defaults(self):
        r = ExpertResponse(success=False, topic="x")
        assert r.response == ""
        assert r.metadata == {}
        assert r.duration_ms == 0.0


# ═══════════════════════════════════════════════════════
# ExpertBridge - no dependencies
# ═══════════════════════════════════════════════════════


class TestExpertBridgeNoDeps:
    def test_no_llm_fn_returns_failure(self):
        bridge = ExpertBridge()
        result = bridge.ask_about_topic("fizyka")
        assert result.success is False
        assert result.reason == "no_llm_fn"

    def test_ask_with_context_no_llm_fn(self):
        bridge = ExpertBridge()
        result = bridge.ask_with_context("fizyka", "Maria potrzebuje...")
        assert result.success is False
        assert result.reason == "no_llm_fn"


# ═══════════════════════════════════════════════════════
# ExpertBridge - with LLM only (no auditor/planner)
# ═══════════════════════════════════════════════════════


class TestExpertBridgeLLMOnly:
    def setup_method(self):
        self.bridge = ExpertBridge()
        self.bridge.set_llm_fn(lambda prompt: _long_response())

    def test_generic_prompt_when_no_auditor(self):
        result = self.bridge.ask_about_topic("fizyka")
        assert result.success is True
        assert result.topic == "fizyka"
        assert len(result.response) >= MIN_RESPONSE_LENGTH

    def test_ask_with_context_direct(self):
        result = self.bridge.ask_with_context(
            "fizyka", "Maria wie o grawitacji, brakuje optyki"
        )
        assert result.success is True
        assert result.gap_action == "direct"

    def test_short_response_fails(self):
        self.bridge.set_llm_fn(lambda p: _short_response())
        result = self.bridge.ask_about_topic("fizyka")
        assert result.success is False
        assert result.reason == "response_too_short"

    def test_empty_response_fails(self):
        self.bridge.set_llm_fn(lambda p: "")
        result = self.bridge.ask_about_topic("fizyka")
        assert result.success is False

    def test_none_response_fails(self):
        self.bridge.set_llm_fn(lambda p: None)
        result = self.bridge.ask_about_topic("fizyka")
        assert result.success is False

    def test_llm_exception_returns_failure(self):
        self.bridge.set_llm_fn(lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        result = self.bridge.ask_about_topic("fizyka")
        assert result.success is False
        assert "llm_error" in result.reason

    def test_duration_tracked(self):
        result = self.bridge.ask_about_topic("fizyka")
        assert result.duration_ms > 0

    def test_goal_description_in_generic_prompt(self):
        prompts = []
        self.bridge.set_llm_fn(lambda p: (prompts.append(p), _long_response())[1])
        self.bridge.ask_about_topic("fizyka", goal_description="Zrozumiec grawitacje")
        assert "Zrozumiec grawitacje" in prompts[0]


# ═══════════════════════════════════════════════════════
# ExpertBridge - full pipeline (auditor + gap planner)
# ═══════════════════════════════════════════════════════


class TestExpertBridgeFullPipeline:
    def _make_bridge(self, audit, gap_plan, llm_response=None):
        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: llm_response or _long_response())
        bridge.set_auditor(FakeAuditor(audit))
        bridge.set_gap_planner(FakeGapPlanner(gap_plan))
        return bridge

    def test_no_action_when_well_covered(self):
        audit = _make_audit(gaps=[])
        plan = GapPlan(
            action=GapAction.NO_ACTION,
            topic="fizyka",
            reason="topic_well_covered",
        )
        bridge = self._make_bridge(audit, plan)
        result = bridge.ask_about_topic("fizyka")
        assert result.success is False
        assert result.reason == "topic_well_covered"

    def test_uses_context_prompt_from_gap_planner(self):
        audit = _make_audit(gaps=[_make_gap()])
        plan = GapPlan(
            action=GapAction.ASK_EXPERT,
            topic="fizyka",
            reason="no_knowledge_exists",
            context_prompt="Maria wie o mechanice, potrzebuje optyki",
        )
        prompts = []
        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: (prompts.append(p), _long_response())[1])
        bridge.set_auditor(FakeAuditor(audit))
        bridge.set_gap_planner(FakeGapPlanner(plan))

        result = bridge.ask_about_topic("fizyka")
        assert result.success is True
        # Context prompt from gap planner should be in the sent prompt
        assert "Maria wie o mechanice" in prompts[0]
        assert "potrzebuje optyki" in prompts[0]
        assert result.context_prompt == "Maria wie o mechanice, potrzebuje optyki"

    def test_from_scratch_when_unknown_topic(self):
        audit = _make_audit(known=False, gaps=[_make_gap(GapType.NO_MATERIAL)])
        plan = GapPlan(
            action=GapAction.ASK_EXPERT,
            topic="kwanty",
            reason="no_knowledge_exists",
            # No context_prompt - gap planner didn't build one
            context_prompt="",
        )
        prompts = []
        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: (prompts.append(p), _long_response())[1])
        bridge.set_auditor(FakeAuditor(audit))
        bridge.set_gap_planner(FakeGapPlanner(plan))

        result = bridge.ask_about_topic("kwanty")
        assert result.success is True
        # Should use from-scratch prompt
        assert "nie ma zadnej wiedzy" in prompts[0]

    def test_metadata_contains_audit_info(self):
        audit = _make_audit(
            known=True, avg_confidence=0.4, files_count=2,
            gaps=[_make_gap()],
        )
        plan = GapPlan(
            action=GapAction.ASK_EXPERT,
            topic="fizyka",
            reason="knowledge_gaps_detected",
            context_prompt="Maria potrzebuje...",
        )
        bridge = self._make_bridge(audit, plan)
        result = bridge.ask_about_topic("fizyka")
        assert result.metadata["audit_known"] is True
        assert result.metadata["audit_confidence"] == 0.4
        assert result.metadata["audit_files"] == 2
        assert result.metadata["gap_count"] == 1

    def test_fetch_material_action_also_queries_llm(self):
        """FETCH_MATERIAL with context_prompt should also ask expert."""
        audit = _make_audit(gaps=[_make_gap()])
        plan = GapPlan(
            action=GapAction.FETCH_MATERIAL,
            topic="biologia",
            reason="general_gap",
            context_prompt="Maria potrzebuje podstaw biologii",
        )
        bridge = self._make_bridge(audit, plan)
        result = bridge.ask_about_topic("biologia")
        assert result.success is True
        assert result.gap_action == "fetch_material"

    def test_auditor_failure_falls_through_to_generic(self):
        """If auditor raises, bridge still works with generic prompt."""
        class BrokenAuditor:
            def audit_topic(self, t):
                raise RuntimeError("db broken")

        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: _long_response())
        bridge.set_auditor(BrokenAuditor())
        result = bridge.ask_about_topic("fizyka")
        assert result.success is True

    def test_gap_planner_failure_falls_through(self):
        """If gap planner raises, bridge still works."""
        class BrokenPlanner:
            def plan_for_topic(self, a, g=""):
                raise RuntimeError("planner broken")

        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: _long_response())
        bridge.set_auditor(FakeAuditor(_make_audit(gaps=[_make_gap()])))
        bridge.set_gap_planner(BrokenPlanner())
        result = bridge.ask_about_topic("fizyka")
        assert result.success is True


# ═══════════════════════════════════════════════════════
# ask_with_context
# ═══════════════════════════════════════════════════════


class TestAskWithContext:
    def test_uses_provided_context(self):
        prompts = []
        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: (prompts.append(p), _long_response())[1])

        result = bridge.ask_with_context(
            "optyka", "Maria zna mechanike ale nie zna optyki"
        )
        assert result.success is True
        assert "nie zna optyki" in prompts[0]

    def test_llm_error_in_context_mode(self):
        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: (_ for _ in ()).throw(ValueError("fail")))

        result = bridge.ask_with_context("x", "context")
        assert result.success is False
        assert "llm_error" in result.reason

    def test_short_response_in_context_mode(self):
        bridge = ExpertBridge()
        bridge.set_llm_fn(lambda p: "za krotko")

        result = bridge.ask_with_context("x", "context")
        assert result.success is False
        assert result.reason == "response_too_short"


# ═══════════════════════════════════════════════════════
# Prompt building
# ═══════════════════════════════════════════════════════


class TestPromptBuilding:
    def test_enhance_prompt_includes_system_wrapper(self):
        bridge = ExpertBridge()
        prompt = bridge._enhance_prompt("Maria wie X", "fizyka")
        assert "ekspertem edukacyjnym" in prompt
        assert "Maria wie X" in prompt
        assert "fizyka" in prompt

    def test_from_scratch_prompt(self):
        bridge = ExpertBridge()
        prompt = bridge._build_from_scratch_prompt("kwanty", "")
        assert "nie ma zadnej wiedzy" in prompt
        assert "kwanty" in prompt
        assert "Definicja" in prompt

    def test_from_scratch_with_goal(self):
        bridge = ExpertBridge()
        prompt = bridge._build_from_scratch_prompt("kwanty", "Zrozumiec fotony")
        assert "Zrozumiec fotony" in prompt

    def test_generic_prompt(self):
        bridge = ExpertBridge()
        prompt = bridge._build_generic_prompt("chemia", "")
        assert "chemia" in prompt

    def test_prompt_truncation(self):
        bridge = ExpertBridge()
        long_context = "x" * 5000
        prompt = bridge._enhance_prompt(long_context, "topic")
        assert len(prompt) <= 3000
