"""
Knowledge Auditor - Pre-Learn Audit Layer (Phase 2).

Checks what Maria already knows about a topic, identifies gaps,
quality issues, and decides what kind of cognitive need to post
to the bulletin board.

Zero LLM. Uses existing subsystems:
- MemoryQuery: topic summary, knowledge gaps
- BeliefStore: confidence, freshness, coverage
- CriticAgent findings: contradictions, staleness, shallow knowledge
- KnowledgeAnalyzer: file status, topic coverage

Returns an AuditReport that drives the bulletin board postings.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GapType(Enum):
    """What kind of knowledge gap was detected."""
    NO_MATERIAL = "no_material"           # Topic not covered at all
    SHALLOW = "shallow"                   # Only surface-level knowledge
    LOW_CONFIDENCE = "low_confidence"     # Beliefs with low confidence
    STALE = "stale"                       # Knowledge decaying
    CONTRADICTIONS = "contradictions"     # Conflicting beliefs
    NO_EXAM = "no_exam"                   # Learned but never tested
    TOPIC_TOO_BROAD = "topic_too_broad"   # Topic needs decomposition


@dataclass
class KnowledgeGap:
    """Single identified gap in Maria's knowledge."""
    gap_type: GapType
    topic: str
    severity: float             # 0.0-1.0 (higher = more urgent)
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "gap_type": self.gap_type.value,
            "topic": self.topic,
            "severity": round(self.severity, 3),
            "description": self.description,
            "metadata": self.metadata,
        }


@dataclass
class AuditReport:
    """Result of auditing Maria's knowledge on a topic."""
    topic: str
    known: bool                           # Does Maria know anything about this?
    files_count: int = 0                  # Files in knowledge_index
    beliefs_count: int = 0                # Related beliefs
    avg_confidence: float = 0.0           # Average confidence across sources
    freshness: float = 0.0               # How recent the knowledge is
    gaps: List[KnowledgeGap] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)
    audit_ts: float = field(default_factory=time.time)

    @property
    def has_gaps(self) -> bool:
        return len(self.gaps) > 0

    @property
    def worst_gap_severity(self) -> float:
        if not self.gaps:
            return 0.0
        return max(g.severity for g in self.gaps)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "known": self.known,
            "files_count": self.files_count,
            "beliefs_count": self.beliefs_count,
            "avg_confidence": round(self.avg_confidence, 3),
            "freshness": round(self.freshness, 3),
            "gaps": [g.to_dict() for g in self.gaps],
            "suggested_actions": self.suggested_actions,
            "audit_ts": self.audit_ts,
        }


