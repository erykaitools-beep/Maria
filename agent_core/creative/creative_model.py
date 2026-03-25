"""Data models for Creative Module (K13).

All typed dataclasses and enums for Creative artifacts.
Contracts should remain stable once locked.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import time
import uuid


# --- Enums ---

class MetaGoalType(Enum):
    """Types of strategic meta-goals."""
    EPISTEMIC_META = "epistemic_meta"           # Knowledge/understanding direction
    CAPABILITY_META = "capability_meta"         # New capability development
    RESILIENCE_META = "resilience_meta"         # System robustness improvement
    EXPLORATION_META = "exploration_meta"       # Curiosity-driven investigation
    ARCHITECTURAL_META = "architectural_meta"   # Structural improvement
    OPERATOR_META = "operator_meta"             # Operator-requested direction
    PERSONALITY_META = "personality_meta"       # Cognitive style adjustment


class MetaGoalStatus(Enum):
    """Lifecycle of a meta-goal within Creative."""
    DRAFT = "draft"             # Generated, not yet evaluated
    PROPOSED = "proposed"       # Passed evaluation, ready for GoalStore
    ACCEPTED = "accepted"       # Promoted to GoalStore
    REJECTED = "rejected"       # Filtered out (duplicate, low value, policy)
    ARCHIVED = "archived"       # No longer relevant


class TensionCategory(Enum):
    """Types of developmental tensions."""
    REPETITION = "repetition"                   # Doing the same thing over and over
    STAGNATION = "stagnation"                   # No progress in any dimension
    MISALIGNMENT = "misalignment"               # Goals vs actual behavior mismatch
    OVER_RESTRICTION = "over_restriction"       # Safety/policy blocking useful work
    UNDER_EXPLORATION = "under_exploration"      # Not enough novelty or breadth
    FRAGILE_COORDINATION = "fragile_coordination"  # Components poorly integrated
    EPISTEMIC_GAP = "epistemic_gap"             # Known knowledge gap not addressed


class RiskLevel(Enum):
    """Risk level for meta-goals and exploration programs."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PersonalityDimension(Enum):
    """Dimensions of cognitive development style."""
    EXPLORATION_VS_ORDER = "exploration_vs_order"
    CAUTION_VS_BOLDNESS = "caution_vs_boldness"
    DEPTH_VS_BREADTH = "depth_vs_breadth"
    REFRAME_BIAS = "reframe_bias"
    OPERATOR_SENSITIVITY = "operator_sensitivity"


class ConversationMemoryType(Enum):
    """Types of operator-dialogue memory."""
    PREFERENCE = "preference"                   # Operator preference
    DECISION = "decision"                       # Operator decision
    GOAL_DISCUSSION = "goal_discussion"         # Goal-related dialogue
    ARCHITECTURAL_PRINCIPLE = "architectural_principle"  # Design decision
    REJECTION = "rejection"                     # Operator rejected something
    ACCEPTANCE = "acceptance"                   # Operator accepted something


class Speaker(Enum):
    """Who said it."""
    OPERATOR = "operator"
    MARIA = "maria"


# --- Dataclasses ---

def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class MetaGoal:
    """Strategic development direction grounded in system evidence."""
    goal_id: str
    title: str
    goal_type: MetaGoalType
    status: MetaGoalStatus
    priority: float                         # 0.0-1.0 strategic importance
    why_now: str                            # Grounded reason for proposing now
    evidence_refs: List[str]                # Links to event IDs, JSONL slices, reports
    expected_value: str                     # What capability/quality this improves
    risk_level: RiskLevel
    decomposition_hint: str = ""            # Optional clue for planner handoff
    source: str = "creative"
    created_ts: float = field(default_factory=time.time)

    @staticmethod
    def create(title: str, goal_type: MetaGoalType, priority: float,
               why_now: str, evidence_refs: List[str], expected_value: str,
               risk_level: RiskLevel = RiskLevel.LOW,
               decomposition_hint: str = "") -> "MetaGoal":
        return MetaGoal(
            goal_id=_gen_id("mg"),
            title=title,
            goal_type=goal_type,
            status=MetaGoalStatus.DRAFT,
            priority=priority,
            why_now=why_now,
            evidence_refs=evidence_refs,
            expected_value=expected_value,
            risk_level=risk_level,
            decomposition_hint=decomposition_hint,
        )

    def with_status(self, new_status: MetaGoalStatus) -> "MetaGoal":
        """Return copy with updated status (frozen dataclass pattern)."""
        return MetaGoal(
            goal_id=self.goal_id,
            title=self.title,
            goal_type=self.goal_type,
            status=new_status,
            priority=self.priority,
            why_now=self.why_now,
            evidence_refs=self.evidence_refs,
            expected_value=self.expected_value,
            risk_level=self.risk_level,
            decomposition_hint=self.decomposition_hint,
            source=self.source,
            created_ts=self.created_ts,
        )


