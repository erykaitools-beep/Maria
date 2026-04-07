"""
Faza G: KnowledgeCritic - rule-based knowledge quality analysis.

READ-ONLY. Zero LLM. Zero side effects.
Reads BeliefStore + JSONL sources, produces CritiqueFinding list.
Does NOT modify beliefs, create goals, or change any state.

7 analysis dimensions:
1. Contradiction - conflicting beliefs about same entity
2. Overconfident - high confidence, weak evidence
3. Underconfident - low confidence despite strong evidence
4. Shallow knowledge - poor support depth
5. Unresolved disputes - high-severity disputes from Faza F
6. Coverage gaps - partially learned / no exam (with grace period)
7. Stale knowledge - decaying confidence near floor

ADR-028: Coherence/calibration critic, not truth engine.
ADR-013: Rule-based, deterministic, testable.
"""

import json
import logging
import math
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from agent_core.critic.critique_model import (
    CritiqueFinding,
    FindingCategory,
    FindingSeverity,
    SuggestedCritiqueAction,
    GOAL_TITLE_MAP,
    MAX_FINDINGS_PER_REPORT,
    COVERAGE_GRACE_PERIOD_DAYS,
    create_finding,
    _normalize_topic,
)

logger = logging.getLogger(__name__)

# Decay constants (mirrored from belief_maintenance.py, read-only use)
_DECAY_HALF_LIVES = {
    "fact": 90.0,
    "observation": 30.0,
    "hypothesis": 14.0,
}
_DECAY_FLOOR = 0.05
_SECONDS_PER_DAY = 86400.0

# Thresholds
_CONTRADICTION_CONFIDENCE_GAP = 0.4
_CONTRADICTION_MIN_CONFIDENCE = 0.3
_OVERCONFIDENT_BELIEF_THRESHOLD = 0.7
_OVERCONFIDENT_EXAM_THRESHOLD = 0.5
_UNDERCONFIDENT_BELIEF_THRESHOLD = 0.4
_UNDERCONFIDENT_EXAM_THRESHOLD = 0.7
_SHALLOW_MIN_BELIEFS = 2
_DISPUTE_MIN_UNRESOLVED = 2
_STALE_CONFIDENCE_THRESHOLD = 0.15
_STALE_DAYS_NO_EXAM = 30

# Negation patterns for contradiction detection (PL + EN)
_NEGATION_PATTERNS = re.compile(
    r"\bnie\b|\bnot\b|\bnever\b|\bnigdy\b|\bbrak\b|\bwithout\b|\bbez\b",
    re.IGNORECASE,
)

# Number extraction for detecting numeric contradictions
_NUMBER_PATTERN = re.compile(r"\b(\d+(?:[.,]\d+)?)\b")


