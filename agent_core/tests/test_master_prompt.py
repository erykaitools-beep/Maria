"""Tests for master_prompt.py - single source of truth for Maria's identity."""

import pytest
from agent_core.llm.master_prompt import (
    BASE_IDENTITY, CONTEXT_BRIEF,
    build_base_prompt, build_full_prompt, build_compact_prompt, build_context_brief,
)


class TestBasePrompt:
    """Base identity prompt tests."""

    def test_base_prompt_returns_string(self):
        result = build_base_prompt()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_base_prompt_contains_maria_identity(self):
        result = build_base_prompt()
        assert "M.A.R.I.A." in result
        assert "Meta Analysis Recalibration Intelligence Architecture" in result

    def test_base_prompt_contains_personality_traits(self):
        result = build_base_prompt()
        assert "naturalny" in result
        assert "spokojny" in result
        assert "konkretny" in result

    def test_base_prompt_contains_operator_name(self):
        result = build_base_prompt()
        assert "Operator" in result or "M.A.R.I.A." in result

    def test_base_prompt_polish_default(self):
        result = build_base_prompt()
        assert "po polsku" in result

    def test_base_prompt_no_corporate_speak(self):
        result = build_base_prompt()
        assert "korpo" in result.lower()

    def test_base_prompt_action_oriented(self):
        result = build_base_prompt()
        assert "dzialaniu" in result.lower() or "dzialani" in result.lower()

    def test_base_prompt_no_lying(self):
        result = build_base_prompt()
        assert "kiam" in result.lower() or "klamac" in result.lower()

    def test_base_prompt_fallback_behavior(self):
        result = build_base_prompt()
        assert "fallback" in result.lower()


class TestFullPrompt:
    """Full prompt (OllamaBrain) tests."""

    def test_full_prompt_base_only(self):
        result = build_full_prompt()
        assert "M.A.R.I.A." in result
        # No context sections when no args
        assert "[Kontekst czasowy:" not in result

    def test_full_prompt_with_time(self):
        result = build_full_prompt(time_context="Piatek, 10.04.2026, 22:15")
        assert "Piatek, 10.04.2026" in result
        assert "[Kontekst czasowy:" in result

    def test_full_prompt_with_identity(self):
        result = build_full_prompt(identity_context="Sesja #42, uptime 12h")
        assert "[Tozsamosc:" in result
        assert "Sesja #42" in result

    def test_full_prompt_with_user(self):
        result = build_full_prompt(user_context="[Profil] User lubi AI")
        assert "User lubi AI" in result

    def test_full_prompt_with_work(self):
        result = build_full_prompt(work_context="Planner: LEARN neuroscience")
        assert "[Aktualna praca:" in result
        assert "neuroscience" in result

    def test_full_prompt_operational_summary_replaces_awareness(self):
        result = build_full_prompt(
            awareness_context="[Awareness] 50 files",
            operational_summary="[Operational] 100 beliefs",
        )
        assert "[Operational] 100 beliefs" in result
        assert "[Awareness] 50 files" not in result

    def test_full_prompt_awareness_when_no_operational(self):
        result = build_full_prompt(awareness_context="[Awareness] 50 files")
        assert "[Awareness] 50 files" in result

    def test_full_prompt_grounding_instruction(self):
        result = build_full_prompt(grounding_active=True)
        assert "danych operacyjnych" in result

    def test_full_prompt_no_grounding_by_default(self):
        result = build_full_prompt()
        assert "danych operacyjnych" not in result

    def test_full_prompt_all_sections(self):
        result = build_full_prompt(
            time_context="Now",
            identity_context="ID",
            user_context="User",
            work_context="Work",
            conversation_context="Conv",
            awareness_context="Aware",
            grounding_active=True,
        )
        assert "Now" in result
        assert "ID" in result
        assert "User" in result
        assert "Work" in result
        assert "Conv" in result
        assert "Aware" in result
        assert "danych operacyjnych" in result


class TestCompactPrompt:
    """Compact prompt (NIM/Web UI) tests."""

    def test_compact_base_only(self):
        result = build_compact_prompt()
        assert "M.A.R.I.A." in result
        assert "[Kontekst czasowy:" not in result

    def test_compact_with_time(self):
        result = build_compact_prompt(time_context="Sobota rano")
        assert "Sobota rano" in result

    def test_compact_with_user(self):
        result = build_compact_prompt(user_context="[Profil] User")
        assert "User" in result

    def test_compact_no_work_context(self):
        # Compact prompt doesn't accept work_context
        result = build_compact_prompt(time_context="Now")
        assert "[Aktualna praca:" not in result


class TestContextBrief:
    """Context brief for external models."""

    def test_brief_returns_string(self):
        result = build_context_brief()
        assert isinstance(result, str)
        assert len(result) > 50

    def test_brief_mentions_maria(self):
        result = build_context_brief()
        assert "M.A.R.I.A." in result

    def test_brief_mentions_local_first(self):
        result = build_context_brief()
        assert "local-first" in result

    def test_brief_in_english(self):
        result = build_context_brief()
        assert "You are helping" in result

    def test_brief_mentions_architecture(self):
        result = build_context_brief()
        assert "agent_core" in result

    def test_brief_mentions_values(self):
        result = build_context_brief()
        assert "action over talk" in result
        assert "graceful fallback" in result