@dataclass(frozen=True)
class DetectedTension:
    """A developmental contradiction, stagnation, or unrealized potential."""
    tension_id: str
    category: TensionCategory
    description: str                        # Human-readable statement
    severity: float                         # 0.0-1.0 relative importance
    evidence_refs: List[str]                # Events, reports, planner decisions
    pattern_window: str                     # Time or count window used for detection
    resolved: bool = False

    @staticmethod
    def create(category: TensionCategory, description: str,
               severity: float, evidence_refs: List[str],
               pattern_window: str = "7d") -> "DetectedTension":
        return DetectedTension(
            tension_id=_gen_id("tension"),
            category=category,
            description=description,
            severity=severity,
            evidence_refs=evidence_refs,
            pattern_window=pattern_window,
        )


@dataclass(frozen=True)
class CreativeInsight:
    """Strategic interpretation of what evidence means."""
    insight_id: str
    derived_from: List[str]                 # Tension IDs or evidence refs
    statement: str                          # Strategic interpretation
    confidence: float                       # 0.0-1.0
    reframe_candidate: bool = False         # Should also produce a reframe?
    meta_goal_candidate: bool = False       # Should also produce a meta-goal?

    @staticmethod
    def create(derived_from: List[str], statement: str,
               confidence: float, reframe_candidate: bool = False,
               meta_goal_candidate: bool = False) -> "CreativeInsight":
        return CreativeInsight(
            insight_id=_gen_id("insight"),
            derived_from=derived_from,
            statement=statement,
            confidence=confidence,
            reframe_candidate=reframe_candidate,
            meta_goal_candidate=meta_goal_candidate,
        )


@dataclass(frozen=True)
class ExplorationProgram:
    """Bounded plan for exploratory learning or testing."""
    program_id: str
    title: str
    question: str                           # What the system wants to investigate
    scope: str                              # Why this is bounded and safe
    success_signal: str                     # What counts as learning value
    promotion_policy: str                   # When this can become a formal goal

    @staticmethod
    def create(title: str, question: str, scope: str,
               success_signal: str, promotion_policy: str) -> "ExplorationProgram":
        return ExplorationProgram(
            program_id=_gen_id("explore"),
            title=title,
            question=question,
            scope=scope,
            success_signal=success_signal,
            promotion_policy=promotion_policy,
        )


@dataclass(frozen=True)
class PersonalitySignal:
    """Style-of-growth adjustment, not emotion."""
    signal_id: str
    dimension: PersonalityDimension
    direction: str                          # Which side to increase/decrease
    reason: str                             # Grounded reason for update
    magnitude: float                        # Small bounded adjustment
    approved: bool = False                  # Whether policy allows immediate update

    @staticmethod
    def create(dimension: PersonalityDimension, direction: str,
               reason: str, magnitude: float) -> "PersonalitySignal":
        return PersonalitySignal(
            signal_id=_gen_id("psig"),
            dimension=dimension,
            direction=direction,
            reason=reason,
            magnitude=min(max(magnitude, 0.0), 0.1),  # Cap at 0.1
        )


@dataclass(frozen=True)
class ReframeProposal:
    """Alternative framing of an existing problem or goal."""
    reframe_id: str
    original_ref: str                       # Goal ID or tension ID being reframed
    original_description: str               # What the system currently thinks
    reframed_description: str               # Alternative interpretation
    rationale: str                          # Why the reframe is better
    evidence_refs: List[str]
    created_ts: float = field(default_factory=time.time)

    @staticmethod
    def create(original_ref: str, original_description: str,
               reframed_description: str, rationale: str,
               evidence_refs: List[str]) -> "ReframeProposal":
        return ReframeProposal(
            reframe_id=_gen_id("reframe"),
            original_ref=original_ref,
            original_description=original_description,
            reframed_description=reframed_description,
            rationale=rationale,
            evidence_refs=evidence_refs,
        )


