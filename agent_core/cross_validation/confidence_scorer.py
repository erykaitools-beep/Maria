"""
Confidence Scorer - Scores reliability of learned knowledge.

Compares two sets of learning results (summary, key_points, tags)
and produces a confidence score based on agreement level.

Scoring dimensions:
- Summary overlap (semantic similarity via keyword matching)
- Key points coverage (how many points appear in both)
- Tag agreement (intersection / union)

All rule-based, zero LLM. ADR-013 pattern.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Minimum word length for meaningful comparison
MIN_WORD_LEN = 3


def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, normalize whitespace."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _extract_keywords(text: str, min_len: int = MIN_WORD_LEN) -> Set[str]:
    """Extract meaningful keywords from text."""
    words = _normalize_text(text).split()
    return {w for w in words if len(w) >= min_len}


def _jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Jaccard similarity: |intersection| / |union|."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _list_overlap(list_a: List[str], list_b: List[str]) -> float:
    """
    Overlap score between two lists of strings.

    Compares each item from list_a to items in list_b using
    keyword overlap. Returns fraction of list_a items that
    have a match in list_b.
    """
    if not list_a:
        return 1.0 if not list_b else 0.0
    if not list_b:
        return 0.0

    matched = 0
    for item_a in list_a:
        kw_a = _extract_keywords(item_a)
        if not kw_a:
            continue
        # Check if any item in list_b shares keywords
        # Low threshold (0.15) because Polish morphology causes
        # exact-match misses (rosliny vs roslinach, proces vs procesem)
        for item_b in list_b:
            kw_b = _extract_keywords(item_b)
            if _jaccard_similarity(kw_a, kw_b) > 0.15:
                matched += 1
                break

    return matched / len(list_a)


class ConfidenceScorer:
    """
    Scores agreement between two learning results.

    Input: two dicts with {summary, key_points, tags}.
    Output: ConfidenceScore with per-dimension breakdown.
    """

    # Weights for final score
    SUMMARY_WEIGHT = 0.4
    KEY_POINTS_WEIGHT = 0.35
    TAGS_WEIGHT = 0.25

    def score(
        self,
        result_a: Dict[str, Any],
        result_b: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compare two learning results and produce confidence score.

        Args:
            result_a: Primary source {summary, key_points, tags}
            result_b: Secondary source {summary, key_points, tags}

        Returns:
            {
                "overall": 0.0-1.0,
                "summary_similarity": 0.0-1.0,
                "key_points_overlap": 0.0-1.0,
                "tags_agreement": 0.0-1.0,
                "disputes": [...],  # areas of disagreement
            }
        """
        # Summary comparison
        summary_a = result_a.get("summary", "") or result_a.get("summary_simple", "")
        summary_b = result_b.get("summary", "") or result_b.get("summary_simple", "")
        summary_sim = _jaccard_similarity(
            _extract_keywords(summary_a),
            _extract_keywords(summary_b),
        )

        # Key points comparison
        kp_a = result_a.get("key_points", []) or result_a.get("core_ideas", [])
        kp_b = result_b.get("key_points", []) or result_b.get("core_ideas", [])
        kp_overlap_ab = _list_overlap(kp_a, kp_b)
        kp_overlap_ba = _list_overlap(kp_b, kp_a)
        kp_overlap = (kp_overlap_ab + kp_overlap_ba) / 2.0

        # Tags comparison
        tags_a = {_normalize_text(t) for t in (result_a.get("tags", []) or [])}
        tags_b = {_normalize_text(t) for t in (result_b.get("tags", []) or [])}
        tags_agreement = _jaccard_similarity(tags_a, tags_b)

        # Overall score
        overall = (
            summary_sim * self.SUMMARY_WEIGHT
            + kp_overlap * self.KEY_POINTS_WEIGHT
            + tags_agreement * self.TAGS_WEIGHT
        )

        # Detect disputes
        # Thresholds are low because Polish morphology causes
        # exact-match misses even on semantically identical content
        disputes = []
        if summary_sim < 0.1:
            disputes.append({
                "dimension": "summary",
                "severity": "high",
                "detail": "Summaries have very low keyword overlap",
            })
        if kp_overlap < 0.15:
            disputes.append({
                "dimension": "key_points",
                "severity": "high",
                "detail": f"Only {kp_overlap:.0%} key points match between sources",
            })
        if tags_agreement < 0.15:
            disputes.append({
                "dimension": "tags",
                "severity": "medium",
                "detail": f"Tag agreement: {tags_agreement:.0%}",
            })

        return {
            "overall": round(overall, 3),
            "summary_similarity": round(summary_sim, 3),
            "key_points_overlap": round(kp_overlap, 3),
            "tags_agreement": round(tags_agreement, 3),
            "disputes": disputes,
        }
