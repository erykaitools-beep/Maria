"""
Gap Planner - decides what cognitive action to take based on audit results.

Phase 3 of Learning Upgrade. Reads AuditReport + BulletinStore and
returns a concrete recommendation for the planner.

Decision logic:
1. NEED_REVIEW on board (from critic) -> REVIEW first, don't add material
2. Topic too broad (many gaps) -> decompose into sub-topics
3. No material at all -> NEED_MATERIAL (targeted, not generic fetch)
4. Low confidence / shallow -> NEED_MATERIAL (deepen specific gaps)
5. No exam coverage -> NEED_TEST
6. Stale knowledge -> NEED_REVIEW (refresh)
7. Topic well-covered -> no action needed

Zero LLM. Deterministic. Testable.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from agent_core.bulletin.knowledge_auditor import (
    AuditReport,
    GapType,
    KnowledgeGap,
)
from agent_core.bulletin.bulletin_model import (
    EntryType,
    EntryStatus,
)

logger = logging.getLogger(__name__)

# If a topic has this many gap types, it's probably too broad
BROAD_TOPIC_THRESHOLD = 4

# Max sub-topics to create when decomposing a broad topic
MAX_SUBTOPICS = 3

# Warstwa 2: topic-validity heuristics.
# Topics should be nominal phrases like "logika formalna", "fizyka".
# Prose descriptions ("Zwiekszenie pokrycia wiedzy do 100%") are strategies,
# not learnable topics, and must not be handed to ASK_EXPERT or FETCH_MATERIAL.
MAX_TOPIC_WORDS = 5
MAX_TOPIC_CHARS = 60

# Strategy / meta-level verbs and nouns that indicate prose, not a subject.
# Polish + English. Lowercase match on any word in topic.
_STRATEGY_KEYWORDS = {
    # polish
    "zmiana", "zmiany", "zmien", "zmienic",
    "rozszerzenie", "rozszerz", "rozszerzyc",
    "eksploracja", "eksploruj", "zbadaj",
    "zwiekszenie", "zwieksz", "zwiekszyc",
    "zmniejszenie", "zmniejsz",
    "poprawa", "popraw", "poprawic",
    "optymalizacja", "optymalizuj",
    "wprowadzenie", "wprowadz",
    "redukcja", "zredukuj",
    "autonomiczna", "autonomiczne", "autonomiczny",
    "strukturyzacja", "struktur",
    "mechanizm", "mechanizmu",
    "strategia", "strategii",
    # english
    "improve", "increase", "reduce", "expand", "explore",
    "optimize", "implement", "introduce",
    "strategy", "mechanism",
}


class GapAction(Enum):
    """What the gap planner recommends."""
    NO_ACTION = "no_action"             # Topic well-covered
    FETCH_MATERIAL = "fetch_material"   # Get material from web
    ASK_EXPERT = "ask_expert"           # Ask strongest model for targeted material
    RUN_EXAM = "run_exam"               # Test existing knowledge
    REVIEW = "review"                   # Re-examine/refresh
    DECOMPOSE = "decompose"             # Split broad topic into sub-topics
    WAIT_HUMAN = "wait_human"           # Need operator input


@dataclass
class GapPlan:
    """Concrete plan from gap analysis."""
    action: GapAction
    topic: str
    reason: str                         # Why this action
    priority: float = 0.5
    subtopics: List[str] = None         # For DECOMPOSE action
    context_prompt: str = ""            # For ASK_EXPERT: what to ask
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.subtopics is None:
            self.subtopics = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "topic": self.topic,
            "reason": self.reason,
            "priority": self.priority,
            "subtopics": self.subtopics,
            "context_prompt": self.context_prompt,
            "metadata": self.metadata,
        }


def is_topic_learnable(topic: str) -> tuple:
    """Check whether a string looks like a concrete topic vs. prose description.

    Warstwa 2 backstop: even if Warstwa 1 (goal-type filter in planner_core)
    lets a non-learnable topic through, this function catches prose like
    'Zwiekszenie pokrycia wiedzy do 100%' or 'Zmiana mechanizmu uczenia'
    before it becomes a template'd ASK_EXPERT bulletin.

    Returns:
        (True, None) if topic is learnable (short nominal phrase).
        (False, reason) if topic looks like prose/strategy.
    """
    if not topic or not isinstance(topic, str):
        return (False, "empty_topic")

    stripped = topic.strip()
    if not stripped:
        return (False, "empty_topic")

    if len(stripped) > MAX_TOPIC_CHARS:
        return (False, "topic_too_long_chars")

    words = stripped.split()
    if len(words) > MAX_TOPIC_WORDS:
        return (False, "topic_too_many_words")

    # Check any word against strategy vocabulary (lowercase, no punctuation)
    normalized_words = [
        "".join(ch for ch in w.lower() if ch.isalpha())
        for w in words
    ]
    if any(w in _STRATEGY_KEYWORDS for w in normalized_words if w):
        return (False, "topic_contains_strategy_keyword")

    # Ends with percent / digit target — e.g. "pokrycia wiedzy do 100%"
    if stripped.endswith("%") or stripped.rstrip(".!").endswith(tuple("0123456789")):
        return (False, "topic_contains_numeric_target")

    return (True, None)


class GapPlanner:
    """
    Decides what to do based on knowledge audit results.

    Reads AuditReport and bulletin board state, returns GapPlan.
    """

    def __init__(self):
        self._bulletin_store = None
        self._memory_query = None

    def set_bulletin_store(self, store) -> None:
        self._bulletin_store = store

    def set_memory_query(self, mq) -> None:
        """Attach MemoryQuery for Warstwa 3 cross-check before ASK_EXPERT."""
        self._memory_query = mq

    @staticmethod
    def _check_knowledge_index(slug: str, project_root) -> bool:
        """Check memory/knowledge_index.jsonl for a completed file matching slug.

        The index is authoritative: it reflects actual learned state, regardless
        of filesystem byte-size quirks or cached bytecode. A topic is covered
        when expert_<slug>.txt or web_wiki_<slug>.txt is status=completed with
        chunks_learned > 0.

        Slug match is exact to avoid false positives (e.g. 'fizyka' must not
        match 'astrofizyka.txt').
        """
        if not slug:
            return False
        import json as _json
        index_path = project_root / "memory" / "knowledge_index.jsonl"
        if not index_path.exists():
            return False
        targets = {f"expert_{slug}.txt", f"web_wiki_{slug}.txt"}
        try:
            with index_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        entry = _json.loads(line)
                    except Exception:
                        continue
                    fname = (entry.get("file") or entry.get("id") or "").lower()
                    if fname not in targets:
                        continue
                    if entry.get("status") == "completed" and int(
                        entry.get("chunks_learned") or 0
                    ) > 0:
                        return True
        except Exception as e:
            logger.debug(f"[GapPlanner] knowledge_index check failed: {e}")
        return False

    def _has_real_material(self, topic: str) -> bool:
        """Cross-check whether Maria actually has material on this topic.

        Warstwa 3: before accepting audit's NO_MATERIAL claim and generating
        ASK_EXPERT, verify directly:
        1. Filesystem: expert_<slug>.txt or web_wiki_<slug>.txt exists and
           has substantial content (>5000 bytes).
        2. knowledge_index.jsonl: authoritative record of completed material
           (robust against filesystem byte-size quirks and pyc cache drift).
        3. MemoryQuery (if wired): get_topic_summary reports known=True with
           files_count > 0.

        If any signal says "yes", audit was stale — don't ask expert.
        """
        import re
        from pathlib import Path

        if not topic:
            return False

        slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
        if not slug:
            return False

        project_root = Path(__file__).resolve().parents[2]
        input_dir = project_root / "input"
        if input_dir.exists():
            for name in (f"expert_{slug}.txt", f"web_wiki_{slug}.txt"):
                fpath = input_dir / name
                try:
                    if fpath.exists() and fpath.stat().st_size > 5000:
                        return True
                except OSError:
                    pass

        if self._check_knowledge_index(slug, project_root):
            return True

        # MemoryQuery cross-check (if attached)
        if self._memory_query is not None:
            try:
                summary = self._memory_query.get_topic_summary(topic)
                if summary.get("known") and summary.get("files_count", 0) > 0:
                    return True
            except Exception as e:
                logger.debug(f"[GapPlanner] MemoryQuery check failed: {e}")

        return False

    def plan_for_topic(
        self,
        audit: AuditReport,
        goal_description: str = "",
    ) -> GapPlan:
        """
        Given an audit report, decide what to do next.

        Priority order:
        1. Quality issues first (review before adding material)
        2. No material -> fetch/ask_expert
        3. Shallow -> deepen
        4. No exam -> test
        5. Stale -> refresh
        6. Too many gaps -> decompose
        """
        topic = audit.topic

        if not audit.has_gaps:
            return GapPlan(
                action=GapAction.NO_ACTION,
                topic=topic,
                reason="topic_well_covered",
            )

        # Warstwa 2: validate that topic looks like a learnable subject,
        # not a prose strategy description. Backstop for Warstwa 1 in
        # planner_core._is_gap_learnable_goal() in case some path feeds us
        # a goal.description instead of a real topic.
        learnable, reject_reason = is_topic_learnable(topic)
        if not learnable:
            logger.debug(
                f"[GapPlanner] Skipping non-learnable topic "
                f"({reject_reason}): {topic[:60]!r}"
            )
            return GapPlan(
                action=GapAction.NO_ACTION,
                topic=topic,
                reason=f"topic_not_learnable:{reject_reason}",
            )

        # Check bulletin for existing NEED_REVIEW (critic flagged)
        if self._has_open_review(topic):
            return GapPlan(
                action=GapAction.REVIEW,
                topic=topic,
                reason="critic_flagged_quality_issue",
                priority=0.8,
            )

        gap_types = {g.gap_type for g in audit.gaps}

        # Too many different gap types -> topic is too broad
        if len(gap_types) >= BROAD_TOPIC_THRESHOLD:
            subtopics = self._suggest_subtopics(audit, goal_description)
            if subtopics:
                return GapPlan(
                    action=GapAction.DECOMPOSE,
                    topic=topic,
                    reason="topic_too_broad",
                    priority=0.6,
                    subtopics=subtopics,
                )

        # Contradictions -> review first
        if GapType.CONTRADICTIONS in gap_types:
            return GapPlan(
                action=GapAction.REVIEW,
                topic=topic,
                reason="contradictions_detected",
                priority=0.8,
                metadata={"gaps": [g.to_dict() for g in audit.gaps
                                   if g.gap_type == GapType.CONTRADICTIONS]},
            )

        # No material at all -> need to fetch or ask expert
        if GapType.NO_MATERIAL in gap_types:
            # Warstwa 3: cross-check audit claim. KnowledgeAuditor may miss
            # material that exists on disk or in MemoryQuery (stale beliefs,
            # audit timing). Don't ask expert if we already have the file.
            if self._has_real_material(topic):
                logger.info(
                    f"[GapPlanner] Audit reported NO_MATERIAL for '{topic}' "
                    f"but material exists — recommending REVIEW instead"
                )
                return GapPlan(
                    action=GapAction.REVIEW,
                    topic=topic,
                    reason="material_exists_audit_stale",
                    priority=0.4,
                    metadata={"audit_mismatch": True},
                )
            prompt = self._build_expert_prompt(audit, goal_description)
            return GapPlan(
                action=GapAction.ASK_EXPERT,
                topic=topic,
                reason="no_knowledge_exists",
                priority=0.9,
                context_prompt=prompt,
            )

        # Low confidence / shallow -> ask expert for targeted material
        if GapType.LOW_CONFIDENCE in gap_types or GapType.SHALLOW in gap_types:
            prompt = self._build_expert_prompt(audit, goal_description)
            return GapPlan(
                action=GapAction.ASK_EXPERT,
                topic=topic,
                reason="knowledge_gaps_detected",
                priority=0.7,
                context_prompt=prompt,
                metadata={
                    "avg_confidence": audit.avg_confidence,
                    "beliefs_count": audit.beliefs_count,
                },
            )

        # No exam coverage -> test
        if GapType.NO_EXAM in gap_types:
            return GapPlan(
                action=GapAction.RUN_EXAM,
                topic=topic,
                reason="untested_knowledge",
                priority=0.5,
            )

        # Stale knowledge -> review/refresh
        if GapType.STALE in gap_types:
            return GapPlan(
                action=GapAction.REVIEW,
                topic=topic,
                reason="knowledge_stale",
                priority=0.4,
                metadata={"freshness": audit.freshness},
            )

        # Fallback: generic fetch
        return GapPlan(
            action=GapAction.FETCH_MATERIAL,
            topic=topic,
            reason="general_gap",
            priority=0.5,
        )

    def _has_open_review(self, topic: str) -> bool:
        """Check if bulletin has open NEED_REVIEW for this topic."""
        if self._bulletin_store is None:
            return False
        entries = self._bulletin_store.find_open(
            topic=topic, entry_type=EntryType.NEED_REVIEW,
        )
        return len(entries) > 0

    def _suggest_subtopics(
        self, audit: AuditReport, goal_description: str
    ) -> List[str]:
        """
        Suggest sub-topics for a broad topic.

        Rule-based: extract distinct gap areas as candidate sub-topics.
        Phase 4 will use LLM for better decomposition.
        """
        # Extract unique gap descriptions as subtopic hints
        subtopics = []
        seen = set()
        for gap in audit.gaps:
            # Use gap type as subtopic hint
            hint = f"{audit.topic} - {gap.gap_type.value}"
            if hint not in seen:
                seen.add(hint)
                subtopics.append(hint)
            if len(subtopics) >= MAX_SUBTOPICS:
                break
        return subtopics

    def _build_expert_prompt(
        self, audit: AuditReport, goal_description: str
    ) -> str:
        """
        Build a targeted prompt for ASK_EXPERT with audit context.

        Format: "Maria wie X, potrzebuje Y" - the key insight from the plan.
        Phase 4 will refine this further.
        """
        topic = audit.topic
        parts = []

        if audit.known:
            parts.append(
                f"Maria ma podstawowa wiedze o '{topic}' "
                f"({audit.files_count} plikow, "
                f"confidence {audit.avg_confidence:.0%})."
            )
            # Describe specific gaps
            gap_descs = []
            for gap in audit.gaps[:3]:
                if gap.gap_type == GapType.LOW_CONFIDENCE:
                    gap_descs.append("niski poziom pewnosci")
                elif gap.gap_type == GapType.SHALLOW:
                    gap_descs.append("plytka wiedza, brak glebszych przykladow")
                elif gap.gap_type == GapType.STALE:
                    gap_descs.append("przestarzala wiedza")
                elif gap.gap_type == GapType.NO_EXAM:
                    gap_descs.append("brak testow weryfikujacych")
            if gap_descs:
                parts.append(f"Problemy: {', '.join(gap_descs)}.")
            parts.append(
                f"Potrzebuje poglebionego materialu edukacyjnego o: {topic}."
            )
        else:
            parts.append(
                f"Maria nie ma zadnej wiedzy o '{topic}'. "
                f"Potrzebuje materialu edukacyjnego od podstaw."
            )

        if goal_description:
            parts.append(f"Cel nauki: {goal_description}.")

        return " ".join(parts)
