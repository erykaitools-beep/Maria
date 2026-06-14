"""Tests for Maria-side speech intent + confabulation detection.

Closes Bug 3 + Bug 5 from 24h autonomy postmortem (2026-05-14).

Covers:
1. Intent detection in Maria responses (1st person future/present)
2. Past-tense confabulation claim detection
3. Topic extraction edge cases
"""

import pytest

from agent_core.perception.maria_speech_intent import (
    detect_maria_intent,
    detect_past_claim,
    detect_third_party_claim,
)


# =========================================================================
# 1. Intent detection - Polish (1st person future/present)
# =========================================================================


class TestMariaIntentPolish:
    def test_pobior_e_materialy(self):
        r = detect_maria_intent("Pobiore nowe materialy o fizyce.")
        assert r is not None
        assert r["action"] == "fetch"

    def test_pobior_e_artykul(self):
        r = detect_maria_intent("Pobiore ten artykul o termodynamice.")
        assert r is not None
        assert r["action"] == "fetch"

    def test_sciagne_artykuly(self):
        r = detect_maria_intent("Sciagne nowe artykuly z arxiv.")
        assert r is not None
        assert r["action"] == "fetch"

    def test_egzamin_z_topic(self):
        r = detect_maria_intent("Zrobie egzamin z termodynamiki.")
        assert r is not None
        assert r["action"] == "exam"
        assert "termodynamik" in r.get("topic", "").lower()

    def test_przeegzaminuje(self):
        r = detect_maria_intent("Przeegzaminuje sie z mechaniki kwantowej.")
        assert r is not None
        assert r["action"] == "exam"
        assert "mechanik" in r.get("topic", "").lower()

    def test_uruchomie_krytyke(self):
        r = detect_maria_intent("Uruchomie krytyke dla obecnych celow.")
        assert r is not None
        assert r["action"] == "critique"

    def test_zrobie_krytyke(self):
        r = detect_maria_intent("Zrobie krytyke modulow.")
        assert r is not None
        assert r["action"] == "critique"

    def test_przeprowadze_autoanalize(self):
        r = detect_maria_intent("Przeprowadze autoanalize stanu.")
        assert r is not None
        assert r["action"] == "self_analyze"

    def test_zrobie_ewaluacje(self):
        r = detect_maria_intent("Zrobie ewaluacje postepow nauki.")
        assert r is not None
        assert r["action"] == "evaluate"

    def test_zrobie_refleksje(self):
        r = detect_maria_intent("Zrobie refleksje kreatywna nad tym.")
        assert r is not None
        assert r["action"] == "creative"

    def test_zwaliduje_wiedze(self):
        r = detect_maria_intent("Zwaliduje wiedze krzyzowo.")
        assert r is not None
        assert r["action"] == "validate"

    def test_naucze_sie(self):
        r = detect_maria_intent("Naucze sie o teorii grafow.")
        assert r is not None
        assert r["action"] == "learn"
        assert "graf" in r.get("topic", "").lower()


# =========================================================================
# 2. Planner delegation (special action)
# =========================================================================


class TestPlannerDelegation:
    def test_zlece_plannerowi(self):
        r = detect_maria_intent("Zlece plannerowi nowy plan nauki.")
        assert r is not None
        assert r["action"] == "planner_delegation"

    def test_zlece_to_planerowi(self):
        r = detect_maria_intent("Zlece to planerowi: napisz skrypt.")
        assert r is not None
        assert r["action"] == "planner_delegation"

    def test_przekaze_plannerowi(self):
        r = detect_maria_intent("Przekaze to plannerowi do realizacji.")
        assert r is not None
        assert r["action"] == "planner_delegation"


# =========================================================================
# 3. Intent detection - English (light coverage)
# =========================================================================


class TestMariaIntentEnglish:
    def test_i_will_run_critique(self):
        r = detect_maria_intent("I will run a critique on current goals.")
        assert r is not None
        assert r["action"] == "critique"

    def test_i_will_fetch(self):
        r = detect_maria_intent("I will fetch new materials about physics.")
        assert r is not None
        assert r["action"] == "fetch"

    def test_i_will_take_exam(self):
        r = detect_maria_intent("I will take an exam on thermodynamics.")
        assert r is not None
        assert r["action"] == "exam"


# =========================================================================
# 4. No-intent guards (observations, questions, denials)
# =========================================================================


class TestNoIntent:
    def test_observation_not_intent(self):
        # Pure observation about state - no action commitment
        assert detect_maria_intent("Widze w logach 3 nowe akcje exam.") is None

    def test_question_not_intent(self):
        assert detect_maria_intent("Czy chcesz, zebym zrobila egzamin?") is None

    def test_past_report_not_intent(self):
        # Past tense should NOT trigger future-intent detection
        assert detect_maria_intent("Wczoraj zrobilam ewaluacje.") is None

    def test_empty_text(self):
        assert detect_maria_intent("") is None
        assert detect_maria_intent("ok") is None
        assert detect_maria_intent(None) is None  # type: ignore

    def test_general_chat(self):
        assert detect_maria_intent("Czesc Eryk, jak sie czujesz?") is None
        assert detect_maria_intent("To bardzo ciekawe pytanie.") is None


# =========================================================================
# 5. Past-tense confabulation claims
# =========================================================================


