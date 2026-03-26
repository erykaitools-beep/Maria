"""Tests for K13 Creative Module Phase 2 (LLM-enhanced engines).

Tests all new modules:
- IdentityProfile + CognitiveProfile
- PersonalityPolicy
- MemoryRetriever
- MemorySummarizer
- MetaGoalEngine
- ReframeEngine
- ExplorationEngine
- LLM utils (try_parse_json, safe_llm_call)
- TokenBudget RPM
- Facade Phase 2 integration (reflect with LLM)
"""

import json
import os
import time
import pytest
from unittest.mock import MagicMock, patch

from agent_core.creative.creative_model import (
    DetectedTension, ExplorationProgram, MetaGoal, MetaGoalType,
    MetaGoalStatus, PersonalityDimension, PersonalitySignal,
    ReframeProposal, ReflectionSession, TensionCategory, RiskLevel,
)


# ==============================
# Test Fixtures
# ==============================

@pytest.fixture
def tmp_meta(tmp_path):
    """Create temp meta_data directory with sample files."""
    meta = tmp_path / "meta_data"
    meta.mkdir()
    return meta


@pytest.fixture
def tmp_memory(tmp_path):
    """Create temp memory directory with sample files."""
    mem = tmp_path / "memory"
    mem.mkdir()
    return mem


@pytest.fixture
def sample_identity(tmp_meta):
    """Create sample consciousness_identity.json."""
    data = {
        "session_count": 42,
        "total_uptime_seconds": 72000,
        "trait_scores": {
            "ciekawska": {"score": 0.72},
            "systematyczna": {"score": 0.65},
            "pomocna": {"score": 0.58},
            "wytrwala": {"score": 0.50},
            "cierpliwa": {"score": 0.45},
            "refleksyjna": {"score": 0.70},
            "spoleczna": {"score": 0.55},
        },
    }
    path = tmp_meta / "consciousness_identity.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def sample_knowledge_index(tmp_memory):
    """Create sample knowledge_index.jsonl with topics."""
    records = [
        {"id": "f1", "topic": "fizyka", "status": "completed", "exam_score": 0.85},
        {"id": "f2", "topic": "fizyka", "status": "completed", "exam_score": 0.90},
        {"id": "f3", "topic": "biologia", "status": "learned", "exam_score": 0.40},
        {"id": "f4", "topic": "chemia", "status": "new"},
        {"id": "f5", "topic": "matematyka", "status": "completed", "exam_score": 0.95},
    ]
    path = tmp_memory / "knowledge_index.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


@pytest.fixture
def sample_planner_decisions(tmp_meta):
    """Create sample planner_decisions.jsonl."""
    now = time.time()
    records = [
        {"timestamp": now - 100, "action_type": "learn", "status": "ok"},
        {"timestamp": now - 200, "action_type": "learn", "status": "ok"},
        {"timestamp": now - 300, "action_type": "noop", "status": "ok"},
        {"timestamp": now - 400, "action_type": "fetch", "status": "failed"},
        {"timestamp": now - 500, "action_type": "exam", "status": "ok"},
    ]
    path = tmp_meta / "planner_decisions.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


@pytest.fixture
def sample_eval_reports(tmp_meta):
    """Create sample evaluation_reports.jsonl."""
    records = [
        {"metrics": {"learning_velocity": 0.05, "retention_rate": 0.7}},
        {"metrics": {"learning_velocity": 0.08, "retention_rate": 0.75}},
        {"metrics": {"learning_velocity": 0.12, "retention_rate": 0.80}},
    ]
    path = tmp_meta / "evaluation_reports.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


@pytest.fixture
def sample_tension():
    return DetectedTension.create(
        category=TensionCategory.REPETITION,
        description="System powtarza te same akcje w kolko",
        severity=0.7,
        evidence_refs=["decision-123"],
        pattern_window="24h",
    )


@pytest.fixture
def sample_context():
    return {
        "action_pattern": {"total": 20, "noop_ratio": 0.7, "failed_ratio": 0.1},
        "learning_state": {
            "total_files": 10, "completed": 7, "coverage": 0.7,
            "retention_rate": 0.65, "learning_velocity": 0.05,
            "statuses": {"completed": 7, "new": 2, "exam_failed": 1},
        },
        "goal_state": {"active": 3, "proposed": 1, "stale_goals": ["Stary cel"]},
        "recent_meta_goals": [],
        "system_health": {"system_stability": 0.9, "personality_growth": 0.1},
        "identity": {"session_count": 42, "trait_scores": {"ciekawska": 0.7}},
    }


