"""
Tests for Creative Module expert_fn integration (Phase C).

Verifies ExplorationEngine uses ChatGPT for richer brainstorming.
"""

import pytest
from unittest.mock import MagicMock

from agent_core.creative.exploration_engine import ExplorationEngine
from agent_core.creative.creative_model import (
    DetectedTension, TensionCategory,
)


def _make_tension(category=TensionCategory.UNDER_EXPLORATION, severity=0.6):
    return DetectedTension(
        tension_id="t-test",
        category=category,
        description="Test tension",
        severity=severity,
        evidence_refs=["test"],
        pattern_window="7d",
    )


class TestExplorationEngineExpert:
    """Tests for expert_fn in ExplorationEngine."""

    def test_set_expert_fn(self):
        engine = ExplorationEngine()
        assert engine._expert_fn is None
        engine.set_expert_fn(lambda p: "answer")
        assert engine._expert_fn is not None

    def test_expert_used_before_llm(self):
        """Expert (ChatGPT) should be tried before NIM."""
        expert_fn = MagicMock(return_value='{"title":"Expert plan","question":"What?","scope":"all","success_signal":"done","promotion_policy":"always"}')
        llm_fn = MagicMock(return_value="should not be called")

        engine = ExplorationEngine(llm_fn=llm_fn)
        engine.set_expert_fn(expert_fn)

        tension = _make_tension()
        programs = engine.generate_programs([tension], {"learning_state": {"coverage": 1.0}})

        assert len(programs) == 1
        assert programs[0].title == "Expert plan"
        expert_fn.assert_called_once()
        llm_fn.assert_not_called()

    def test_fallback_to_llm_when_expert_fails(self):
        """If expert returns None, fall back to NIM LLM."""
        expert_fn = MagicMock(return_value=None)
        llm_fn = MagicMock(return_value='{"title":"NIM plan","question":"Q","scope":"s","success_signal":"ss","promotion_policy":"pp"}')

        engine = ExplorationEngine(llm_fn=llm_fn)
        engine.set_expert_fn(expert_fn)

        tension = _make_tension()
        programs = engine.generate_programs([tension], {"learning_state": {"coverage": 0.8}})

        assert len(programs) == 1
        assert programs[0].title == "NIM plan"
        expert_fn.assert_called_once()
        llm_fn.assert_called_once()

    def test_expert_non_json_response(self):
        """If expert returns plain text, use it as freeform exploration."""
        expert_fn = MagicMock(return_value="Proponuje zbadac biologiczne mechanizmy adaptacji do stresu")
        engine = ExplorationEngine()
        engine.set_expert_fn(expert_fn)

        tension = _make_tension()
        programs = engine.generate_programs([tension], {"learning_state": {"coverage": 0.9}})

        assert len(programs) == 1
        assert "adaptacji" in programs[0].question or "Eksploracja" in programs[0].title

    def test_expert_exception_handled(self):
        """Expert exception should not crash, fall back to rules."""
        expert_fn = MagicMock(side_effect=Exception("network error"))
        engine = ExplorationEngine()
        engine.set_expert_fn(expert_fn)

        tension = _make_tension()
        programs = engine.generate_programs([tension], {})

        # Should fall back to rule-based
        assert len(programs) == 1
        assert "Eksploracja" in programs[0].title

    def test_no_expert_uses_llm(self):
        """Without expert_fn, LLM is used directly."""
        llm_fn = MagicMock(return_value='{"title":"NIM only","question":"Q","scope":"s","success_signal":"ss","promotion_policy":"pp"}')
        engine = ExplorationEngine(llm_fn=llm_fn)

        tension = _make_tension()
        programs = engine.generate_programs([tension], {"learning_state": {"coverage": 0.5}})

        assert len(programs) == 1
        assert programs[0].title == "NIM only"


class TestFacadeExpertFn:
    """Tests for CreativeModule.set_expert_fn()."""

    def test_facade_has_set_expert_fn(self):
        from agent_core.creative.facade import CreativeModule
        module = CreativeModule()
        assert hasattr(module, "set_expert_fn")

    def test_facade_wires_to_exploration_engine(self):
        from agent_core.creative.facade import CreativeModule
        module = CreativeModule()
        mock_fn = MagicMock()
        module.set_expert_fn(mock_fn)
        assert module._exploration_engine._expert_fn is mock_fn