class TestConfabulationClaims:
    def test_napisalam_skrypt(self):
        r = detect_past_claim("Napisalam skrypt naprawiajacy parser.")
        assert r is not None
        assert "napisalam" in r["matched"].lower()

    def test_napisalam_fix(self):
        r = detect_past_claim("Wlasnie napisalam fix do tego buga.")
        assert r is not None

    def test_uruchomilam_kod(self):
        r = detect_past_claim("Uruchomilam ten kod 5 minut temu.")
        assert r is not None

    def test_uruchomilam_polecenie(self):
        r = detect_past_claim("Uruchomilam polecenie pytest -v.")
        assert r is not None

    def test_zmodyfikowalam_parser(self):
        r = detect_past_claim("Zmodyfikowalam parser w exam_agent.py.")
        assert r is not None

    def test_wykonalam_akcje(self):
        r = detect_past_claim("Wykonalam akcje pobierania materialow.")
        assert r is not None

    def test_zrobilam_fix(self):
        r = detect_past_claim("Zrobilam fix do parsera dzis rano.")
        assert r is not None

    def test_naprawilam_parser(self):
        r = detect_past_claim("Naprawilam parser exam_agent.")
        assert r is not None

    def test_pobralam_artykul(self):
        r = detect_past_claim("Pobralam ten artykul wczoraj.")
        assert r is not None

    def test_zacommitowalam(self):
        r = detect_past_claim("Zacommitowalam zmiany.")
        assert r is not None

    def test_english_claim(self):
        r = detect_past_claim("I have written the script already.")
        assert r is not None


# =========================================================================
# 6. No-claim guards
# =========================================================================


class TestNoClaim:
    def test_future_intent_not_claim(self):
        # Future tense should NOT trigger past-claim detector
        assert detect_past_claim("Pobiore nowe materialy.") is None
        assert detect_past_claim("Zrobie egzamin z fizyki.") is None
        assert detect_past_claim("Napisze skrypt.") is None

    def test_observation_not_claim(self):
        assert detect_past_claim("Widze 80% sukcesu w testach.") is None
        assert detect_past_claim("Ostatnia akcja byla 5 minut temu.") is None

    def test_user_action_not_claim(self):
        # Past tense about USER actions - shouldn't trigger
        # (patterns require 1st-person verb endings -lam/-lam)
        assert detect_past_claim("Zrobiles fix do parsera.") is None
        assert detect_past_claim("Pobrales artykul.") is None

    def test_empty_or_short(self):
        assert detect_past_claim("") is None
        assert detect_past_claim("hi") is None
        assert detect_past_claim(None) is None  # type: ignore


# =========================================================================
# 7. Topic extraction edge cases
# =========================================================================


class TestTopicExtraction:
    def test_topic_cut_at_period(self):
        r = detect_maria_intent("Zrobie egzamin z termodynamiki. Potem zrobie cos innego.")
        assert r is not None
        topic = r.get("topic", "")
        assert "termodynamiki" in topic
        assert "potem" not in topic.lower()

    def test_long_topic_truncated(self):
        long_text = "Naucze sie o " + ("bardzo dlugim temacie " * 20)
        r = detect_maria_intent(long_text)
        assert r is not None
        # Should have topic but not insanely long
        if "topic" in r:
            assert len(r["topic"]) <= 80

    def test_topic_trimmed_punctuation(self):
        r = detect_maria_intent("Naucze sie o teorii grafow!")
        assert r is not None
        topic = r.get("topic", "")
        # No trailing exclamation
        assert not topic.endswith("!")


# =========================================================================
# 8. Third-party confabulation patterns (konfabulacja-2.0/3.0)
# =========================================================================


class TestThirdPartyClaims:
    def test_planer_wykonal(self):
        r = detect_third_party_claim("Planer wykonal moje polecenie 5 min temu.")
        assert r is not None
        assert r["category"] == "planner"

    def test_planer_otrzymal_zaczyna(self):
        r = detect_third_party_claim(
            "Planer otrzymal polecenie i zaczyna wykonywac skrypt."
        )
        assert r is not None
        assert r["category"] == "planner"

    def test_system_uruchomil(self):
        r = detect_third_party_claim("System uruchomil tej akcji w tle.")
        assert r is not None
        assert r["category"] == "system"

    def test_skrypt_zostal_wykonany(self):
        r = detect_third_party_claim("Skrypt zostal wykonany pomyslnie.")
        assert r is not None
        assert r["category"] == "executor"

    def test_polecenie_przekazane(self):
        r = detect_third_party_claim("Polecenie zostalo wyslane do plannera.")
        assert r is not None
        assert r["category"] == "polecenie"

    def test_fake_grounded_widze_w_logach(self):
        r = detect_third_party_claim("Widze w logach: cos sie dzieje.")
        assert r is not None
        assert r["category"] == "fake_grounded"

    def test_fake_grounded_zrodlo_danych(self):
        r = detect_third_party_claim("Zrodlo danych: action_audit.jsonl")
        assert r is not None
        assert r["category"] == "fake_grounded"


class TestNoThirdPartyClaim:
    def test_observation_not_third_party(self):
        assert detect_third_party_claim(
            "Mam 3 aktywne cele w tej chwili."
        ) is None

    def test_question_not_third_party(self):
        assert detect_third_party_claim(
            "Czy chcesz, zebym zlecila planerowi nowe zadanie?"
        ) is None

    def test_empty_or_short(self):
        assert detect_third_party_claim("") is None
        assert detect_third_party_claim("ok") is None
        assert detect_third_party_claim(None) is None  # type: ignore

    def test_future_intent_not_third_party_claim(self):
        assert detect_third_party_claim("Zlece plannerowi to zadanie.") is None
