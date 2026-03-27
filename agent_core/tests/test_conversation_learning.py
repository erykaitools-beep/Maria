"""Tests for Conversation-Driven Learning.

Covers:
1. Learning intent detection (Polish + English patterns)
2. process_user_message integration
3. Goal creation from conversation
"""

import pytest
from unittest.mock import MagicMock, patch

from agent_core.perception.learning_intent import detect_learning_intent
from agent_core.perception.conversation_learning import process_user_message


# =========================================================================
# 1. Intent detection - Polish
# =========================================================================

class TestLearningIntentPolish:
    def test_naucz_sie(self):
        r = detect_learning_intent("naucz sie o fizyce kwantowej")
        assert r is not None
        assert r["topic"] == "fizyce kwantowej"
        assert r["action"] == "learn"

    def test_poczytaj(self):
        r = detect_learning_intent("poczytaj o genetyce")
        assert r is not None
        assert r["topic"] == "genetyce"

    def test_dowiedz_sie(self):
        r = detect_learning_intent("dowiedz sie o historii Polski")
        assert r is not None
        assert "historii Polski" in r["topic"]

    def test_przeczytaj(self):
        r = detect_learning_intent("przeczytaj o astronomii")
        assert r is not None
        assert r["topic"] == "astronomii"

    def test_poznaj(self):
        r = detect_learning_intent("poznaj temat sztucznej inteligencji")
        assert r is not None
        assert "sztucznej inteligencji" in r["topic"]

    def test_zgłęb(self):
        r = detect_learning_intent("zgłęb temat ekologii")
        assert r is not None
        assert "ekologii" in r["topic"]

    def test_zbadaj(self):
        r = detect_learning_intent("zbadaj temat kosmologii")
        assert r is not None
        assert r["action"] == "explore"

    def test_fetch_znajdz(self):
        r = detect_learning_intent("znajdz materialy o chemii")
        assert r is not None
        assert r["action"] == "fetch"

    def test_interest(self):
        r = detect_learning_intent("interesuje mnie biologia morska")
        assert r is not None
        assert "biologia morska" in r["topic"]

    def test_chce_zeby(self):
        r = detect_learning_intent("chce zebys sie nauczyla o matematyce")
        assert r is not None
        assert "matematyce" in r["topic"]

    def test_mozesz(self):
        r = detect_learning_intent("mozesz poczytac o filozofii")
        assert r is not None
        assert "filozofii" in r["topic"]

    def test_ucz_sie(self):
        r = detect_learning_intent("ucz sie o logice formalnej")
        assert r is not None
        assert "logice formalnej" in r["topic"]

    def test_no_intent_normal_message(self):
        assert detect_learning_intent("jak sie masz?") is None
        assert detect_learning_intent("opowiedz mi dowcip") is None
        assert detect_learning_intent("co to jest fotosynteza?") is None

    def test_no_intent_short(self):
        assert detect_learning_intent("") is None
        assert detect_learning_intent("hi") is None

    def test_strips_trailing_punctuation(self):
        r = detect_learning_intent("naucz sie o fizyce!")
        assert r is not None
        assert r["topic"] == "fizyce"

    def test_case_insensitive(self):
        r = detect_learning_intent("NAUCZ SIE O BIOLOGII")
        assert r is not None
        assert "BIOLOGII" in r["topic"]


# =========================================================================
# 2. Intent detection - English
# =========================================================================

class TestLearningIntentEnglish:
    def test_learn_about(self):
        r = detect_learning_intent("learn about quantum physics")
        assert r is not None
        assert r["topic"] == "quantum physics"
        assert r["language"] == "en"

    def test_study(self):
        r = detect_learning_intent("study machine learning")
        assert r is not None
        assert "machine learning" in r["topic"]

    def test_read_about(self):
        r = detect_learning_intent("read about chemistry")
        assert r is not None
        assert r["topic"] == "chemistry"

    def test_fetch(self):
        r = detect_learning_intent("fetch articles about biology")
        assert r is not None
        assert r["action"] == "fetch"


# =========================================================================
# 3. process_user_message integration
# =========================================================================

class TestProcessUserMessage:
    def _make_ctx(self, tmp_path=None):
        ctx = MagicMock()
        ctx.perception_buffer = MagicMock()
        ctx.perception_buffer.push = MagicMock()

        # GoalStore mock
        ctx.goal_store = MagicMock()
        ctx.goal_store.create = MagicMock(return_value="goal-test123")
        ctx.goal_store.save = MagicMock()

        ctx.semantic_search = None
        return ctx

    def test_learning_intent_creates_goal(self):
        ctx = self._make_ctx()
        result = process_user_message("naucz sie o fizyce", ctx)

        assert result is not None
        assert result["topic"] == "fizyce"
        assert result["goal_id"] == "goal-test123"
        ctx.goal_store.create.assert_called_once()
        ctx.goal_store.save.assert_called_once()

    def test_no_intent_returns_none(self):
        ctx = self._make_ctx()
        result = process_user_message("jak sie masz?", ctx)
        assert result is None
        ctx.goal_store.create.assert_not_called()

    def test_always_pushes_perception_event(self):
        ctx = self._make_ctx()
        process_user_message("zwykla wiadomosc", ctx)
        ctx.perception_buffer.push.assert_called_once()

    def test_perception_event_for_learning(self):
        ctx = self._make_ctx()
        process_user_message("poczytaj o astronomii", ctx)
        ctx.perception_buffer.push.assert_called_once()

    def test_no_goal_store_graceful(self):
        ctx = self._make_ctx()
        ctx.goal_store = None
        result = process_user_message("naucz sie o biologii", ctx)
        assert result is not None
        assert result["goal_id"] is None

    def test_no_perception_buffer_graceful(self):
        ctx = self._make_ctx()
        ctx.perception_buffer = None
        result = process_user_message("naucz sie o chemii", ctx)
        assert result is not None  # Still detects intent

    def test_telegram_channel(self):
        ctx = self._make_ctx()
        result = process_user_message("naucz sie o fizyce", ctx, channel="telegram")
        assert result is not None
        # Check goal metadata
        goal_arg = ctx.goal_store.create.call_args[0][0]
        assert goal_arg.metadata["channel"] == "telegram"

    def test_semantic_indexing(self):
        ctx = self._make_ctx()
        ctx.semantic_search = MagicMock()
        process_user_message("naucz sie o genetyce", ctx)
        ctx.semantic_search.index_text.assert_called_once()
