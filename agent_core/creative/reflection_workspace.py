"""Temporary bounded thought-space for an active reflection session.

The workspace orchestrates one creative reflection cycle:
1. Set problem statement from trigger
2. Retrieve relevant memories
3. Detect tensions
4. Form insights from tensions
5. Generate candidate meta-goals
6. Close and persist summary

Should be bounded by object limits. Not a giant scratchpad.
Speculative fragments are NOT persisted as long-term truth unless promoted.
"""

import logging
from typing import Any, Dict, List, Optional

from agent_core.creative.creative_model import (
    CreativeInsight, DetectedTension, MetaGoal, MetaGoalType,
    MetaGoalStatus, ReflectionSession, ReframeProposal,
    StrategicObservation, RiskLevel, TensionCategory,
)

logger = logging.getLogger(__name__)

# Maps tension category -> meta-goal type
_TENSION_TO_GOAL_TYPE = {
    TensionCategory.REPETITION: MetaGoalType.EXPLORATION_META,
    TensionCategory.STAGNATION: MetaGoalType.CAPABILITY_META,
    TensionCategory.UNDER_EXPLORATION: MetaGoalType.EXPLORATION_META,
    TensionCategory.EPISTEMIC_GAP: MetaGoalType.EPISTEMIC_META,
    TensionCategory.OVER_RESTRICTION: MetaGoalType.RESILIENCE_META,
    TensionCategory.MISALIGNMENT: MetaGoalType.ARCHITECTURAL_META,
    TensionCategory.FRAGILE_COORDINATION: MetaGoalType.RESILIENCE_META,
}

# Maps tension category -> suggested action direction
_TENSION_RESPONSES = {
    TensionCategory.REPETITION: (
        "Poszukaj nowych kierunkow nauki lub aktywnosci poza dotychczasowym zakresem"
    ),
    TensionCategory.STAGNATION: (
        "Zidentyfikuj blokade postepu i zaproponuj zmiane strategii"
    ),
    TensionCategory.UNDER_EXPLORATION: (
        "Rozszerz horyzonty - szukaj tematow interdyscyplinarnych lub nowych dziedzin"
    ),
    TensionCategory.EPISTEMIC_GAP: (
        "Wzmocnij retencje wiedzy - powtorki, egzaminy, nowe materialy uzupelniajace"
    ),
    TensionCategory.OVER_RESTRICTION: (
        "Przejrzyj polityki autonomii - czy blokady sa uzasadnione?"
    ),
    TensionCategory.MISALIGNMENT: (
        "Zrewiduj cele - porzuc niewykonalne, priorytetyzuj osiagalne"
    ),
    TensionCategory.FRAGILE_COORDINATION: (
        "Popraw stabilnosc - zidentyfikuj zrodla bledow w pipeline"
    ),
}


class ReflectionWorkspaceManager:
    """Manages creation and execution of reflection sessions."""

    def create_session(self, trigger: str, problem_statement: str = "") -> ReflectionSession:
        """Create a new bounded reflection session."""
        session = ReflectionSession(
            trigger=trigger,
            problem_statement=problem_statement or f"Reflection triggered by: {trigger}",
        )
        logger.info(f"[CREATIVE] Reflection session started: {session.session_id}")
        return session

    def form_insights(self, session: ReflectionSession) -> List[CreativeInsight]:
        """Form insights from detected tensions.

        Rule-based: each tension with severity > 0.4 gets an insight.
        """
        insights = []
        for tension in session.detected_tensions:
            if tension.severity < 0.4:
                continue

            response = _TENSION_RESPONSES.get(
                tension.category,
                "Wymaga dalszej analizy"
            )

            insight = CreativeInsight.create(
                derived_from=[tension.tension_id],
                statement=(
                    f"Napiecie '{tension.category.value}' (waznosc: {tension.severity:.1f}): "
                    f"{response}"
                ),
                confidence=tension.severity * 0.8,
                meta_goal_candidate=(tension.severity >= 0.6),
                reframe_candidate=(
                    tension.category in (
                        TensionCategory.MISALIGNMENT,
                        TensionCategory.OVER_RESTRICTION,
                    )
                ),
            )
            if session.add_insight(insight):
                insights.append(insight)

        logger.info(f"[CREATIVE] Formed {len(insights)} insights from {len(session.detected_tensions)} tensions")
        return insights

    def generate_candidates(self, session: ReflectionSession,
                            context: Dict[str, Any],
                            meta_goal_engine=None,
                            memories_summary: str = "") -> List[MetaGoal]:
        """Generate candidate meta-goals from insights.

        Only insights marked as meta_goal_candidate produce goals.
        """
        candidates = []
        for insight in session.insights:
            if not insight.meta_goal_candidate:
                continue

            # Find the tension that spawned this insight
            tension_id = insight.derived_from[0] if insight.derived_from else ""
            tension = None
            for t in session.detected_tensions:
                if t.tension_id == tension_id:
                    tension = t
                    break

            goal_type = MetaGoalType.EXPLORATION_META
            if tension:
                goal_type = _TENSION_TO_GOAL_TYPE.get(
                    tension.category, MetaGoalType.EXPLORATION_META
                )

            # Build evidence refs from context
            evidence_refs = list(insight.derived_from)
            learning_state = context.get("learning_state", {})
            coverage = learning_state.get("coverage", 0)
            if coverage:
                evidence_refs.append(f"knowledge_coverage={coverage:.2f}")

            # Use LLM engine if available, else rule-based
            if meta_goal_engine is not None:
                generated = meta_goal_engine.generate(
                    tension, context, memories_summary
                )
            else:
                generated = {
                    "title": self._generate_title(tension, context),
                    "expected_value": self._generate_expected_value(tension),
                    "decomposition_hint": self._generate_decomposition_hint(tension),
                }

            mg = MetaGoal.create(
                title=generated.get("title", "Nowy kierunek rozwoju"),
                goal_type=goal_type,
                priority=insight.confidence,
                why_now=insight.statement,
                evidence_refs=evidence_refs,
                expected_value=generated.get("expected_value", ""),
                risk_level=RiskLevel.LOW if insight.confidence > 0.5 else RiskLevel.MEDIUM,
                decomposition_hint=generated.get("decomposition_hint", ""),
            )
            if session.add_meta_goal(mg):
                candidates.append(mg)

        logger.info(f"[CREATIVE] Generated {len(candidates)} candidate meta-goals")
        return candidates

    def _generate_title(self, tension: Optional[DetectedTension],
                        context: Dict[str, Any]) -> str:
        """Generate a clear strategic title for a meta-goal."""
        if not tension:
            return "Nowy kierunek rozwoju strategicznego"

        titles = {
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
        return titles.get(tension.category, "Nowy kierunek rozwoju")

    def _generate_expected_value(self, tension: Optional[DetectedTension]) -> str:
        if not tension:
            return "Lepsze wykorzystanie czasu systemu"

        values = {
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
        return values.get(tension.category, "Ogolna poprawa funkcjonowania")

    def _generate_decomposition_hint(self, tension: Optional[DetectedTension]) -> str:
        if not tension:
            return ""

        hints = {
            TensionCategory.REPETITION:
                "Planner: rozważ nowe ActionType lub web_source dla nowych tematow",
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
        return hints.get(tension.category, "")