@dataclass(frozen=True)
class StrategicObservation:
    """Logged reflection without goal promotion."""
    observation_id: str
    statement: str
    evidence_refs: List[str]
    category: str                           # Free-form tag
    created_ts: float = field(default_factory=time.time)

    @staticmethod
    def create(statement: str, evidence_refs: List[str],
               category: str = "general") -> "StrategicObservation":
        return StrategicObservation(
            observation_id=_gen_id("obs"),
            statement=statement,
            evidence_refs=evidence_refs,
            category=category,
        )


# --- Store/Session models ---

@dataclass(frozen=True)
class CreativeJournalEntry:
    """Persistent strategic diary entry."""
    entry_id: str
    trigger: str                            # Why reflection started
    summary: str                            # Short strategic summary
    tension_ids: List[str]
    insight_ids: List[str]
    meta_goal_ids: List[str]
    operator_decision: str = ""             # accepted/rejected/postponed/not_reviewed
    later_outcome: str = ""                 # Filled later if evidence emerges
    created_ts: float = field(default_factory=time.time)

    @staticmethod
    def create(trigger: str, summary: str,
               tension_ids: List[str] = None,
               insight_ids: List[str] = None,
               meta_goal_ids: List[str] = None) -> "CreativeJournalEntry":
        return CreativeJournalEntry(
            entry_id=_gen_id("journal"),
            trigger=trigger,
            summary=summary,
            tension_ids=tension_ids or [],
            insight_ids=insight_ids or [],
            meta_goal_ids=meta_goal_ids or [],
        )


@dataclass(frozen=True)
class ConversationMemoryEntry:
    """Operator-dialogue memory relevant to growth and direction."""
    memory_id: str
    source_session: str                     # Conversation/session trace
    speaker: Speaker
    content: str                            # Development-related statement
    memory_type: ConversationMemoryType
    importance: float                       # 0.0-1.0 retrieval priority
    summary: str = ""                       # Compressed reusable version
    created_ts: float = field(default_factory=time.time)

    @staticmethod
    def create(source_session: str, speaker: Speaker, content: str,
               memory_type: ConversationMemoryType, importance: float,
               summary: str = "") -> "ConversationMemoryEntry":
        return ConversationMemoryEntry(
            memory_id=_gen_id("cmem"),
            source_session=source_session,
            speaker=speaker,
            content=content,
            memory_type=memory_type,
            importance=importance,
            summary=summary,
        )


@dataclass
class ReflectionSession:
    """Temporary bounded thought-space for an active reflection."""
    session_id: str = field(default_factory=lambda: _gen_id("refl"))
    trigger: str = ""
    problem_statement: str = ""
    retrieved_memories: List[ConversationMemoryEntry] = field(default_factory=list)
    detected_tensions: List[DetectedTension] = field(default_factory=list)
    insights: List[CreativeInsight] = field(default_factory=list)
    candidate_meta_goals: List[MetaGoal] = field(default_factory=list)
    candidate_reframes: List[ReframeProposal] = field(default_factory=list)
    observations: List[StrategicObservation] = field(default_factory=list)
    started_ts: float = field(default_factory=time.time)
    closed: bool = False

    # Bounded limits
    MAX_TENSIONS: int = 10
    MAX_INSIGHTS: int = 10
    MAX_CANDIDATES: int = 5

    def add_tension(self, t: DetectedTension) -> bool:
        if len(self.detected_tensions) >= self.MAX_TENSIONS:
            return False
        self.detected_tensions.append(t)
        return True

    def add_insight(self, i: CreativeInsight) -> bool:
        if len(self.insights) >= self.MAX_INSIGHTS:
            return False
        self.insights.append(i)
        return True

    def add_meta_goal(self, mg: MetaGoal) -> bool:
        if len(self.candidate_meta_goals) >= self.MAX_CANDIDATES:
            return False
        self.candidate_meta_goals.append(mg)
        return True

    def close(self) -> None:
        self.closed = True
