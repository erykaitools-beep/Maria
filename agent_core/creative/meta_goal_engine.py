"""LLM-enhanced meta-goal generation engine.

Generates richer meta-goal titles, expected values, and decomposition hints
using NIM API when available. Falls back to rule-based generation (Phase 1).
"""

import logging
from typing import Any, Callable, Dict, Optional

from agent_core.creative.creative_model import DetectedTension, TensionCategory
from agent_core.creative.llm_utils import safe_llm_call, try_parse_json

logger = logging.getLogger(__name__)

# Rule-based fallback titles (from Phase 1 reflection_workspace.py)
_RULE_TITLES = {
    TensionCategory.REPETITION:
        "Przelam stagnacje - znajdz nowe aktywnosci poza nauka",
    TensionCategory.STAGNATION:
        "Odblokuj postep - zmien strategie podejscia do wiedzy",
    TensionCategory.UNDER_EXPLORATION:
        "Rozszerz horyzonty - eksploruj nowe dziedziny wiedzy",
    TensionCategory.EPISTEMIC_GAP:
        "Wzmocnij retencje - uzupelnij luki w wiedzy",
    TensionCategory.OVER_RESTRICTION:
        "Przejrzyj polityki - zmniejsz zbedne ograniczenia",
    TensionCategory.MISALIGNMENT:
        "Zrewiduj cele - dopasuj plany do mozliwosci",
    TensionCategory.FRAGILE_COORDINATION:
        "Popraw stabilnosc - napraw bledy w koordynacji",
}

_RULE_VALUES = {
    TensionCategory.REPETITION:
        "System przestanie krecic sie w kolko i podejmie konstruktywne dzialania",
    TensionCategory.STAGNATION:
        "Wznowienie postepu w nauce lub rozwoju",
    TensionCategory.UNDER_EXPLORATION:
        "Nowe tematy i perspektywy w bazie wiedzy",
    TensionCategory.EPISTEMIC_GAP:
        "Wyzsza retencja i glebsze zrozumienie materialow",
    TensionCategory.OVER_RESTRICTION:
        "Wiecej uzytecznych akcji zamiast zablokowanych prob",
    TensionCategory.MISALIGNMENT:
        "Cele dopasowane do aktualnych mozliwosci systemu",
    TensionCategory.FRAGILE_COORDINATION:
        "Nizsza stopa bledow, stabilniejsze dzialanie",
}

_RULE_HINTS = {
    TensionCategory.REPETITION:
        "Planner: rozwaZ nowe ActionType lub web_source dla nowych tematow",
    TensionCategory.STAGNATION:
        "Planner: zmien priorytet z LEARN na REVIEW/EXAM, lub pobierz nowe materialy",
    TensionCategory.UNDER_EXPLORATION:
        "Planner: FETCH nowych tematow spoza dotychczasowego zakresu",
    TensionCategory.EPISTEMIC_GAP:
        "Planner: priorytet REVIEW i EXAM dla slabych tematow",
    TensionCategory.OVER_RESTRICTION:
        "Operator: przejrzyj K7 rate limits i polityki autonomii",
    TensionCategory.MISALIGNMENT:
        "Planner: ABANDON stale goals, create focused replacements",
    TensionCategory.FRAGILE_COORDINATION:
        "K11 Experiment: przetestuj parametry integracji",
}


class MetaGoalEngine:
    """Generates meta-goal content using NIM when available, rule-based fallback."""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def set_llm_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        """Set or update LLM function (late wiring)."""
        self._llm_fn = fn

    def generate(
        self,
        tension: Optional[DetectedTension],
        context: Dict[str, Any],
        memories_summary: str = "",
    ) -> Dict[str, str]:
        """
        Generate meta-goal content (title, expected_value, decomposition_hint).

        Uses NIM API when available, falls back to rule-based Phase 1 logic.

        Args:
            tension: The tension driving this meta-goal
            context: Strategic context dict
            memories_summary: Condensed conversation memory

        Returns:
            Dict with keys: title, expected_value, decomposition_hint
        """
        # Try LLM-enhanced generation
        if self._llm_fn is not None and tension is not None:
            result = self._generate_with_llm(tension, context, memories_summary)
            if result:
                return result

        # Rule-based fallback
        return self._generate_rule_based(tension)

    def _generate_rule_based(
        self,
        tension: Optional[DetectedTension],
    ) -> Dict[str, str]:
        """Phase 1 rule-based generation."""
        if not tension:
            return {
                "title": "Nowy kierunek rozwoju strategicznego",
                "expected_value": "Lepsze wykorzystanie czasu systemu",
                "decomposition_hint": "",
            }
        return {
            "title": _RULE_TITLES.get(
                tension.category, "Nowy kierunek rozwoju"
            ),
            "expected_value": _RULE_VALUES.get(
                tension.category, "Ogolna poprawa funkcjonowania"
            ),
            "decomposition_hint": _RULE_HINTS.get(
                tension.category, ""
            ),
        }

    def _generate_with_llm(
        self,
        tension: DetectedTension,
        context: Dict[str, Any],
        memories_summary: str,
    ) -> Optional[Dict[str, str]]:
        """Generate meta-goal content via NIM API."""
        learning = context.get("learning_state", {})
        coverage = learning.get("coverage", 0)
        retention = learning.get("retention_rate", 0)

        action = context.get("action_pattern", {})
        noop_ratio = action.get("noop_ratio", 0)

        prompt = (
            "Jestes M.A.R.I.A. - autonomiczny agent uczacy sie. "
            "Na podstawie napiecia rozwojowego, zaproponuj konkretny meta-cel.\n\n"
            f"Napiecie: {tension.category.value}\n"
            f"Opis: {tension.description[:200]}\n"
            f"Waznosc: {tension.severity:.1f}\n"
            f"Pokrycie wiedzy: {coverage:.0%}\n"
            f"Retencja: {retention or 'brak danych'}\n"
            f"NOOP ratio: {noop_ratio:.0%}\n"
        )
        if memories_summary:
            prompt += f"\n{memories_summary[:500]}\n"

        prompt += (
            "\nOdpowiedz TYLKO w JSON:\n"
            '{"title": "max 80 znakow, konkretny cel", '
            '"expected_value": "co to da systemowi", '
            '"decomposition_hint": "wskazowka dla planera jak to zrealizowac"}'
        )

        response = safe_llm_call(self._llm_fn, prompt, "meta_goal_engine")
        if not response:
            return None

        parsed = try_parse_json(response)
        if not parsed:
            return None

        title = parsed.get("title", "")
        if not title or len(title) < 5:
            return None

        return {
            "title": title[:100],
            "expected_value": parsed.get("expected_value", "")[:200],
            "decomposition_hint": parsed.get("decomposition_hint", "")[:200],
        }