def _make_mock_llm(response_text):
    """Create a mock LLM function that returns given text."""
    return MagicMock(return_value=response_text)


# ==============================
# LLM Utils
# ==============================

class TestLLMUtils:

    def test_try_parse_json_clean(self):
        from agent_core.creative.llm_utils import try_parse_json
        result = try_parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_try_parse_json_markdown_fenced(self):
        from agent_core.creative.llm_utils import try_parse_json
        text = '```json\n{"key": "value"}\n```'
        result = try_parse_json(text)
        assert result == {"key": "value"}

    def test_try_parse_json_embedded(self):
        from agent_core.creative.llm_utils import try_parse_json
        text = 'Some text before {"key": "value"} and after'
        result = try_parse_json(text)
        assert result == {"key": "value"}

    def test_try_parse_json_invalid(self):
        from agent_core.creative.llm_utils import try_parse_json
        assert try_parse_json("not json at all") is None
        assert try_parse_json("") is None
        assert try_parse_json(None) is None

    def test_safe_llm_call_success(self):
        from agent_core.creative.llm_utils import safe_llm_call
        fn = _make_mock_llm("response text")
        result = safe_llm_call(fn, "prompt")
        assert result == "response text"

    def test_safe_llm_call_none_fn(self):
        from agent_core.creative.llm_utils import safe_llm_call
        assert safe_llm_call(None, "prompt") is None

    def test_safe_llm_call_exception(self):
        from agent_core.creative.llm_utils import safe_llm_call
        fn = MagicMock(side_effect=Exception("API error"))
        assert safe_llm_call(fn, "prompt") is None

    def test_safe_llm_call_empty_response(self):
        from agent_core.creative.llm_utils import safe_llm_call
        fn = _make_mock_llm("")
        assert safe_llm_call(fn, "prompt") is None


# ==============================
# IdentityProfile
# ==============================

class TestIdentityProfile:

    def test_build_with_data(self, tmp_meta, tmp_memory, sample_identity,
                              sample_knowledge_index, sample_planner_decisions,
                              sample_eval_reports):
        from agent_core.creative.identity_profile import IdentityProfile
        profile = IdentityProfile(str(tmp_meta), str(tmp_memory))
        result = profile.build()

        assert result.growth_trajectory in ("accelerating", "stable", "slowing", "stalled")
        assert len(result.dominant_traits) <= 3
        assert "ciekawska" in result.dominant_traits  # highest score
        assert result.total_files == 5
        assert result.completed_files == 4  # completed + learned
        assert result.coverage > 0

    def test_build_empty_dir(self, tmp_path):
        from agent_core.creative.identity_profile import IdentityProfile
        meta = tmp_path / "meta_data"
        mem = tmp_path / "memory"
        meta.mkdir()
        mem.mkdir()
        profile = IdentityProfile(str(meta), str(mem))
        result = profile.build()

        assert result.growth_trajectory == "stable"
        assert result.dominant_traits == []
        assert result.domain_strengths == {}
        assert result.total_files == 0

    def test_domain_retention(self, tmp_meta, tmp_memory, sample_knowledge_index):
        from agent_core.creative.identity_profile import IdentityProfile
        profile = IdentityProfile(str(tmp_meta), str(tmp_memory))
        domains = profile._get_domain_retention()

        assert "fizyka" in domains
        assert domains["fizyka"] == pytest.approx(0.875, abs=0.01)  # (0.85+0.90)/2
        assert "biologia" in domains
        assert domains["biologia"] == pytest.approx(0.40, abs=0.01)

    def test_trait_scores(self, tmp_meta, tmp_memory, sample_identity):
        from agent_core.creative.identity_profile import IdentityProfile
        profile = IdentityProfile(str(tmp_meta), str(tmp_memory))
        traits = profile._get_trait_scores()

        assert traits["ciekawska"] == pytest.approx(0.72)
        assert traits["systematyczna"] == pytest.approx(0.65)

    def test_trajectory_accelerating(self, tmp_meta, tmp_memory):
        from agent_core.creative.identity_profile import IdentityProfile
        # Create reports with increasing velocity
        records = [
            {"metrics": {"learning_velocity": 0.01}},
            {"metrics": {"learning_velocity": 0.02}},
            {"metrics": {"learning_velocity": 0.08}},
            {"metrics": {"learning_velocity": 0.15}},
        ]
        path = tmp_meta / "evaluation_reports.jsonl"
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        profile = IdentityProfile(str(tmp_meta), str(tmp_memory))
        assert profile._classify_trajectory() == "accelerating"

    def test_trajectory_stalled(self, tmp_meta, tmp_memory):
        from agent_core.creative.identity_profile import IdentityProfile
        records = [
            {"metrics": {"learning_velocity": 0.0}},
            {"metrics": {"learning_velocity": 0.0}},
            {"metrics": {"learning_velocity": 0.0}},
            {"metrics": {"learning_velocity": 0.001}},
        ]
        path = tmp_meta / "evaluation_reports.jsonl"
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        profile = IdentityProfile(str(tmp_meta), str(tmp_memory))
        assert profile._classify_trajectory() == "stalled"

    def test_capability_map(self, tmp_meta, tmp_memory, sample_planner_decisions):
        from agent_core.creative.identity_profile import IdentityProfile
        profile = IdentityProfile(str(tmp_meta), str(tmp_memory))
        cap = profile._get_capability_map()

        assert "learn" in cap
        assert cap["learn"] == 2

    def test_meta_goal_acceptance_rate(self, tmp_meta, tmp_memory):
        from agent_core.creative.identity_profile import IdentityProfile
        records = [
            {"goal_id": "mg-1", "status": "accepted"},
            {"goal_id": "mg-2", "status": "rejected"},
            {"goal_id": "mg-3", "status": "accepted"},
        ]
        path = tmp_meta / "creative_meta_goals.jsonl"
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        profile = IdentityProfile(str(tmp_meta), str(tmp_memory))
        rate = profile._get_meta_goal_acceptance_rate()
        assert rate == pytest.approx(2/3, abs=0.01)


