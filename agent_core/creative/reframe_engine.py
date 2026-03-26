"""LLM-enhanced cognitive reframing engine.

Generates ReframeProposal objects for MISALIGNMENT and OVER_RESTRICTION tensions.
Produces alternative perspectives on problems. Falls back to rule-based.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from agent_core.creative.creative_model import (
    DetectedTension, ReframeProposal, TensionCategory,
)
from agent_core.creative.llm_utils import safe_llm_call, try_parse_json

logger = logging.getLogger(__name__)

# Tension categories eligible for reframing
_REFRAME_CATEGORIES = {
    TensionCategory.MISALIGNMENT,
    TensionCategory.OVER_RESTRICTION,
}

# Rule-based reframe templates
_RULE_REFRAMES = {
    TensionCategory.MISALIGNMENT: {
        "reframed": "Cele bez postepu moga byc zbyt ambitne - zamiast porzucac, "
                    "podziel na mniejsze osiagalne kroki",
        "rationale": "Nierealistyczne cele demotywuja - lepiej miec male sukcesy",
    },
    TensionCategory.OVER_RESTRICTION: {
        "reframed": "Blokady K7 moga chronic system, ale tez blokowac rozwoj - "
                    "rozwaZ poluzowanie rate limitow dla bezpiecznych akcji",
        "rationale": "Zbyt restrykcyjne polityki hamuja autonomie i nauke",
    },
}


class ReframeEngine:
    """Generates cognitive reframes for tensions using NIM or rules."""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def set_llm_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        """Set or update LLM function (late wiring)."""
        self._llm_fn = fn

    def generate_reframes(
        self,
        tensions: List[DetectedTension],
        context: Dict[str, Any],
        memories_summary: str = "",
    ) -> List[ReframeProposal]:
        """
        Generate reframe proposals for eligible tensions.

        Only processes MISALIGNMENT and OVER_RESTRICTION tensions.

        Args:
            tensions: All detected tensions
            context: Strategic context dict
            memories_summary: Condensed conversation memory

        Returns:
            List of ReframeProposal objects
        """
        eligible = [
            t for t in tensions
            if t.category in _REFRAME_CATEGORIES and t.severity >= 0.4
        ]

        if not eligible:
            return []

        reframes = []
        for tension in eligible:
            # Try LLM
            if self._llm_fn is not None:
                proposal = self._reframe_with_llm(
                    tension, context, memories_summary
                )
                if proposal:
                    reframes.append(proposal)
                    continue

            # Rule-based fallback
            proposal = self._reframe_rule_based(tension)
            if proposal:
                reframes.append(proposal)

        return reframes

    def _reframe_rule_based(
        self,
        tension: DetectedTension,
    ) -> Optional[ReframeProposal]:
        """Generate a mechanical reframe from templates."""
        template = _RULE_REFRAMES.get(tension.category)
        if not template:
            return None

        return ReframeProposal.create(
            original_ref=tension.tension_id,
            original_description=tension.description[:200],
            reframed_description=template["reframed"],
            rationale=template["rationale"],
            evidence_refs=list(tension.evidence_refs),
        )

    def _reframe_with_llm(
        self,
        tension: DetectedTension,
        context: Dict[str, Any],
        memories_summary: str,
    ) -> Optional[ReframeProposal]:
        """Generate a reframe via NIM API."""
        prompt = (
            "System M.A.R.I.A. ma napiecie rozwojowe. "
            "Zaproponuj alternatywne spojrzenie na ten problem.\n\n"
            f"Napiecie: {tension.category.value}\n"
            f"Opis: {tension.description[:200]}\n"
            f"Waznosc: {tension.severity:.1f}\n"
        )
        if memories_summary:
            prompt += f"\nKontekst: {memories_summary[:300]}\n"

        prompt += (
            "\nOdpowiedz TYLKO w JSON:\n"
            '{"reframed_description": "alternatywne spojrzenie na problem", '
            '"rationale": "dlaczego to lepsze podejscie"}'
        )

        response = safe_llm_call(self._llm_fn, prompt, "reframe_engine")
        if not response:
            return None

        parsed = try_parse_json(response)
        if not parsed:
            return None

        reframed = parsed.get("reframed_description", "")
        if not reframed or len(reframed) < 10:
            return None

        return ReframeProposal.create(
            original_ref=tension.tension_id,
            original_description=tension.description[:200],
            reframed_description=reframed[:300],
            rationale=parsed.get("rationale", "")[:200],
            evidence_refs=list(tension.evidence_refs),
        )
