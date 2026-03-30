"""
Faza G: Critic Agent - data models for knowledge quality findings and reports.

Knowledge quality gate: coherence, calibration, support depth, dispute state,
exam coverage, freshness. NOT a truth engine (ADR-028).

Follows K12 recommendation_model.py pattern: frozen dataclasses + JSON.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import time
import uuid


class FindingCategory(Enum):
    """What kind of knowledge quality issue was found (7 categories)."""
    CONTRADICTION = "contradiction"           # Conflicting beliefs about same entity
    OVERCONFIDENT = "overconfident"            # High confidence, weak evidence
    UNDERCONFIDENT = "underconfident"          # Low confidence despite strong evidence
    SHALLOW_KNOWLEDGE = "shallow_knowledge"    # Topic with poor support depth
    UNRESOLVED_DISPUTE = "unresolved_dispute"  # High-severity disputes from Faza F
    COVERAGE_GAP = "coverage_gap"             # Partially learned / no exam
    STALE_KNOWLEDGE = "stale_knowledge"       # Decaying knowledge near floor


class FindingSeverity(Enum):
    """How urgent is this finding."""
    CRITICAL = "critical"   # Contradictions, severe disputes
    WARNING = "warning"     # Calibration errors, shallow, stale
    INFO = "info"           # Coverage notes, minor staleness


class SuggestedCritiqueAction(Enum):
    """What Maria should do about this finding."""
    REVIEW = "review"         # Re-examine existing material
    VERIFY = "verify"         # Run exam to verify
    RESOLVE = "resolve"       # Resolve dispute / contradiction
    LEARN_MORE = "learn_more" # Deepen knowledge on topic
    REFRESH = "refresh"       # Re-learn decaying material


# Severity sort order (lower = more severe)
_SEVERITY_ORDER = {
    FindingSeverity.CRITICAL.value: 0,
    FindingSeverity.WARNING.value: 1,
    FindingSeverity.INFO.value: 2,
}


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _normalize_topic(topic: str) -> str:
    """Normalize topic string for dedup comparison."""
    return topic.strip().lower().replace(" ", "_")


def _make_dedupe_key(
    category: str,
    topic_normalized: str,
    belief_ids: Tuple[str, ...],
) -> str:
    """Build dedupe key: category:topic:sorted_belief_ids."""
    sorted_ids = ":".join(sorted(belief_ids)) if belief_ids else ""
    return f"{category}:{topic_normalized}:{sorted_ids}"


@dataclass(frozen=True)
class CritiqueFinding:
    """Single knowledge quality finding. READ-ONLY output from KnowledgeCritic."""

    finding_id: str
    category: str              # FindingCategory value
    severity: str              # FindingSeverity value
    topic: str                 # Original topic name
    topic_normalized: str      # Normalized for dedup
    description: str           # Human-readable explanation
    suggested_action: str      # SuggestedCritiqueAction value

    # Evidence and provenance
    evidence: Dict[str, Any] = field(default_factory=dict)
    evidence_sources: Tuple[str, ...] = ()  # Where data came from
    belief_ids: Tuple[str, ...] = ()        # Related belief IDs
    confidence_delta: float = 0.0           # For calibration findings

    # Dedup and goal creation
    dedupe_key: str = ""
    recommended_goal_title: Optional[str] = None

    # Extensible metadata (volatility_hint, staleness_reason, etc.)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def severity_order(self) -> int:
        """Numeric order for sorting (lower = more severe)."""
        return _SEVERITY_ORDER.get(self.severity, 99)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evidence_sources"] = list(self.evidence_sources)
        d["belief_ids"] = list(self.belief_ids)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CritiqueFinding":
        return cls(
            finding_id=d.get("finding_id", _gen_id("cf")),
            category=d.get("category", "contradiction"),
            severity=d.get("severity", "warning"),
            topic=d.get("topic", "unknown"),
            topic_normalized=d.get("topic_normalized", "unknown"),
            description=d.get("description", ""),
            suggested_action=d.get("suggested_action", "review"),
            evidence=d.get("evidence", {}),
            evidence_sources=tuple(d.get("evidence_sources", [])),
            belief_ids=tuple(d.get("belief_ids", [])),
            confidence_delta=float(d.get("confidence_delta", 0.0)),
            dedupe_key=d.get("dedupe_key", ""),
            recommended_goal_title=d.get("recommended_goal_title"),
            metadata=d.get("metadata", {}),
        )


def create_finding(
    category: FindingCategory,
    severity: FindingSeverity,
    topic: str,
    description: str,
    suggested_action: SuggestedCritiqueAction,
    evidence: Optional[Dict[str, Any]] = None,
    evidence_sources: Optional[List[str]] = None,
    belief_ids: Optional[List[str]] = None,
    confidence_delta: float = 0.0,
    recommended_goal_title: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CritiqueFinding:
    """Factory function for creating a CritiqueFinding with auto-generated fields."""
    topic_norm = _normalize_topic(topic)
    b_ids = tuple(belief_ids or [])

    return CritiqueFinding(
        finding_id=_gen_id("cf"),
        category=category.value,
        severity=severity.value,
        topic=topic,
        topic_normalized=topic_norm,
        description=description,
        suggested_action=suggested_action.value,
        evidence=evidence or {},
        evidence_sources=tuple(evidence_sources or []),
        belief_ids=b_ids,
        confidence_delta=confidence_delta,
        dedupe_key=_make_dedupe_key(category.value, topic_norm, b_ids),
        recommended_goal_title=recommended_goal_title,
        metadata=metadata or {},
    )


# -- Goal title mapping --

GOAL_TITLE_MAP = {
    FindingCategory.CONTRADICTION.value: "Rozwiaz sprzecznosc: {}",
    FindingCategory.OVERCONFIDENT.value: "Zweryfikuj egzaminem: {}",
    FindingCategory.UNDERCONFIDENT.value: "Zaktualizuj pewnosc: {}",
    FindingCategory.SHALLOW_KNOWLEDGE.value: "Pogleb wiedze: {}",
    FindingCategory.UNRESOLVED_DISPUTE.value: "Rozwiaz spor: {}",
    FindingCategory.COVERAGE_GAP.value: "Dokoncz nauke: {}",
    FindingCategory.STALE_KNOWLEDGE.value: "Odswiez wiedze: {}",
}


@dataclass
class CritiqueReport:
    """Complete critique report from one analysis cycle."""

    report_id: str = field(default_factory=lambda: _gen_id("cr"))
    timestamp: float = field(default_factory=time.time)
    trigger: str = "periodic"     # periodic / post_validation / post_maintenance / manual

    # Core results
    findings: List[CritiqueFinding] = field(default_factory=list)
    goals_created: List[str] = field(default_factory=list)
    llm_summary: Optional[str] = None  # Decoration only
    duration_ms: float = 0.0
    error: Optional[str] = None

    # Operational stats
    findings_total: int = 0            # Before cap
    findings_by_category: Dict[str, int] = field(default_factory=dict)
    findings_by_severity: Dict[str, int] = field(default_factory=dict)
    suppressed_duplicates: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "report_id": self.report_id,
            "timestamp": self.timestamp,
            "trigger": self.trigger,
            "findings": [f.to_dict() for f in self.findings],
            "goals_created": self.goals_created,
            "llm_summary": self.llm_summary,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "findings_total": self.findings_total,
            "findings_by_category": self.findings_by_category,
            "findings_by_severity": self.findings_by_severity,
            "suppressed_duplicates": self.suppressed_duplicates,
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CritiqueReport":
        findings = [
            CritiqueFinding.from_dict(f)
            for f in d.get("findings", [])
        ]
        return cls(
            report_id=d.get("report_id", _gen_id("cr")),
            timestamp=d.get("timestamp", time.time()),
            trigger=d.get("trigger", "periodic"),
            findings=findings,
            goals_created=d.get("goals_created", []),
            llm_summary=d.get("llm_summary"),
            duration_ms=d.get("duration_ms", 0.0),
            error=d.get("error"),
            findings_total=d.get("findings_total", 0),
            findings_by_category=d.get("findings_by_category", {}),
            findings_by_severity=d.get("findings_by_severity", {}),
            suppressed_duplicates=d.get("suppressed_duplicates", 0),
        )


# Limits
MAX_FINDINGS_PER_REPORT = 5
MAX_PROPOSED_GOALS_FROM_CRITIQUE = 3
DEFAULT_CRITIQUE_COOLDOWN_SEC = 28800  # 8 hours
COVERAGE_GRACE_PERIOD_DAYS = 3        # Don't report fresh files