# ==============================
# PersonalityPolicy
# ==============================

class TestPersonalityPolicy:

    def test_evaluate_ciekawska_high(self):
        from agent_core.creative.personality_policy import PersonalityPolicy
        from agent_core.creative.identity_profile import CognitiveProfile
        profile = CognitiveProfile(
            growth_trajectory="stable",
            dominant_traits=["ciekawska", "systematyczna", "refleksyjna"],
            domain_strengths={}, domain_weaknesses={},
            capability_map={}, meta_goal_acceptance_rate=0.5,
            total_files=10, completed_files=5, coverage=0.5,
        )
        policy = PersonalityPolicy()
        signals = policy.evaluate(profile, [])

        # ciekawska is dominant (0.7) -> exploration signal
        dims = [s.dimension for s in signals]
        assert PersonalityDimension.EXPLORATION_VS_ORDER in dims

    def test_evaluate_wytrwala_boldness(self):
        from agent_core.creative.personality_policy import PersonalityPolicy
        from agent_core.creative.identity_profile import CognitiveProfile
        profile = CognitiveProfile(
            growth_trajectory="stable",
            dominant_traits=["wytrwala", "ciekawska", "pomocna"],
            domain_strengths={}, domain_weaknesses={},
            capability_map={}, meta_goal_acceptance_rate=0.5,
            total_files=10, completed_files=5, coverage=0.5,
        )
        policy = PersonalityPolicy()
        signals = policy.evaluate(profile, [])

        bold = [s for s in signals if s.dimension == PersonalityDimension.CAUTION_VS_BOLDNESS]
        assert any(s.direction == "boldness" for s in bold)

    def test_evaluate_cierpliwa_with_stagnation(self):
        from agent_core.creative.personality_policy import PersonalityPolicy
        from agent_core.creative.identity_profile import CognitiveProfile
        profile = CognitiveProfile(
            growth_trajectory="stable",
            dominant_traits=["cierpliwa", "pomocna", "spoleczna"],
            domain_strengths={}, domain_weaknesses={},
            capability_map={}, meta_goal_acceptance_rate=0.5,
            total_files=10, completed_files=5, coverage=0.5,
        )
        tension = DetectedTension.create(
            category=TensionCategory.STAGNATION,
            description="No progress", severity=0.6,
            evidence_refs=[], pattern_window="24h",
        )
        policy = PersonalityPolicy()
        signals = policy.evaluate(profile, [tension])

        caution = [s for s in signals if s.direction == "caution"]
        assert len(caution) >= 1

    def test_adjust_weights_normalizes(self):
        from agent_core.creative.personality_policy import PersonalityPolicy
        policy = PersonalityPolicy()
        signal = PersonalitySignal.create(
            dimension=PersonalityDimension.EXPLORATION_VS_ORDER,
            direction="exploration",
            reason="test",
            magnitude=0.05,
        )
        weights = policy.adjust_evaluation_weights(signals=[signal])

        # Should sum to ~1.0
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_adjust_weights_no_signals(self):
        from agent_core.creative.personality_policy import (
            PersonalityPolicy, DEFAULT_WEIGHTS,
        )
        policy = PersonalityPolicy()
        weights = policy.adjust_evaluation_weights()
        assert weights == DEFAULT_WEIGHTS

    def test_adjust_weights_clamps_negative(self):
        from agent_core.creative.personality_policy import PersonalityPolicy
        policy = PersonalityPolicy()
        # Extreme signal that would push a weight negative
        signals = [
            PersonalitySignal.create(
                dimension=PersonalityDimension.CAUTION_VS_BOLDNESS,
                direction="boldness", reason="test", magnitude=0.1,
            )
            for _ in range(5)
        ]
        weights = policy.adjust_evaluation_weights(signals=signals)
        # All weights should be positive (no negative values)
        assert all(v > 0 for v in weights.values())
        # Sum should be ~1.0
        assert abs(sum(weights.values()) - 1.0) < 0.01


