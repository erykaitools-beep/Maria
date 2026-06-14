"""Tests for Conversation-Driven Learning.

Covers:
1. Learning intent detection (Polish + English patterns)
2. process_user_message integration
3. Goal creation from conversation
"""

import pytest
from unittest.mock import MagicMock, patch

from agent_core.perception.learning_intent import (
    detect_learning_intent, detect_cancel_intent,
)
from agent_core.perception.conversation_learning import process_user_message
from agent_core.tests.spec_helpers import specced
from agent_core.registry.shared_context import SharedContext
from agent_core.perception.buffer import PerceptionBuffer
from agent_core.goals.store import GoalStore
from agent_core.semantic import SemanticMemory


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
        ctx = specced(SharedContext)

        # spec-blocked: PerceptionBuffer defines __len__ -> autospec returns 0 -> falsy -> if ctx.perception_buffer: skips push
        ctx.perception_buffer = MagicMock()
        ctx.perception_buffer.push = MagicMock()

        # GoalStore mock
        ctx.goal_store = specced(GoalStore)
        ctx.goal_store.create.return_value = "goal-test123"

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
        ctx.semantic_search = specced(SemanticMemory)
        process_user_message("naucz sie o genetyce", ctx)
        ctx.semantic_search.index_text.assert_called_once()


# =========================================================================
# 4. Cancel intent detection
# =========================================================================

class TestCancelIntent:
    def test_zapomnij(self):
        r = detect_cancel_intent("zapomnij o nauce fizyki")
        assert r is not None
        assert "fizyki" in r["topic"]
        assert r["action"] == "cancel"

    def test_anuluj(self):
        r = detect_cancel_intent("anuluj nauke o chemii")
        assert r is not None
        assert "chemii" in r["topic"]

    def test_przerwij(self):
        r = detect_cancel_intent("przerwij nauke o biologii")
        assert r is not None
        assert "biologii" in r["topic"]

    def test_nie_ucz_sie(self):
        r = detect_cancel_intent("nie ucz sie o matematyce")
        assert r is not None
        assert "matematyce" in r["topic"]

    def test_przestan_uczyc(self):
        r = detect_cancel_intent("przestan sie uczyc o logice")
        assert r is not None
        assert "logice" in r["topic"]

    def test_cancel_english(self):
        r = detect_cancel_intent("cancel learning about physics")
        assert r is not None
        assert "physics" in r["topic"]

    def test_stop_english(self):
        r = detect_cancel_intent("stop learning about math")
        assert r is not None
        assert "math" in r["topic"]

    def test_forget_english(self):
        r = detect_cancel_intent("forget about biology")
        assert r is not None
        assert "biology" in r["topic"]

    def test_no_cancel_normal_message(self):
        assert detect_cancel_intent("jak sie masz?") is None
        assert detect_cancel_intent("naucz sie o fizyce") is None

    def test_no_cancel_short(self):
        assert detect_cancel_intent("") is None
        assert detect_cancel_intent("hi") is None

    def test_zrezygnuj(self):
        r = detect_cancel_intent("zrezygnuj z nauki o astronomii")
        assert r is not None
        assert "astronomii" in r["topic"]

    def test_olej(self):
        r = detect_cancel_intent("olej temat historii")
        assert r is not None
        assert "historii" in r["topic"]


# ============================================================
# Operational Intent Tests
# ============================================================

from agent_core.perception.learning_intent import detect_operational_intent


class TestOperationalIntent:
    def test_fetch_pl(self):
        r = detect_operational_intent("zrob fetch")
        assert r is not None
        assert r["action"] == "fetch"

    def test_fetch_pl2(self):
        r = detect_operational_intent("pobierz nowe materialy")
        assert r is not None
        assert r["action"] == "fetch"

    def test_evaluate_pl(self):
        r = detect_operational_intent("zrob ewaluacje")
        assert r is not None
        assert r["action"] == "evaluate"

    def test_evaluate_pl2(self):
        r = detect_operational_intent("ocen swoje postepy")
        assert r is not None
        assert r["action"] == "evaluate"

    def test_critique_pl(self):
        r = detect_operational_intent("uruchom krytyke")
        assert r is not None
        assert r["action"] == "critique"

    def test_critique_pl2(self):
        r = detect_operational_intent("sprawdz jakosc wiedzy")
        assert r is not None
        assert r["action"] == "critique"

    def test_self_analyze_pl(self):
        r = detect_operational_intent("przeanalizuj sie")
        assert r is not None
        assert r["action"] == "self_analyze"

    def test_self_analyze_pl2(self):
        r = detect_operational_intent("zrob autoanalize")
        assert r is not None
        assert r["action"] == "self_analyze"

    def test_creative_pl(self):
        r = detect_operational_intent("zrob refleksje")
        assert r is not None
        assert r["action"] == "creative"

    def test_validate_pl(self):
        r = detect_operational_intent("zwaliduj wiedze")
        assert r is not None
        assert r["action"] == "validate"

    def test_exam_with_topic(self):
        r = detect_operational_intent("zrob egzamin z fizyki")
        assert r is not None
        assert r["action"] == "exam"
        assert "fizyki" in r["topic"]

    def test_exam_verify(self):
        r = detect_operational_intent("sprawdz moja wiedze o chemii")
        assert r is not None
        assert r["action"] == "exam"
        assert "chemii" in r["topic"]

    def test_fetch_en(self):
        r = detect_operational_intent("fetch new materials")
        assert r is not None
        assert r["action"] == "fetch"

    def test_evaluate_en(self):
        r = detect_operational_intent("run evaluation")
        assert r is not None
        assert r["action"] == "evaluate"

    def test_critique_en(self):
        r = detect_operational_intent("run critique")
        assert r is not None
        assert r["action"] == "critique"

    def test_no_intent_normal_message(self):
        assert detect_operational_intent("jak sie masz?") is None
        assert detect_operational_intent("opowiedz mi o fizyce") is None

    def test_no_intent_short(self):
        assert detect_operational_intent("") is None
        assert detect_operational_intent("hi") is None
