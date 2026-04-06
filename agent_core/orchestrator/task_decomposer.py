"""
TaskDecomposer (V3 Phase B, Module 5)

Decomposes a user task description into structured steps.
Wraps K8 Deliberation templates with a user-facing API.

V2 foundation: Deliberator + StrategyTemplates provide multi-step
strategies for goals. This module translates user intent into
a decomposed plan that ExecutionPlanBuilder can turn into an
executable plan.

Usage:
    decomposer = TaskDecomposer(ctx)
    result = decomposer.decompose("naucz sie fizyki kwantowej")
    # result.steps = [
    #   TaskStep(action="fetch", description="Pobierz materialy o fizyce kwantowej"),
    #   TaskStep(action="learn", description="Nauka z pobranych materialow"),
    #   TaskStep(action="exam", description="Egzamin sprawdzajacy"),
    # ]
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskCategory(Enum):
    """High-level task categories that Maria can handle."""
    LEARN_TOPIC = "learn_topic"
    EXPLORE_NEW = "explore_new"
    CONSOLIDATE = "consolidate"
    ANALYZE = "analyze"
    FETCH_INFO = "fetch_info"
    SYSTEM_CHECK = "system_check"
    CODE = "code"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TaskStep:
    """Single step in a decomposed task."""
    order: int
    action: str
    description: str
    estimated_actions: int = 1
    requires_llm: bool = False
    requires_network: bool = False
    k7_classification: str = "free"
    fallback_order: Optional[int] = None


@dataclass
class DecomposedTask:
    """Result of task decomposition."""
    original_input: str
    category: TaskCategory
    topic: Optional[str]
    steps: List[TaskStep]
    template_name: Optional[str] = None
    feasibility: str = "feasible"
    infeasibility_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_estimated_actions(self) -> int:
        return sum(s.estimated_actions for s in self.steps)

    @property
    def requires_network(self) -> bool:
        return any(s.requires_network for s in self.steps)

    @property
    def requires_llm(self) -> bool:
        return any(s.requires_llm for s in self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_input": self.original_input,
            "category": self.category.value,
            "topic": self.topic,
            "steps": [
                {
                    "order": s.order,
                    "action": s.action,
                    "description": s.description,
                    "estimated_actions": s.estimated_actions,
                    "requires_llm": s.requires_llm,
                    "requires_network": s.requires_network,
                    "k7_classification": s.k7_classification,
                    "fallback_order": s.fallback_order,
                }
                for s in self.steps
            ],
            "template_name": self.template_name,
            "feasibility": self.feasibility,
            "infeasibility_reason": self.infeasibility_reason,
            "total_estimated_actions": self.total_estimated_actions,
            "requires_network": self.requires_network,
            "metadata": self.metadata,
        }


# Keywords for intent classification (PL + EN)
_LEARN_KEYWORDS = {
    "naucz", "ucz", "nauka", "learn", "study", "przeczytaj",
    "przeanalizuj", "zrozum", "explain", "wytlumacz",
}
_EXPLORE_KEYWORDS = {
    "znajdz", "szukaj", "search", "explore", "odkryj",
    "sprawdz co nowego", "poszukaj",
}
_CONSOLIDATE_KEYWORDS = {
    "powtorz", "review", "utrwal", "consolidate", "podsumuj",
    "egzamin", "exam", "test",
}
_ANALYZE_KEYWORDS = {
    "analizuj", "analyze", "ocen", "evaluate", "krytyka",
    "critique", "zbadaj", "diagnoza",
}
_FETCH_KEYWORDS = {
    "pobierz", "fetch", "download", "sciagnij", "wikipedia",
    "rss", "internet",
}
_SYSTEM_KEYWORDS = {
    "status", "health", "diagnostyka", "maintenance",
    "konserwacja", "eksperyment", "experiment",
}
_CODE_KEYWORDS = {
    "zrob", "napisz", "build", "implement", "code", "coding",
    "modul", "module", "feature", "napraw", "fix", "refactor",
    "zaprogramuj", "program", "script", "skrypt", "stwórz",
    "stworz", "zaprojektuj", "design", "zaimplementuj",
}


class TaskDecomposer:
    """Decomposes user tasks into structured steps."""

    def __init__(self, ctx):
        """
        Args:
            ctx: SharedContext instance
        """
        self._ctx = ctx

    def decompose(self, task_description: str) -> DecomposedTask:
        """
        Decompose a task description into structured steps.

        Args:
            task_description: User's task in natural language (PL or EN)

        Returns:
            DecomposedTask with category, steps, and feasibility.
        """
        category = self._classify(task_description)
        topic = self._extract_topic(task_description, category)

        if category == TaskCategory.UNKNOWN:
            return DecomposedTask(
                original_input=task_description,
                category=category,
                topic=topic,
                steps=[],
                feasibility="unclear",
                infeasibility_reason="Nie rozpoznano kategorii zadania",
            )

        steps = self._build_steps(category, topic, task_description)
        feasibility, reason = self._check_feasibility(category, steps)

        template = self._category_to_template(category)

        return DecomposedTask(
            original_input=task_description,
            category=category,
            topic=topic,
            steps=steps,
            template_name=template,
            feasibility=feasibility,
            infeasibility_reason=reason,
        )

    def get_available_categories(self) -> List[Dict[str, str]]:
        """List available task categories with descriptions."""
        return [
            {"category": "learn_topic", "label": "Nauka tematu",
             "description": "Pobierz materialy, naucz sie, zdaj egzamin"},
            {"category": "explore_new", "label": "Eksploracja",
             "description": "Znajdz nowe materialy z internetu i naucz sie"},
            {"category": "consolidate", "label": "Utrwalenie",
             "description": "Powtorka, egzamin, ewaluacja"},
            {"category": "analyze", "label": "Analiza",
             "description": "Samoanaliza, krytyka wiedzy, ewaluacja"},
            {"category": "fetch_info", "label": "Pobranie informacji",
             "description": "Pobierz materialy z Wikipedia/RSS"},
            {"category": "system_check", "label": "Diagnostyka",
             "description": "Sprawdz stan systemu, uruchom konserwacje"},
            {"category": "code", "label": "Kodowanie",
             "description": "Zaprojektuj, napisz, przetestuj i dostarcz kod"},
        ]

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(self, text: str) -> TaskCategory:
        """Classify task by keyword matching (zero LLM)."""
        lower = text.lower()
        words = set(lower.split())

        scores = {
            TaskCategory.LEARN_TOPIC: self._keyword_score(words, lower, _LEARN_KEYWORDS),
            TaskCategory.EXPLORE_NEW: self._keyword_score(words, lower, _EXPLORE_KEYWORDS),
            TaskCategory.CONSOLIDATE: self._keyword_score(words, lower, _CONSOLIDATE_KEYWORDS),
            TaskCategory.ANALYZE: self._keyword_score(words, lower, _ANALYZE_KEYWORDS),
            TaskCategory.FETCH_INFO: self._keyword_score(words, lower, _FETCH_KEYWORDS),
            TaskCategory.SYSTEM_CHECK: self._keyword_score(words, lower, _SYSTEM_KEYWORDS),
            TaskCategory.CODE: self._keyword_score(words, lower, _CODE_KEYWORDS),
        }

        best = max(scores, key=scores.get)
        if scores[best] == 0:
            # Default: short text without keywords -> treat as learn topic
            if len(text.split()) <= 6:
                return TaskCategory.LEARN_TOPIC
            return TaskCategory.UNKNOWN

        return best

    def _keyword_score(self, words: set, text: str, keywords: set) -> int:
        """Count keyword matches (word-level + substring)."""
        score = 0
        for kw in keywords:
            if kw in words:
                score += 2
            elif kw in text:
                score += 1
        return score

    def _extract_topic(self, text: str, category: TaskCategory) -> Optional[str]:
        """Extract the topic from task description."""
        lower = text.lower()

        # Remove known command words
        remove_words = (
            _LEARN_KEYWORDS | _EXPLORE_KEYWORDS | _CONSOLIDATE_KEYWORDS |
            _ANALYZE_KEYWORDS | _FETCH_KEYWORDS | _SYSTEM_KEYWORDS |
            _CODE_KEYWORDS |
            {"sie", "o", "z", "na", "w", "do", "i", "co", "jak",
             "mnie", "mi", "to", "ten", "ta", "te", "moj", "moja"}
        )

        words = text.split()
        topic_words = [w for w in words if w.lower() not in remove_words]

        if topic_words:
            return " ".join(topic_words)

        # Fallback: use whole text if short
        if len(text.split()) <= 4:
            return text

        return None

    # ------------------------------------------------------------------
    # Step building
    # ------------------------------------------------------------------

    def _build_steps(
        self, category: TaskCategory, topic: Optional[str], description: str,
    ) -> List[TaskStep]:
        """Build steps based on category (mirrors K8 templates)."""
        builders = {
            TaskCategory.LEARN_TOPIC: self._steps_learn_topic,
            TaskCategory.EXPLORE_NEW: self._steps_explore_new,
            TaskCategory.CONSOLIDATE: self._steps_consolidate,
            TaskCategory.ANALYZE: self._steps_analyze,
            TaskCategory.FETCH_INFO: self._steps_fetch_info,
            TaskCategory.SYSTEM_CHECK: self._steps_system_check,
            TaskCategory.CODE: self._steps_code,
        }
        builder = builders.get(category)
        if builder:
            return builder(topic)
        return []

    def _steps_learn_topic(self, topic: Optional[str]) -> List[TaskStep]:
        """Learn topic: check files -> learn -> exam -> (fail: review -> exam)."""
        t = topic or "wybrany temat"
        has_files = self._topic_has_files(topic)

        steps = []
        if not has_files:
            steps.append(TaskStep(
                order=0, action="fetch",
                description=f"Pobierz materialy o: {t}",
                estimated_actions=1, requires_network=True,
                k7_classification="guarded",
            ))

        base = len(steps)
        steps.extend([
            TaskStep(
                order=base, action="learn",
                description=f"Nauka: {t}",
                estimated_actions=3, requires_llm=True,
                k7_classification="free",
            ),
            TaskStep(
                order=base + 1, action="exam",
                description=f"Egzamin: {t}",
                estimated_actions=1, requires_llm=True,
                k7_classification="free",
                fallback_order=base + 2,
            ),
            TaskStep(
                order=base + 2, action="review",
                description=f"Powtorka slabych fragmentow: {t}",
                estimated_actions=1, requires_llm=True,
                k7_classification="free",
            ),
            TaskStep(
                order=base + 3, action="exam",
                description=f"Egzamin powtorkowy: {t}",
                estimated_actions=1, requires_llm=True,
                k7_classification="free",
                fallback_order=base + 2,
            ),
        ])
        return steps

    def _steps_explore_new(self, topic: Optional[str]) -> List[TaskStep]:
        """Explore: fetch -> learn -> exam."""
        t = topic or "nowe tematy"
        return [
            TaskStep(
                order=0, action="fetch",
                description=f"Pobierz materialy: {t}",
                estimated_actions=1, requires_network=True,
                k7_classification="guarded",
            ),
            TaskStep(
                order=1, action="learn",
                description=f"Nauka z pobranych materialow: {t}",
                estimated_actions=3, requires_llm=True,
                k7_classification="free",
            ),
            TaskStep(
                order=2, action="exam",
                description=f"Egzamin: {t}",
                estimated_actions=1, requires_llm=True,
                k7_classification="free",
                fallback_order=1,
            ),
        ]

    def _steps_consolidate(self, topic: Optional[str]) -> List[TaskStep]:
        """Consolidate: review -> exam -> evaluate."""
        t = topic or "dotychczasowa wiedza"
        return [
            TaskStep(
                order=0, action="review",
                description=f"Powtorka: {t}",
                estimated_actions=2, requires_llm=True,
                k7_classification="free",
            ),
            TaskStep(
                order=1, action="exam",
                description=f"Egzamin: {t}",
                estimated_actions=1, requires_llm=True,
                k7_classification="free",
                fallback_order=0,
            ),
            TaskStep(
                order=2, action="evaluate",
                description="Ewaluacja wynikow",
                estimated_actions=1,
                k7_classification="free",
            ),
        ]

    def _steps_analyze(self, topic: Optional[str]) -> List[TaskStep]:
        """Analyze: evaluate -> critique -> self_analyze."""
        return [
            TaskStep(
                order=0, action="evaluate",
                description="Ewaluacja stanu wiedzy",
                estimated_actions=1,
                k7_classification="free",
            ),
            TaskStep(
                order=1, action="critique",
                description="Krytyka jakosci wiedzy",
                estimated_actions=1,
                k7_classification="guarded",
            ),
            TaskStep(
                order=2, action="self_analyze",
                description="Samoanaliza K12",
                estimated_actions=1, requires_llm=True,
                k7_classification="guarded",
            ),
        ]

    def _steps_fetch_info(self, topic: Optional[str]) -> List[TaskStep]:
        """Fetch only."""
        t = topic or "nowe materialy"
        return [
            TaskStep(
                order=0, action="fetch",
                description=f"Pobierz: {t}",
                estimated_actions=1, requires_network=True,
                k7_classification="guarded",
            ),
        ]

    def _steps_system_check(self, topic: Optional[str]) -> List[TaskStep]:
        """System diagnostics."""
        return [
            TaskStep(
                order=0, action="evaluate",
                description="Ewaluacja metryk systemu",
                estimated_actions=1,
                k7_classification="free",
            ),
            TaskStep(
                order=1, action="maintenance",
                description="Konserwacja systemu",
                estimated_actions=1,
                k7_classification="guarded",
            ),
        ]

    def _steps_code(self, topic: Optional[str]) -> List[TaskStep]:
        """Code: design -> generate -> write -> test -> (fix loop) -> review."""
        t = topic or "nowy kod"
        return [
            TaskStep(
                order=0, action="code_design",
                description=f"Projektowanie: {t}",
                estimated_actions=1, requires_llm=True,
                k7_classification="guarded",
            ),
            TaskStep(
                order=1, action="code_generate",
                description=f"Generowanie kodu: {t}",
                estimated_actions=3, requires_llm=True,
                k7_classification="restricted",
            ),
            TaskStep(
                order=2, action="code_write",
                description=f"Zapis plikow: {t}",
                estimated_actions=0,
                k7_classification="restricted",
            ),
            TaskStep(
                order=3, action="code_test",
                description=f"Testowanie: {t}",
                estimated_actions=0,
                k7_classification="restricted",
            ),
            TaskStep(
                order=4, action="code_fix",
                description=f"Naprawa bledow: {t}",
                estimated_actions=2, requires_llm=True,
                k7_classification="restricted",
                fallback_order=2,
            ),
            TaskStep(
                order=5, action="code_review",
                description=f"Code review: {t}",
                estimated_actions=1, requires_llm=True,
                k7_classification="guarded",
            ),
        ]

    # ------------------------------------------------------------------
    # Feasibility
    # ------------------------------------------------------------------

    def _check_feasibility(
        self, category: TaskCategory, steps: List[TaskStep],
    ) -> tuple:
        """Check if the task is feasible given current state.

        Returns:
            (feasibility: str, reason: str)
            feasibility = "feasible" | "limited" | "infeasible"
        """
        if not steps:
            return ("infeasible", "Brak krokow do wykonania")

        # Check mode
        core = self._ctx.homeostasis_core
        if core:
            mode = getattr(core, "_current_mode", None)
            mode_name = mode.name if hasattr(mode, "name") else str(mode) if mode else ""
            if mode_name in ("SLEEP", "SURVIVAL"):
                return ("limited", f"Tryb {mode_name} - ograniczone dzialanie")

        # Check if network needed but not available
        needs_net = any(s.requires_network for s in steps)
        if needs_net:
            # We can still proceed - fetch may fail gracefully
            pass

        return ("feasible", "")

    def _topic_has_files(self, topic: Optional[str]) -> bool:
        """Check if we already have input files for this topic."""
        if not topic:
            return False
        analyzer = getattr(self._ctx, "knowledge_analyzer", None)
        if not analyzer:
            return False
        try:
            topic_map = analyzer.get_topic_map()
            topic_lower = topic.lower()
            for tag in topic_map:
                if topic_lower in tag.lower() or tag.lower() in topic_lower:
                    return True
        except Exception:
            pass
        return False

    def _category_to_template(self, category: TaskCategory) -> Optional[str]:
        """Map category to K8 Deliberation template name."""
        mapping = {
            TaskCategory.LEARN_TOPIC: "learn_topic",
            TaskCategory.EXPLORE_NEW: "explore_new",
            TaskCategory.CONSOLIDATE: "consolidate",
            TaskCategory.ANALYZE: None,
            TaskCategory.FETCH_INFO: None,
            TaskCategory.SYSTEM_CHECK: None,
            TaskCategory.CODE: "code_implementation",
        }
        return mapping.get(category)