# ==============================
# MemoryRetriever
# ==============================

class TestMemoryRetriever:

    def test_extract_keywords_from_tensions(self, sample_tension):
        from agent_core.creative.memory_retriever import MemoryRetriever
        from agent_core.creative.creative_store import CreativeStore
        store = MagicMock(spec=CreativeStore)
        retriever = MemoryRetriever(store)

        keywords = retriever.extract_keywords([sample_tension], {})
        assert len(keywords) > 0
        # Should include category-specific keywords
        assert "powtarzanie" in keywords or "noop" in keywords

    def test_extract_keywords_from_stale_goals(self):
        from agent_core.creative.memory_retriever import MemoryRetriever
        from agent_core.creative.creative_store import CreativeStore
        store = MagicMock(spec=CreativeStore)
        retriever = MemoryRetriever(store)

        context = {
            "goal_state": {"stale_goals": ["Nauka biologii molekularnej"]},
            "learning_state": {"statuses": {}},
        }
        keywords = retriever.extract_keywords([], context)
        assert any("biologii" in kw or "molekularnej" in kw for kw in keywords)

    def test_keywords_deduplication(self, sample_tension):
        from agent_core.creative.memory_retriever import MemoryRetriever
        from agent_core.creative.creative_store import CreativeStore
        store = MagicMock(spec=CreativeStore)
        retriever = MemoryRetriever(store)

        keywords = retriever.extract_keywords([sample_tension, sample_tension], {})
        # No duplicates
        assert len(keywords) == len(set(keywords))

    def test_keywords_cap_at_30(self):
        from agent_core.creative.memory_retriever import MemoryRetriever
        from agent_core.creative.creative_store import CreativeStore
        store = MagicMock(spec=CreativeStore)
        retriever = MemoryRetriever(store)

        # Many tensions with long descriptions
        tensions = [
            DetectedTension.create(
                category=TensionCategory.REPETITION,
                description="Bardzo dlugi opis napiecia " * 20,
                severity=0.7, evidence_refs=[], pattern_window="24h",
            )
            for _ in range(10)
        ]
        keywords = retriever.extract_keywords(tensions, {})
        assert len(keywords) <= 30


# ==============================
# MemorySummarizer
# ==============================