class KnowledgeAuditor:
    """
    Audits Maria's knowledge on a given topic.

    Checks beliefs, coverage, quality issues, and produces
    an AuditReport with identified gaps and suggested actions.
    """

    def __init__(self):
        self._memory_query = None
        self._belief_store = None
        self._critic_agent = None
        self._knowledge_analyzer = None

    def set_memory_query(self, mq) -> None:
        self._memory_query = mq

    def set_belief_store(self, bs) -> None:
        self._belief_store = bs

    def set_critic_agent(self, ca) -> None:
        self._critic_agent = ca

    def set_knowledge_analyzer(self, ka) -> None:
        self._knowledge_analyzer = ka

    def audit_topic(self, topic: str) -> AuditReport:
        """
        Run full audit on a topic. Returns AuditReport with gaps.

        Checks in order:
        1. Does Maria know anything? (MemoryQuery)
        2. What's the confidence level? (beliefs)
        3. Are there quality problems? (critic findings)
        4. Is there exam coverage? (knowledge_index)
        5. Is knowledge stale? (freshness)
        """
        report = AuditReport(topic=topic, known=False)

        # Step 1: Query existing knowledge
        summary = self._get_topic_summary(topic)
        if summary and summary.get("known"):
            report.known = True
            report.files_count = summary.get("files_count", 0)
            report.beliefs_count = summary.get("beliefs_count", 0)
            report.avg_confidence = summary.get("avg_confidence", 0.0)
            report.freshness = summary.get("freshness", 0.0)
        else:
            # No knowledge at all
            report.gaps.append(KnowledgeGap(
                gap_type=GapType.NO_MATERIAL,
                topic=topic,
                severity=0.9,
                description=f"Maria nie ma wiedzy na temat: {topic}",
            ))
            report.suggested_actions.append("need_material")
            return report

        # Step 2: Check confidence
        if report.avg_confidence < 0.4:
            report.gaps.append(KnowledgeGap(
                gap_type=GapType.LOW_CONFIDENCE,
                topic=topic,
                severity=0.7,
                description=f"Niski confidence ({report.avg_confidence:.0%}) dla: {topic}",
                metadata={"avg_confidence": report.avg_confidence},
            ))
            report.suggested_actions.append("need_material")

        # Step 3: Check for shallow knowledge
        if report.files_count > 0 and report.beliefs_count < 2:
            report.gaps.append(KnowledgeGap(
                gap_type=GapType.SHALLOW,
                topic=topic,
                severity=0.5,
                description=f"Plytka wiedza o: {topic} ({report.beliefs_count} beliefs, {report.files_count} files)",
                metadata={"beliefs": report.beliefs_count, "files": report.files_count},
            ))
            report.suggested_actions.append("need_material")

        # Step 4: Check staleness
        if report.freshness < 0.3:
            report.gaps.append(KnowledgeGap(
                gap_type=GapType.STALE,
                topic=topic,
                severity=0.4,
                description=f"Przestarzala wiedza o: {topic} (freshness={report.freshness:.0%})",
                metadata={"freshness": report.freshness},
            ))
            report.suggested_actions.append("need_review")

        # Step 5: Check critic findings (if available)
        self._check_critic_findings(topic, report)

        # Step 6: Check exam coverage
        self._check_exam_coverage(topic, report)

        # Deduplicate suggested actions
        report.suggested_actions = list(dict.fromkeys(report.suggested_actions))

        return report

    def _get_topic_summary(self, topic: str) -> Optional[Dict]:
        """Query MemoryQuery for topic summary."""
        if self._memory_query is None:
            return None
        try:
            return self._memory_query.get_topic_summary(topic)
        except Exception as e:
            logger.debug(f"[AUDITOR] MemoryQuery failed for {topic}: {e}")
            return None

    def _check_critic_findings(self, topic: str, report: AuditReport) -> None:
        """Check if critic has flagged quality issues for this topic."""
        if self._critic_agent is None:
            return
        try:
            # Get recent critique report
            recent = getattr(self._critic_agent, 'get_last_report', None)
            if recent is None:
                return
            critique_report = recent()
            if critique_report is None:
                return

            topic_lower = topic.lower()
            for finding in critique_report.findings:
                # Check if finding relates to our topic
                finding_topic = getattr(finding, 'topic', '') or ''
                if topic_lower in finding_topic.lower():
                    if finding.category.value == "contradiction":
                        report.gaps.append(KnowledgeGap(
                            gap_type=GapType.CONTRADICTIONS,
                            topic=topic,
                            severity=0.8,
                            description=f"Sprzecznosci w wiedzy o: {topic}",
                            metadata={"finding_id": finding.finding_id},
                        ))
                        report.suggested_actions.append("need_review")
        except Exception as e:
            logger.debug(f"[AUDITOR] Critic check failed: {e}")

    def _check_exam_coverage(self, topic: str, report: AuditReport) -> None:
        """Check if topic has been tested via exams."""
        if self._knowledge_analyzer is None:
            return
        try:
            snapshot = self._knowledge_analyzer.get_snapshot()
            by_status = snapshot.get("files_by_status", {})
            # Files that are "completed" have been examined
            # Files that are "learned" have NOT been examined yet
            learned = by_status.get("learned", [])

            topic_lower = topic.lower()
            untested = [
                f for f in learned
                if topic_lower in f.lower()
            ]
            if untested:
                report.gaps.append(KnowledgeGap(
                    gap_type=GapType.NO_EXAM,
                    topic=topic,
                    severity=0.3,
                    description=f"{len(untested)} files learned but not tested for: {topic}",
                    metadata={"untested_files": untested[:5]},
                ))
                report.suggested_actions.append("need_test")
        except Exception as e:
            logger.debug(f"[AUDITOR] Exam coverage check failed: {e}")