class KnowledgeCritic:
    """
    Rule-based knowledge quality analyzer.

    READ-ONLY: reads data, returns findings. Zero side effects.
    """

    def __init__(
        self,
        belief_store=None,
        dispute_log=None,
        project_root: str = ".",
    ):
        self._belief_store = belief_store
        self._dispute_log = dispute_log
        self._root = Path(project_root)
        self._meta = self._root / "meta_data"
        self._memory = self._root / "memory"

    def analyze(self) -> Tuple[List[CritiqueFinding], int]:
        """
        Run all 7 analysis dimensions.

        Returns:
            (findings capped to MAX_FINDINGS_PER_REPORT, total_before_cap)
            Sorted by severity (CRITICAL > WARNING > INFO) then evidence count.
        """
        all_findings: List[CritiqueFinding] = []

        # Run each dimension, catching errors to not block others
        for method in [
            self._find_contradictions,
            self._find_overconfident,
            self._find_underconfident,
            self._find_shallow_knowledge,
            self._find_unresolved_disputes,
            self._find_coverage_gaps,
            self._find_stale_knowledge,
        ]:
            try:
                findings = method()
                all_findings.extend(findings)
            except Exception as e:
                logger.warning(
                    "[Critic] %s failed: %s", method.__name__, e,
                )

        # Dedup by dedupe_key
        seen_keys: Set[str] = set()
        deduped: List[CritiqueFinding] = []
        for f in all_findings:
            if f.dedupe_key and f.dedupe_key in seen_keys:
                continue
            if f.dedupe_key:
                seen_keys.add(f.dedupe_key)
            deduped.append(f)

        total = len(deduped)

        # Sort: severity (lower order = more severe), then evidence size desc
        deduped.sort(
            key=lambda f: (f.severity_order, -len(f.belief_ids)),
        )

        # Cap
        capped = deduped[:MAX_FINDINGS_PER_REPORT]
        return capped, total

    # ═══════════════════════════════════════════════════════
    # 1. CONTRADICTION
    # ═══════════════════════════════════════════════════════

    def _find_contradictions(self) -> List[CritiqueFinding]:
        """Find conflicting beliefs about same entity."""
        if self._belief_store is None:
            return []

        findings = []
        beliefs = self._get_current_beliefs()

        # Group by normalized entity
        by_entity: Dict[str, list] = defaultdict(list)
        for b in beliefs:
            key = _normalize_topic(b.entity)
            by_entity[key].append(b)

        for entity_key, group in by_entity.items():
            if len(group) < 2:
                continue

            # Check pairs within entity group
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    b1, b2 = group[i], group[j]
                    contradiction = self._check_contradiction(b1, b2)
                    if contradiction:
                        both_high = (
                            b1.confidence > 0.5 and b2.confidence > 0.5
                        )
                        severity = (
                            FindingSeverity.CRITICAL
                            if both_high
                            else FindingSeverity.WARNING
                        )
                        findings.append(create_finding(
                            category=FindingCategory.CONTRADICTION,
                            severity=severity,
                            topic=b1.entity,
                            description=contradiction,
                            suggested_action=SuggestedCritiqueAction.RESOLVE,
                            evidence={
                                "belief_a": {
                                    "id": b1.belief_id,
                                    "content": b1.content[:200],
                                    "confidence": b1.confidence,
                                    "source": b1.source.value if hasattr(b1.source, 'value') else str(b1.source),
                                },
                                "belief_b": {
                                    "id": b2.belief_id,
                                    "content": b2.content[:200],
                                    "confidence": b2.confidence,
                                    "source": b2.source.value if hasattr(b2.source, 'value') else str(b2.source),
                                },
                                "reason": contradiction,
                            },
                            evidence_sources=["belief_store"],
                            belief_ids=[b1.belief_id, b2.belief_id],
                            recommended_goal_title=GOAL_TITLE_MAP.get(
                                FindingCategory.CONTRADICTION.value, "{}"
                            ).format(b1.entity),
                        ))

        return findings

    def _check_contradiction(self, b1, b2) -> Optional[str]:
        """
        Check if two beliefs about the same entity are contradictory.

        Returns description string if contradiction found, None otherwise.
        Requires comparable predicate/slot AND conflicting value.
        Does NOT flag different aspects of the same entity.
        """
        # Same entity but different sources -> check content
        if b1.source_id == b2.source_id and b1.source == b2.source:
            return None  # Same source, same entity = refinement, not contradiction

        # Check 1: Negation patterns
        has_negation_1 = bool(_NEGATION_PATTERNS.search(b1.content))
        has_negation_2 = bool(_NEGATION_PATTERNS.search(b2.content))
        if has_negation_1 != has_negation_2:
            # One negates, other doesn't - potential contradiction
            # Verify they discuss similar subject by word overlap
            words_1 = set(b1.content.lower().split())
            words_2 = set(b2.content.lower().split())
            overlap = len(words_1 & words_2)
            if overlap >= 3:
                return (
                    f"Negation conflict: '{b1.content[:80]}' vs "
                    f"'{b2.content[:80]}'"
                )

        # Check 2: Numeric contradiction (same topic, different numbers)
        nums_1 = _NUMBER_PATTERN.findall(b1.content)
        nums_2 = _NUMBER_PATTERN.findall(b2.content)
        if nums_1 and nums_2:
            # Both have numbers - check if same context but different values
            words_1 = set(b1.content.lower().split()) - set(nums_1)
            words_2 = set(b2.content.lower().split()) - set(nums_2)
            overlap = len(words_1 & words_2)
            if overlap >= 3 and set(nums_1) != set(nums_2):
                return (
                    f"Numeric conflict: '{b1.content[:80]}' vs "
                    f"'{b2.content[:80]}'"
                )

        # Check 3: High confidence gap with different sources
        conf_gap = abs(b1.confidence - b2.confidence)
        if (
            conf_gap > _CONTRADICTION_CONFIDENCE_GAP
            and b1.confidence > _CONTRADICTION_MIN_CONFIDENCE
            and b2.confidence > _CONTRADICTION_MIN_CONFIDENCE
            and str(b1.source) != str(b2.source)
        ):
            # Different sources, big confidence gap on same entity
            # Check belief types differ (FACT vs HYPOTHESIS)
            bt1 = b1.belief_type.value if hasattr(b1.belief_type, 'value') else str(b1.belief_type)
            bt2 = b2.belief_type.value if hasattr(b2.belief_type, 'value') else str(b2.belief_type)
            if bt1 != bt2:
                return (
                    f"Type/confidence conflict: {bt1}({b1.confidence:.2f}) "
                    f"vs {bt2}({b2.confidence:.2f})"
                )

        return None

    # ═══════════════════════════════════════════════════════
    # 2. OVERCONFIDENT
    # ═══════════════════════════════════════════════════════

    def _find_overconfident(self) -> List[CritiqueFinding]:
        """Find beliefs with high confidence but weak evidence."""
        if self._belief_store is None:
            return []

        findings = []
        beliefs = self._get_current_beliefs()
        exam_map = self._load_exam_map()  # file_id -> {best_score, count, latest_score}

        for b in beliefs:
            if b.confidence <= _OVERCONFIDENT_BELIEF_THRESHOLD:
                continue

            source_id = b.source_id
            exam_info = exam_map.get(source_id)

            if exam_info is None:
                # No exam at all for this source
                findings.append(create_finding(
                    category=FindingCategory.OVERCONFIDENT,
                    severity=FindingSeverity.WARNING,
                    topic=b.entity,
                    description=(
                        f"Confidence {b.confidence:.2f} but no exam verification "
                        f"for source '{source_id}'"
                    ),
                    suggested_action=SuggestedCritiqueAction.VERIFY,
                    evidence={
                        "belief_confidence": b.confidence,
                        "exam_count": 0,
                        "calibration_gap": b.confidence,
                    },
                    evidence_sources=["belief_store", "exam_results"],
                    belief_ids=[b.belief_id],
                    confidence_delta=b.confidence,
                    recommended_goal_title=GOAL_TITLE_MAP.get(
                        FindingCategory.OVERCONFIDENT.value, "{}"
                    ).format(b.entity),
                ))
            elif exam_info["weighted_score"] < _OVERCONFIDENT_EXAM_THRESHOLD:
                # Exam exists but score is low
                gap = b.confidence - exam_info["weighted_score"]
                findings.append(create_finding(
                    category=FindingCategory.OVERCONFIDENT,
                    severity=FindingSeverity.WARNING,
                    topic=b.entity,
                    description=(
                        f"Confidence {b.confidence:.2f} but weighted exam "
                        f"score {exam_info['weighted_score']:.2f} "
                        f"({exam_info['count']} exams)"
                    ),
                    suggested_action=SuggestedCritiqueAction.VERIFY,
                    evidence={
                        "belief_confidence": b.confidence,
                        "weighted_exam_score": exam_info["weighted_score"],
                        "exam_count": exam_info["count"],
                        "calibration_gap": gap,
                    },
                    evidence_sources=["belief_store", "exam_results"],
                    belief_ids=[b.belief_id],
                    confidence_delta=gap,
                    recommended_goal_title=GOAL_TITLE_MAP.get(
                        FindingCategory.OVERCONFIDENT.value, "{}"
                    ).format(b.entity),
                ))

        return findings

    # ═══════════════════════════════════════════════════════
    # 3. UNDERCONFIDENT
    # ═══════════════════════════════════════════════════════

    def _find_underconfident(self) -> List[CritiqueFinding]:
        """Find beliefs with low confidence despite strong exam evidence."""
        if self._belief_store is None:
            return []

        findings = []
        beliefs = self._get_current_beliefs()
        exam_map = self._load_exam_map()

        for b in beliefs:
            if b.confidence >= _UNDERCONFIDENT_BELIEF_THRESHOLD:
                continue

            exam_info = exam_map.get(b.source_id)
            if exam_info is None:
                continue

            if exam_info["weighted_score"] >= _UNDERCONFIDENT_EXAM_THRESHOLD:
                gap = exam_info["weighted_score"] - b.confidence
                findings.append(create_finding(
                    category=FindingCategory.UNDERCONFIDENT,
                    severity=FindingSeverity.WARNING,
                    topic=b.entity,
                    description=(
                        f"Confidence {b.confidence:.2f} but weighted exam "
                        f"score {exam_info['weighted_score']:.2f} "
                        f"({exam_info['count']} exams)"
                    ),
                    suggested_action=SuggestedCritiqueAction.REVIEW,
                    evidence={
                        "belief_confidence": b.confidence,
                        "weighted_exam_score": exam_info["weighted_score"],
                        "exam_count": exam_info["count"],
                        "calibration_gap": gap,
                    },
                    evidence_sources=["belief_store", "exam_results"],
                    belief_ids=[b.belief_id],
                    confidence_delta=-gap,
                    recommended_goal_title=GOAL_TITLE_MAP.get(
                        FindingCategory.UNDERCONFIDENT.value, "{}"
                    ).format(b.entity),
                ))

        return findings

    # ═══════════════════════════════════════════════════════
    # 4. SHALLOW KNOWLEDGE
    # ═══════════════════════════════════════════════════════

    def _find_shallow_knowledge(self) -> List[CritiqueFinding]:
        """Find topics with poor support depth."""
        if self._belief_store is None:
            return []

        findings = []
        beliefs = self._get_current_beliefs()
        exam_map = self._load_exam_map()

        # Group by tags (topics)
        by_topic: Dict[str, list] = defaultdict(list)
        for b in beliefs:
            tags = b.tags if isinstance(b.tags, (list, tuple)) else []
            for tag in tags:
                by_topic[_normalize_topic(tag)].append(b)

        # Also check dispute resolution history
        dispute_files: Set[str] = set()
        if self._dispute_log is not None:
            try:
                stats = self._dispute_log.get_stats()
                # If any disputes are resolved, those files have been through review
                for r in self._dispute_log.get_recent(limit=200):
                    if isinstance(r, dict) and r.get("resolved"):
                        dispute_files.add(r.get("file_id", ""))
            except Exception:
                pass

        for topic, group in by_topic.items():
            if len(group) < _SHALLOW_MIN_BELIEFS:
                continue

            bt_vals = [
                b.belief_type.value
                if hasattr(b.belief_type, 'value')
                else str(b.belief_type)
                for b in group
            ]

            fact_count = bt_vals.count("fact")
            sources = set(b.source_id for b in group)
            has_exam = any(b.source_id in exam_map for b in group)
            has_dispute_resolution = any(
                b.source_id in dispute_files for b in group
            )

            is_shallow = False
            reason_parts = []

            if fact_count == 0:
                is_shallow = True
                reason_parts.append("no facts (only hypothesis/observation)")

            if len(sources) <= 1 and fact_count > 0:
                is_shallow = True
                reason_parts.append(f"all from single source ({sources.pop() if sources else 'unknown'})")

            if not has_exam and not has_dispute_resolution and fact_count == 0:
                is_shallow = True
                if "no facts" not in str(reason_parts):
                    reason_parts.append("no exam and no dispute resolution")

            if is_shallow:
                topic_display = group[0].tags[0] if group[0].tags else topic
                findings.append(create_finding(
                    category=FindingCategory.SHALLOW_KNOWLEDGE,
                    severity=FindingSeverity.WARNING,
                    topic=topic_display,
                    description=(
                        f"Topic '{topic_display}' has {len(group)} beliefs but "
                        f"shallow support: {', '.join(reason_parts)}"
                    ),
                    suggested_action=SuggestedCritiqueAction.LEARN_MORE,
                    evidence={
                        "belief_count": len(group),
                        "fact_count": fact_count,
                        "source_count": len(sources),
                        "has_exam": has_exam,
                        "has_dispute_resolution": has_dispute_resolution,
                        "reasons": reason_parts,
                    },
                    evidence_sources=["belief_store"],
                    belief_ids=[b.belief_id for b in group[:5]],
                    recommended_goal_title=GOAL_TITLE_MAP.get(
                        FindingCategory.SHALLOW_KNOWLEDGE.value, "{}"
                    ).format(topic_display),
                ))

        return findings

    # ═══════════════════════════════════════════════════════
    # 5. UNRESOLVED DISPUTES
    # ═══════════════════════════════════════════════════════

    def _find_unresolved_disputes(self) -> List[CritiqueFinding]:
        """Find files/topics with high-severity unresolved disputes."""
        if self._dispute_log is None:
            return []

        findings = []
        try:
            unresolved = self._dispute_log.get_unresolved(limit=50)
        except Exception:
            return []

        # Group by file_id
        by_file: Dict[str, list] = defaultdict(list)
        for d in unresolved:
            if isinstance(d, dict):
                by_file[d.get("file_id", "unknown")].append(d)

        for file_id, disputes in by_file.items():
            high_count = sum(
                1 for d in disputes if d.get("severity") == "high"
            )
            medium_count = sum(
                1 for d in disputes if d.get("severity") == "medium"
            )

            if high_count >= _DISPUTE_MIN_UNRESOLVED:
                severity = FindingSeverity.CRITICAL
            elif medium_count >= _DISPUTE_MIN_UNRESOLVED:
                severity = FindingSeverity.WARNING
            else:
                continue

            findings.append(create_finding(
                category=FindingCategory.UNRESOLVED_DISPUTE,
                severity=severity,
                topic=file_id,
                description=(
                    f"File '{file_id}' has {high_count} high + "
                    f"{medium_count} medium unresolved disputes"
                ),
                suggested_action=SuggestedCritiqueAction.RESOLVE,
                evidence={
                    "file_id": file_id,
                    "high_severity": high_count,
                    "medium_severity": medium_count,
                    "total_unresolved": len(disputes),
                },
                evidence_sources=["dispute_log"],
                recommended_goal_title=GOAL_TITLE_MAP.get(
                    FindingCategory.UNRESOLVED_DISPUTE.value, "{}"
                ).format(file_id),
            ))

        return findings

    # ═══════════════════════════════════════════════════════
    # 6. COVERAGE GAPS
    # ═══════════════════════════════════════════════════════

    def _find_coverage_gaps(self) -> List[CritiqueFinding]:
        """Find partially learned files / completed without exam."""
        findings = []
        ki_path = self._memory / "knowledge_index.jsonl"
        exam_map = self._load_exam_map()
        now = time.time()
        grace_cutoff = now - (COVERAGE_GRACE_PERIOD_DAYS * _SECONDS_PER_DAY)

        records = self._read_jsonl_merge(ki_path, key_field="id")

        for file_id, record in records.items():
            status = record.get("status", "")
            try:
                updated = float(record.get("updated_at", record.get("timestamp", now)))
            except (TypeError, ValueError):
                updated = now

            # Grace period - skip fresh files
            if updated > grace_cutoff:
                continue

            # Skip actively being learned
            if status in ("learning", "in_progress"):
                continue

            chunks_learned = record.get("chunks_learned", 0)
            total_chunks = record.get("total_chunks", 0)
            has_exam = file_id in exam_map

            is_gap = False
            reason = ""

            if status == "partial" or (
                total_chunks > 0 and 0 < chunks_learned < total_chunks
            ):
                is_gap = True
                reason = (
                    f"Partially learned: {chunks_learned}/{total_chunks} chunks"
                )
            elif status == "completed" and not has_exam:
                is_gap = True
                reason = "Completed but no exam verification"

            if is_gap:
                findings.append(create_finding(
                    category=FindingCategory.COVERAGE_GAP,
                    severity=FindingSeverity.INFO,
                    topic=file_id,
                    description=f"File '{file_id}': {reason}",
                    suggested_action=(
                        SuggestedCritiqueAction.LEARN_MORE
                        if "Partially" in reason
                        else SuggestedCritiqueAction.VERIFY
                    ),
                    evidence={
                        "file_id": file_id,
                        "status": status,
                        "chunks_learned": chunks_learned,
                        "total_chunks": total_chunks,
                        "has_exam": has_exam,
                        "age_days": (now - updated) / _SECONDS_PER_DAY,
                    },
                    evidence_sources=["knowledge_index"],
                    recommended_goal_title=GOAL_TITLE_MAP.get(
                        FindingCategory.COVERAGE_GAP.value, "{}"
                    ).format(file_id),
                ))

        return findings

    # ═══════════════════════════════════════════════════════
    # 7. STALE KNOWLEDGE
    # ═══════════════════════════════════════════════════════

    def _find_stale_knowledge(self) -> List[CritiqueFinding]:
        """Find beliefs with decayed confidence near floor."""
        if self._belief_store is None:
            return []

        findings = []
        beliefs = self._get_current_beliefs()
        exam_map = self._load_exam_map()
        now = time.time()

        # Group beliefs by topic for per-topic staleness
        by_topic: Dict[str, list] = defaultdict(list)
        for b in beliefs:
            by_topic[_normalize_topic(b.entity)].append(b)

        for topic, group in by_topic.items():
            worst_belief = None
            worst_decayed = 1.0

            for b in group:
                decayed = self._compute_decayed_confidence(b, now)
                if decayed < worst_decayed:
                    worst_decayed = decayed
                    worst_belief = b

            if worst_belief is None:
                continue

            # Check if near floor
            if worst_decayed < _STALE_CONFIDENCE_THRESHOLD:
                bt_val = (
                    worst_belief.belief_type.value
                    if hasattr(worst_belief.belief_type, 'value')
                    else str(worst_belief.belief_type)
                )
                severity = (
                    FindingSeverity.WARNING
                    if worst_decayed < 0.1
                    else FindingSeverity.INFO
                )
                age_days = (now - worst_belief.updated_at) / _SECONDS_PER_DAY

                findings.append(create_finding(
                    category=FindingCategory.STALE_KNOWLEDGE,
                    severity=severity,
                    topic=worst_belief.entity,
                    description=(
                        f"Topic '{worst_belief.entity}': effective confidence "
                        f"{worst_decayed:.2f} (original {worst_belief.confidence:.2f}, "
                        f"{bt_val}, {age_days:.0f} days old)"
                    ),
                    suggested_action=SuggestedCritiqueAction.REFRESH,
                    evidence={
                        "original_confidence": worst_belief.confidence,
                        "decayed_confidence": worst_decayed,
                        "belief_type": bt_val,
                        "age_days": age_days,
                    },
                    evidence_sources=["belief_store"],
                    belief_ids=[worst_belief.belief_id],
                    metadata={
                        "volatility_hint": (
                            "volatile" if bt_val == "hypothesis" else "stable"
                        ),
                        "staleness_reason": (
                            "near_floor"
                            if worst_decayed < 0.1
                            else "approaching_floor"
                        ),
                    },
                    recommended_goal_title=GOAL_TITLE_MAP.get(
                        FindingCategory.STALE_KNOWLEDGE.value, "{}"
                    ).format(worst_belief.entity),
                ))

        return findings

    # ═══════════════════════════════════════════════════════
    # Data access helpers (READ-ONLY)
    # ═══════════════════════════════════════════════════════

    def _get_current_beliefs(self) -> list:
        """Get non-superseded beliefs from store."""
        if self._belief_store is None:
            return []
        try:
            all_beliefs = self._belief_store._beliefs
            return [
                b for b in all_beliefs.values()
                if b.superseded_by is None
            ]
        except Exception:
            return []

    def _load_exam_map(self) -> Dict[str, Dict[str, Any]]:
        """
        Load exam results grouped by file_id.

        Returns: {file_id: {best_score, weighted_score, count, latest_score}}
        Weighted score: exponential recency weighting.
        """
        path = self._memory / "exam_results.jsonl"
        if not path.exists():
            return {}

        # Collect all exams per file
        by_file: Dict[str, list] = defaultdict(list)
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        file_id = record.get("file") or record.get("file_id", "")
                        score = record.get("score", record.get("exam_score", 0.0))
                        ts = record.get("timestamp", 0.0)
                        if file_id:
                            by_file[file_id].append({
                                "score": float(score),
                                "timestamp": float(ts),
                            })
                    except (json.JSONDecodeError, ValueError):
                        continue
        except IOError:
            return {}

        result = {}
        for file_id, exams in by_file.items():
            exams.sort(key=lambda e: e["timestamp"])
            scores = [e["score"] for e in exams]
            if not scores:
                continue
            best = max(scores)
            latest = scores[-1]
            count = len(scores)

            # Weighted recent: exponential decay, most recent weighs most
            if count == 1:
                weighted = scores[0]
            else:
                weights = [2.0 ** i for i in range(count)]
                total_w = sum(weights)
                weighted = sum(s * w for s, w in zip(scores, weights)) / total_w

            result[file_id] = {
                "best_score": best,
                "weighted_score": weighted,
                "latest_score": latest,
                "count": count,
            }

        return result

    def _compute_decayed_confidence(self, belief, now: float) -> float:
        """Compute effective confidence after decay (read-only, no side effects)."""
        bt_val = (
            belief.belief_type.value
            if hasattr(belief.belief_type, 'value')
            else str(belief.belief_type)
        )
        half_life = _DECAY_HALF_LIVES.get(bt_val, 30.0)
        age_days = (now - belief.updated_at) / _SECONDS_PER_DAY

        if age_days <= 0:
            return belief.confidence

        decayed = belief.confidence * math.pow(0.5, age_days / half_life)
        return max(decayed, _DECAY_FLOOR)

    def _read_jsonl_merge(
        self, path: Path, key_field: str = "id",
    ) -> Dict[str, Dict[str, Any]]:
        """Read JSONL with MERGE semantics (last record per key wins)."""
        result: Dict[str, Dict[str, Any]] = {}
        if not path.exists():
            return result

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        key = record.get(key_field, "")
                        if key:
                            result[key] = record
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass

        return result