class TestMemorySummarizer:

    def test_summarize_rule_based(self):
        from agent_core.creative.memory_summarizer import MemorySummarizer
        summarizer = MemorySummarizer()  # no LLM

        memories = [
            {"content": "Operator chce szybszej nauki", "importance": 0.8},
            {"content": "Operator preferuje tematy z fizyki", "importance": 0.6},
        ]
        result = summarizer.summarize(memories)
        assert "Kontekst z pamieci operatora:" in result
        assert "szybszej nauki" in result

    def test_summarize_empty(self):
        from agent_core.creative.memory_summarizer import MemorySummarizer
        summarizer = MemorySummarizer()
        assert summarizer.summarize([]) == ""

    def test_summarize_respects_max_chars(self):
        from agent_core.creative.memory_summarizer import MemorySummarizer
        summarizer = MemorySummarizer()

        memories = [
            {"content": "A" * 500, "importance": 0.9},
            {"content": "B" * 500, "importance": 0.8},
            {"content": "C" * 500, "importance": 0.7},
        ]
        result = summarizer.summarize(memories, max_chars=300)
        assert len(result) <= 300

    def test_summarize_prefers_summary_over_content(self):
        from agent_core.creative.memory_summarizer import MemorySummarizer
        summarizer = MemorySummarizer()

        memories = [
            {"content": "Dlugi tekst oryginalny", "summary": "Krotki",
             "importance": 0.8},
        ]
        result = summarizer.summarize(memories)
        assert "Krotki" in result

    def test_summarize_with_llm(self):
        from agent_core.creative.memory_summarizer import MemorySummarizer
        llm = _make_mock_llm("- Operator chce fizyki\n- Szybsza nauka")
        summarizer = MemorySummarizer(llm)

        memories = [
            {"content": "Cos", "importance": 0.8, "speaker": "operator",
             "memory_type": "preference"},
        ]
        result = summarizer.summarize(memories)
        assert "fizyki" in result
        llm.assert_called_once()

    def test_summarize_llm_fallback(self):
        from agent_core.creative.memory_summarizer import MemorySummarizer
        llm = MagicMock(side_effect=Exception("API error"))
        summarizer = MemorySummarizer(llm)

        memories = [
            {"content": "Fallback content", "importance": 0.8},
        ]
        result = summarizer.summarize(memories)
        assert "Fallback content" in result

    def test_set_llm_fn(self):
        from agent_core.creative.memory_summarizer import MemorySummarizer
        summarizer = MemorySummarizer()
        assert summarizer._llm_fn is None
        llm = _make_mock_llm("test")
        summarizer.set_llm_fn(llm)
        assert summarizer._llm_fn is llm


# ==============================
# MetaGoalEngine
# ==============================

class TestMetaGoalEngine:

    def test_generate_rule_based(self, sample_tension, sample_context):
        from agent_core.creative.meta_goal_engine import MetaGoalEngine
        engine = MetaGoalEngine()  # no LLM
        result = engine.generate(sample_tension, sample_context)

        assert "title" in result
        assert "expected_value" in result
        assert "decomposition_hint" in result
        assert len(result["title"]) > 0

    def test_generate_rule_based_no_tension(self, sample_context):
        from agent_core.creative.meta_goal_engine import MetaGoalEngine
        engine = MetaGoalEngine()
        result = engine.generate(None, sample_context)
        assert "Nowy kierunek" in result["title"]

    def test_generate_with_llm(self, sample_tension, sample_context):
        from agent_core.creative.meta_goal_engine import MetaGoalEngine
        llm_response = json.dumps({
            "title": "Wprowadz cross-domain learning z fizyki do chemii",
            "expected_value": "Nowe polaczenia miedzy domenami wiedzy",
            "decomposition_hint": "Planner: FETCH materialy laczace fizyka+chemia",
        })
        engine = MetaGoalEngine(_make_mock_llm(llm_response))
        result = engine.generate(sample_tension, sample_context)

        assert "cross-domain" in result["title"]

    def test_generate_llm_bad_json_fallback(self, sample_tension, sample_context):
        from agent_core.creative.meta_goal_engine import MetaGoalEngine
        engine = MetaGoalEngine(_make_mock_llm("This is not JSON"))
        result = engine.generate(sample_tension, sample_context)

        # Should fall back to rule-based
        assert "title" in result
        assert len(result["title"]) > 0

    def test_generate_llm_empty_title_fallback(self, sample_tension, sample_context):
        from agent_core.creative.meta_goal_engine import MetaGoalEngine
        llm_response = json.dumps({"title": "", "expected_value": "x"})
        engine = MetaGoalEngine(_make_mock_llm(llm_response))
        result = engine.generate(sample_tension, sample_context)

        # Empty title -> falls back to rule-based
        assert len(result["title"]) > 5

    def test_set_llm_fn(self):
        from agent_core.creative.meta_goal_engine import MetaGoalEngine
        engine = MetaGoalEngine()
        assert engine._llm_fn is None
        llm = _make_mock_llm("test")
        engine.set_llm_fn(llm)
        assert engine._llm_fn is llm

    def test_generate_with_memories_summary(self, sample_tension, sample_context):
        from agent_core.creative.meta_goal_engine import MetaGoalEngine
        llm_response = json.dumps({
            "title": "Meta-cel z kontekstem operatora",
            "expected_value": "Lepsze dopasowanie",
            "decomposition_hint": "Uwzglednij preferencje",
        })
        llm = _make_mock_llm(llm_response)
        engine = MetaGoalEngine(llm)
        result = engine.generate(sample_tension, sample_context, "Operator chce fizyki")

        # LLM should have been called with memories in prompt
        call_args = llm.call_args[0][0]
        assert "Operator chce fizyki" in call_args


