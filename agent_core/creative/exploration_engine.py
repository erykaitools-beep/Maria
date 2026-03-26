"""LLM-enhanced exploration program design engine.

Generates ExplorationProgram objects for UNDER_EXPLORATION and EPISTEMIC_GAP
tensions. Falls back to template-based generation.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from agent_core.creative.creative_model import (
    DetectedTension, ExplorationProgram, TensionCategory,
)
from agent_core.creative.identity_profile import CognitiveProfile
from agent_core.creative.llm_utils import safe_llm_call, try_parse_json

logger = logging.getLogger(__name__)

# Tension categories eligible for exploration programs
_EXPLORE_CATEGORIES = {
    TensionCategory.UNDER_EXPLORATION,
    TensionCategory.EPISTEMIC_GAP,
}

# Rule-based exploration templates
_RULE_PROGRAMS = {
    TensionCategory.UNDER_EXPLORATION: {
        "title": "Eksploracja nowych dziedzin wiedzy",
        "question": "Jakie tematy interdyscyplinarne moga poszerzyc baze wiedzy?",
        "scope": "Pobierz 3-5 artykulow z nowych dziedzin (Wikipedia/RSS), przysw jako materia",
        "success_signal": "Nowe tematy w knowledge_index, coverage wzroslo",
        "promotion_policy": "Jesli nowe tematy maja retencje > 50%, promuj do stalego celu",
    },
    TensionCategory.EPISTEMIC_GAP: {
        "title": "Uzupelnienie luk w wiedzy",
        "question": "Ktore tematy maja najnizsza retencje i wymagaja powtorki?",
        "scope": "Powtorz egzaminy z 3 najslabszych tematow, uzupelnij material",
        "success_signal": "Retencja w slabych tematach wzrosla powyzej 60%",
        "promotion_policy": "Jesli retencja wzrasta po 2 cyklach, kontynuuj jako cel",
    },
}


class ExplorationEngine:
    """Designs exploration programs using NIM or templates."""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn
        self._expert_fn: Optional[Callable[[str], str]] = None

    def set_llm_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        """Set or update LLM function (late wiring)."""
        self._llm_fn = fn

    def set_expert_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        """Set expert LLM (ChatGPT) for richer exploration brainstorming."""
        self._expert_fn = fn

    def generate_programs(
        self,
        tensions: List[DetectedTension],
        context: Dict[str, Any],
        profile: Optional[CognitiveProfile] = None,
    ) -> List[ExplorationProgram]:
        """
        Generate exploration programs for eligible tensions.

        Args:
            tensions: All detected tensions
            context: Strategic context dict
            profile: Cognitive profile (for domain awareness)

        Returns:
            List of ExplorationProgram objects (max 2)
        """
        eligible = [
            t for t in tensions
            if t.category in _EXPLORE_CATEGORIES and t.severity >= 0.4
        ]

        if not eligible:
            return []

        programs = []
        for tension in eligible[:2]:  # Max 2 programs per cycle
            # Try expert (ChatGPT) for richer brainstorming
            if self._expert_fn is not None:
                program = self._generate_with_expert(tension, context, profile)
                if program:
                    programs.append(program)
                    continue

            # Try NIM LLM
            if self._llm_fn is not None:
                program = self._generate_with_llm(tension, context, profile)
                if program:
                    programs.append(program)
                    continue

            # Rule-based fallback
            program = self._generate_rule_based(tension, context, profile)
            if program:
                programs.append(program)

        return programs

    def _generate_rule_based(
        self,
        tension: DetectedTension,
        context: Dict[str, Any],
        profile: Optional[CognitiveProfile],
    ) -> Optional[ExplorationProgram]:
        """Generate exploration program from templates."""
        template = _RULE_PROGRAMS.get(tension.category)
        if not template:
            return None

        title = template["title"]
        # Enrich with domain info if available
        if profile and profile.domain_weaknesses:
            weak_topics = list(profile.domain_weaknesses.keys())[:3]
            if weak_topics and tension.category == TensionCategory.EPISTEMIC_GAP:
                title = f"Uzupelnienie luk: {', '.join(weak_topics[:2])}"

        return ExplorationProgram.create(
            title=title,
            question=template["question"],
            scope=template["scope"],
            success_signal=template["success_signal"],
            promotion_policy=template["promotion_policy"],
        )

    def _generate_with_expert(
        self,
        tension: DetectedTension,
        context: Dict[str, Any],
        profile: Optional[CognitiveProfile],
    ) -> Optional[ExplorationProgram]:
        """Generate exploration program via ChatGPT (richer, open-ended)."""
        learning = context.get("learning_state", {})
        coverage = learning.get("coverage", 0)

        domains_info = ""
        if profile:
            if profile.domain_strengths:
                strong = list(profile.domain_strengths.keys())[:5]
                domains_info += f"Moje mocne tematy: {', '.join(strong)}\n"
            if profile.domain_weaknesses:
                weak = list(profile.domain_weaknesses.keys())[:5]
                domains_info += f"Moje slabe tematy: {', '.join(weak)}\n"

        prompt = (
            "Jestem M.A.R.I.A. - autonomiczny agent AI uczacy sie z tekstow.\n\n"
            f"Wykrylam napiecie: {tension.category.value}\n"
            f"Opis: {tension.description[:300]}\n"
            f"Pokrycie wiedzy: {coverage:.0%}\n"
            f"{domains_info}\n"
            "Zaproponuj konkretny program eksploracyjny - co powinam zbadac, "
            "jakie pytania sobie zadac, jak mierzyc postep. "
            "Odpowiedz TYLKO w JSON:\n"
            '{"title": "krotki tytul", '
            '"question": "glowne pytanie badawcze", '
            '"scope": "zakres i metoda", '
            '"success_signal": "miara sukcesu", '
            '"promotion_policy": "kiedy kontynuowac"}'
        )

        try:
            response = self._expert_fn(prompt)
        except Exception as e:
            logger.debug(f"[ExplorationEngine] Expert call failed: {e}")
            return None

        if not response:
            return None

        parsed = try_parse_json(response)
        if not parsed:
            # ChatGPT may return rich text, try to extract useful content
            logger.debug("[ExplorationEngine] Expert response not JSON, using as freeform")
            return ExplorationProgram.create(
                title=f"Eksploracja: {tension.category.value}",
                question=response[:200],
                scope="Na podstawie sugestii eksperta",
                success_signal="Nowa wiedza przyswojona",
                promotion_policy="Kontynuuj jesli retencja > 50%",
            )

        title = parsed.get("title", "")
        question = parsed.get("question", "")
        if not title or not question:
            return None

        return ExplorationProgram.create(
            title=title[:100],
            question=question[:200],
            scope=parsed.get("scope", "")[:200],
            success_signal=parsed.get("success_signal", "")[:200],
            promotion_policy=parsed.get("promotion_policy", "")[:200],
        )

    def _generate_with_llm(
        self,
        tension: DetectedTension,
        context: Dict[str, Any],
        profile: Optional[CognitiveProfile],
    ) -> Optional[ExplorationProgram]:
        """Generate exploration program via NIM API."""
        learning = context.get("learning_state", {})
        coverage = learning.get("coverage", 0)

        domains_info = ""
        if profile:
            if profile.domain_strengths:
                strong = list(profile.domain_strengths.keys())[:5]
                domains_info += f"Mocne tematy: {', '.join(strong)}\n"
            if profile.domain_weaknesses:
                weak = list(profile.domain_weaknesses.keys())[:5]
                domains_info += f"Slabe tematy: {', '.join(weak)}\n"

        prompt = (
            "M.A.R.I.A. potrzebuje programu eksploracyjnego.\n\n"
            f"Napiecie: {tension.category.value}\n"
            f"Opis: {tension.description[:200]}\n"
            f"Pokrycie wiedzy: {coverage:.0%}\n"
            f"{domains_info}"
            "\nZaproponuj program eksploracyjny. Odpowiedz TYLKO w JSON:\n"
            '{"title": "krotki tytul programu", '
            '"question": "co chcemy zbadac", '
            '"scope": "zakres i ograniczenia", '
            '"success_signal": "po czym poznamy sukces", '
            '"promotion_policy": "kiedy program staje sie celem"}'
        )

        response = safe_llm_call(self._llm_fn, prompt, "exploration_engine")
        if not response:
            return None

        parsed = try_parse_json(response)
        if not parsed:
            return None

        title = parsed.get("title", "")
        question = parsed.get("question", "")
        if not title or not question:
            return None

        return ExplorationProgram.create(
            title=title[:100],
            question=question[:200],
            scope=parsed.get("scope", "")[:200],
            success_signal=parsed.get("success_signal", "")[:200],
            promotion_policy=parsed.get("promotion_policy", "")[:200],
        )