# ==============================
# ReframeEngine
# ==============================

class TestReframeEngine:

    def test_reframe_rule_based(self):
        from agent_core.creative.reframe_engine import ReframeEngine
        engine = ReframeEngine()

        tension = DetectedTension.create(
            category=TensionCategory.MISALIGNMENT,
            description="Cele bez postepu od 72h",
            severity=0.6,
            evidence_refs=["goal-1"],
            pattern_window="72h",
        )
        reframes = engine.generate_reframes([tension], {})
        assert len(reframes) == 1
        assert isinstance(reframes[0], ReframeProposal)
        assert reframes[0].original_ref == tension.tension_id

    def test_reframe_filters_ineligible(self):
        from agent_core.creative.reframe_engine import ReframeEngine
        engine = ReframeEngine()

        # REPETITION is not eligible for reframe
        tension = DetectedTension.create(
            category=TensionCategory.REPETITION,
            description="Powtarzanie", severity=0.7,
            evidence_refs=[], pattern_window="24h",
        )
        reframes = engine.generate_reframes([tension], {})
        assert len(reframes) == 0

    def test_reframe_filters_low_severity(self):
        from agent_core.creative.reframe_engine import ReframeEngine
        engine = ReframeEngine()

        tension = DetectedTension.create(
            category=TensionCategory.MISALIGNMENT,
            description="Maly problem", severity=0.2,
            evidence_refs=[], pattern_window="24h",
        )
        reframes = engine.generate_reframes([tension], {})
        assert len(reframes) == 0

    def test_reframe_with_llm(self):
        from agent_core.creative.reframe_engine import ReframeEngine
        llm_response = json.dumps({
            "reframed_description": "Cele mozna podzelic na mniejsze kroki",
            "rationale": "Inkrementalne podejscie jest skuteczniejsze",
        })
        engine = ReframeEngine(_make_mock_llm(llm_response))

        tension = DetectedTension.create(
            category=TensionCategory.OVER_RESTRICTION,
            description="Zbyt wiele blokad K7",
            severity=0.6,
            evidence_refs=["k7-block-1"],
            pattern_window="24h",
        )
        reframes = engine.generate_reframes([tension], {})
        assert len(reframes) == 1
        assert "mniejsze kroki" in reframes[0].reframed_description

    def test_reframe_llm_fallback(self):
        from agent_core.creative.reframe_engine import ReframeEngine
        engine = ReframeEngine(MagicMock(side_effect=Exception("fail")))

        tension = DetectedTension.create(
            category=TensionCategory.MISALIGNMENT,
            description="Problem", severity=0.6,
            evidence_refs=[], pattern_window="24h",
        )
        reframes = engine.generate_reframes([tension], {})
        assert len(reframes) == 1  # Rule-based fallback worked


# ==============================
# ExplorationEngine
# ==============================

class TestExplorationEngine:

    def test_exploration_rule_based(self):
        from agent_core.creative.exploration_engine import ExplorationEngine
        engine = ExplorationEngine()

        tension = DetectedTension.create(
            category=TensionCategory.UNDER_EXPLORATION,
            description="Brak nowych tematow",
            severity=0.6,
            evidence_refs=["coverage-90"],
            pattern_window="7d",
        )
        programs = engine.generate_programs([tension], {})
        assert len(programs) == 1
        assert isinstance(programs[0], ExplorationProgram)

    def test_exploration_filters_ineligible(self):
        from agent_core.creative.exploration_engine import ExplorationEngine
        engine = ExplorationEngine()

        tension = DetectedTension.create(
            category=TensionCategory.REPETITION,
            description="Powtarzanie", severity=0.7,
            evidence_refs=[], pattern_window="24h",
        )
        programs = engine.generate_programs([tension], {})
        assert len(programs) == 0

    def test_exploration_max_2_programs(self):
        from agent_core.creative.exploration_engine import ExplorationEngine
        engine = ExplorationEngine()

        tensions = [
            DetectedTension.create(
                category=TensionCategory.UNDER_EXPLORATION,
                description=f"Gap {i}", severity=0.6,
                evidence_refs=[], pattern_window="7d",
            )
            for i in range(5)
        ]
        programs = engine.generate_programs(tensions, {})
        assert len(programs) <= 2

    def test_exploration_with_profile(self):
        from agent_core.creative.exploration_engine import ExplorationEngine
        from agent_core.creative.identity_profile import CognitiveProfile
        engine = ExplorationEngine()

        profile = CognitiveProfile(
            growth_trajectory="stable",
            dominant_traits=["ciekawska"],
            domain_strengths={"fizyka": 0.9},
            domain_weaknesses={"biologia": 0.3},
            capability_map={}, meta_goal_acceptance_rate=0.5,
            total_files=10, completed_files=5, coverage=0.5,
        )
        tension = DetectedTension.create(
            category=TensionCategory.EPISTEMIC_GAP,
            description="Niska retencja", severity=0.6,
            evidence_refs=[], pattern_window="7d",
        )
        programs = engine.generate_programs([tension], {}, profile)
        assert len(programs) == 1
        # Should include weak topic info
        assert "biologia" in programs[0].title

    def test_exploration_with_llm(self):
        from agent_core.creative.exploration_engine import ExplorationEngine
        llm_response = json.dumps({
            "title": "Eksploracja nanotechnologii",
            "question": "Jak nanotechnologia laczy fizyka i chemie?",
            "scope": "3 artykuly Wikipedia, 1 tydzien",
            "success_signal": "Nowe polaczenia w bazie wiedzy",
            "promotion_policy": "Jesli retencja > 60% po 2 cyklach",
        })
        engine = ExplorationEngine(_make_mock_llm(llm_response))

        tension = DetectedTension.create(
            category=TensionCategory.UNDER_EXPLORATION,
            description="Brak eksploracji", severity=0.6,
            evidence_refs=[], pattern_window="7d",
        )
        programs = engine.generate_programs([tension], {})
        assert len(programs) == 1
        assert "nanotechnologii" in programs[0].title


# ==============================
# TokenBudget RPM
# ==============================

class TestTokenBudgetRPM:

    def test_record_request(self, tmp_path):
        from agent_core.llm.token_budget import TokenBudget
        budget = TokenBudget(budget_file=str(tmp_path / "b.json"))
        budget.record_request()
        assert budget._get_current_rpm() == 1

    def test_rpm_limit(self, tmp_path):
        from agent_core.llm.token_budget import TokenBudget
        budget = TokenBudget(budget_file=str(tmp_path / "b.json"))

        now = time.time()
        budget._request_timestamps = [now - i * 0.5 for i in range(40)]
        assert budget.can_use_nim() is False

    def test_rpm_window_expiry(self, tmp_path):
        from agent_core.llm.token_budget import TokenBudget
        budget = TokenBudget(budget_file=str(tmp_path / "b.json"))

        old = time.time() - 61.0
        budget._request_timestamps = [old - i for i in range(40)]
        assert budget.can_use_nim() is True

    def test_rpm_prune_on_record(self, tmp_path):
        from agent_core.llm.token_budget import TokenBudget
        budget = TokenBudget(budget_file=str(tmp_path / "b.json"))

        old = time.time() - 120.0
        budget._request_timestamps = [old] * 50
        budget.record_request()
        # Old timestamps should be pruned
        assert len(budget._request_timestamps) == 1

    def test_status_dict_has_rpm(self, tmp_path):
        from agent_core.llm.token_budget import TokenBudget
        budget = TokenBudget(budget_file=str(tmp_path / "b.json"))
        budget.record_request()
        d = budget.get_status_dict()
        assert "rpm" in d
        assert d["rpm"]["current"] == 1
        assert d["rpm"]["limit"] == 40

    def test_token_tracking_still_works(self, tmp_path):
        from agent_core.llm.token_budget import TokenBudget
        budget = TokenBudget(budget_file=str(tmp_path / "b.json"))
        budget.record_usage(prompt_tokens=100, completion_tokens=50)
        today = budget.get_today_usage()
        assert today["total_tokens"] == 150
        assert today["calls"] == 1


# ==============================
# Facade Phase 2 Integration
# ==============================

class TestFacadePhase2:

    def test_reflect_with_phase2_components(self, tmp_path):
        """Full reflect() cycle uses Phase 2 components."""
        from agent_core.creative.facade import CreativeModule

        meta = tmp_path / "meta_data"
        mem = tmp_path / "memory"
        meta.mkdir()
        mem.mkdir()

        # Create minimal planner_decisions to trigger REPETITION tension
        now = time.time()
        decisions = [
            {"timestamp": now - i * 60, "action_type": "noop", "status": "ok"}
            for i in range(20)
        ]
        with open(meta / "planner_decisions.jsonl", "w") as f:
            for d in decisions:
                f.write(json.dumps(d) + "\n")

        # Create knowledge_index
        with open(mem / "knowledge_index.jsonl", "w") as f:
            for i in range(5):
                f.write(json.dumps({
                    "id": f"f{i}", "topic": "test", "status": "new",
                }) + "\n")

        module = CreativeModule(
            data_dir=str(meta),
            memory_dir=str(mem),
        )
        result = module.reflect(trigger="test")

        assert result["success"] is True
        assert "reframes" in result
        assert "explorations" in result
        assert "llm_enhanced" in result
        assert result["llm_enhanced"] is False  # No LLM wired

    def test_reflect_with_llm_wired(self, tmp_path):
        """Full reflect() with mocked LLM."""
        from agent_core.creative.facade import CreativeModule

        meta = tmp_path / "meta_data"
        mem = tmp_path / "memory"
        meta.mkdir()
        mem.mkdir()

        # Trigger REPETITION
        now = time.time()
        decisions = [
            {"timestamp": now - i * 60, "action_type": "noop", "status": "ok"}
            for i in range(20)
        ]
        with open(meta / "planner_decisions.jsonl", "w") as f:
            for d in decisions:
                f.write(json.dumps(d) + "\n")

        with open(mem / "knowledge_index.jsonl", "w") as f:
            for i in range(5):
                f.write(json.dumps({
                    "id": f"f{i}", "topic": "test", "status": "new",
                }) + "\n")

        llm_response = json.dumps({
            "title": "LLM-generated meta-goal",
            "expected_value": "Better learning",
            "decomposition_hint": "Do something smart",
        })
        llm = _make_mock_llm(llm_response)

        module = CreativeModule(
            data_dir=str(meta),
            memory_dir=str(mem),
            llm_fn=llm,
        )
        result = module.reflect(trigger="test")

        assert result["success"] is True
        assert result["llm_enhanced"] is True
        # LLM should have been called at least once
        assert llm.call_count >= 1

    def test_set_llm_fn_late_wiring(self, tmp_path):
        """set_llm_fn() wires LLM to all engines."""
        from agent_core.creative.facade import CreativeModule

        meta = tmp_path / "meta_data"
        mem = tmp_path / "memory"
        meta.mkdir()
        mem.mkdir()

        module = CreativeModule(data_dir=str(meta), memory_dir=str(mem))
        assert module._has_llm is False

        llm = _make_mock_llm("test")
        module.set_llm_fn(llm)
        assert module._has_llm is True
        assert module._meta_goal_engine._llm_fn is llm
        assert module._reframe_engine._llm_fn is llm
        assert module._exploration_engine._llm_fn is llm
        assert module._memory_summarizer._llm_fn is llm

    def test_get_status_includes_phase2(self, tmp_path):
        from agent_core.creative.facade import CreativeModule

        meta = tmp_path / "meta_data"
        mem = tmp_path / "memory"
        meta.mkdir()
        mem.mkdir()

        module = CreativeModule(data_dir=str(meta), memory_dir=str(mem))
        status = module.get_status()

        assert "total_reframes" in status
        assert "total_explorations" in status
        assert "llm_enhanced" in status


# ==============================
# CreativeEvaluator custom weights
# ==============================

class TestEvaluatorCustomWeights:

    def test_evaluate_with_custom_weights(self):
        from agent_core.creative.creative_evaluator import CreativeEvaluator

        evaluator = CreativeEvaluator()
        mg = MetaGoal.create(
            title="Test",
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.7,
            why_now="test",
            evidence_refs=["e1"],
            expected_value="test",
        )
        # Heavy weight on novelty
        custom = {
            "strategic_value": 0.1,
            "feasibility": 0.1,
            "novelty": 0.6,
            "risk": 0.1,
            "operator_relevance": 0.1,
        }
        result = evaluator.evaluate(mg, {}, weights=custom)
        assert "final_score" in result

    def test_batch_with_custom_weights(self):
        from agent_core.creative.creative_evaluator import CreativeEvaluator

        evaluator = CreativeEvaluator()
        goals = [
            MetaGoal.create(
                title=f"Test {i}",
                goal_type=MetaGoalType.EXPLORATION_META,
                priority=0.5 + i * 0.1,
                why_now="test",
                evidence_refs=["e1"],
                expected_value="test",
            )
            for i in range(3)
        ]
        custom = {"strategic_value": 0.5, "feasibility": 0.2,
                  "novelty": 0.1, "risk": 0.1, "operator_relevance": 0.1}
        results = evaluator.evaluate_batch(goals, {}, weights=custom)
        assert len(results) == 3
        # Should be sorted by final_score descending
        assert results[0]["final_score"] >= results[-1]["final_score"]
