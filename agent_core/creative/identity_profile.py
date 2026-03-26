"""Persistent cognitive development profile built from system data.

Aggregates growth trajectory, domain strengths/weaknesses, dominant traits,
and capability map from existing JSONL sources. Zero LLM.

Used by PersonalityPolicy and reflection cycle to inform meta-goal generation.
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import time

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CognitiveProfile:
    """Snapshot of Maria's cognitive development state."""
    growth_trajectory: str          # accelerating / stable / slowing / stalled
    dominant_traits: List[str]      # top 3 personality traits by score
    domain_strengths: Dict[str, float]   # topic -> retention (top 5)
    domain_weaknesses: Dict[str, float]  # topic -> retention (bottom 5)
    capability_map: Dict[str, int]       # action_type -> count (what Maria does)
    meta_goal_acceptance_rate: float     # accepted / total proposed
    total_files: int
    completed_files: int
    coverage: float
    built_at: float = field(default_factory=time.time)


class IdentityProfile:
    """Builds CognitiveProfile from existing data sources. Zero LLM."""

    def __init__(self, data_dir: str = "meta_data", memory_dir: str = "memory"):
        self._meta = Path(data_dir)
        self._memory = Path(memory_dir)

    def build(self) -> CognitiveProfile:
        """Build a cognitive profile snapshot from JSONL sources."""
        traits = self._get_trait_scores()
        dominant = sorted(traits.items(), key=lambda x: x[1], reverse=True)[:3]

        domain_map = self._get_domain_retention()
        sorted_domains = sorted(domain_map.items(), key=lambda x: x[1])
        strengths = dict(sorted_domains[-5:]) if sorted_domains else {}
        weaknesses = dict(sorted_domains[:5]) if sorted_domains else {}

        capability = self._get_capability_map()
        acceptance = self._get_meta_goal_acceptance_rate()
        trajectory = self._classify_trajectory()

        learning = self._get_learning_counts()

        return CognitiveProfile(
            growth_trajectory=trajectory,
            dominant_traits=[name for name, _ in dominant],
            domain_strengths=strengths,
            domain_weaknesses=weaknesses,
            capability_map=capability,
            meta_goal_acceptance_rate=acceptance,
            total_files=learning["total"],
            completed_files=learning["completed"],
            coverage=learning["coverage"],
        )

    def _get_trait_scores(self) -> Dict[str, float]:
        """Read trait scores from consciousness_identity.json."""
        path = self._meta / "consciousness_identity.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("trait_scores", {})
            return {
                k: (v.get("score", 0) if isinstance(v, dict) else float(v))
                for k, v in raw.items()
            }
        except (OSError, json.JSONDecodeError, ValueError):
            return {}

    def _get_domain_retention(self) -> Dict[str, float]:
        """Get per-topic retention from knowledge_index.jsonl (MERGE)."""
        path = self._memory / "knowledge_index.jsonl"
        if not path.exists():
            return {}

        # MERGE semantics: last record per id wins
        records: Dict[str, Dict] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        rid = rec.get("id", "")
                        if rid:
                            records[rid] = rec
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return {}

        # Group by topic, average exam scores
        topic_scores: Dict[str, List[float]] = {}
        for rec in records.values():
            topic = rec.get("topic", "unknown")
            score = rec.get("exam_score")
            if score is not None:
                topic_scores.setdefault(topic, []).append(float(score))

        return {
            topic: sum(scores) / len(scores)
            for topic, scores in topic_scores.items()
            if scores
        }

    def _get_capability_map(self) -> Dict[str, int]:
        """Get action type distribution from planner_decisions.jsonl."""
        path = self._meta / "planner_decisions.jsonl"
        if not path.exists():
            return {}

        dist: Counter = Counter()
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        action = rec.get("action_type", "unknown")
                        dist[action] += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        return dict(dist.most_common(15))

    def _get_meta_goal_acceptance_rate(self) -> float:
        """Calculate acceptance rate from creative_meta_goals.jsonl (MERGE)."""
        path = self._meta / "creative_meta_goals.jsonl"
        if not path.exists():
            return 0.0

        goals: Dict[str, Dict] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        gid = rec.get("goal_id", "")
                        if gid:
                            goals[gid] = rec
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return 0.0

        total = len(goals)
        if total == 0:
            return 0.0
        accepted = sum(1 for g in goals.values() if g.get("status") == "accepted")
        return accepted / total

    def _get_learning_counts(self) -> Dict[str, Any]:
        """Get total/completed file counts from knowledge_index."""
        path = self._memory / "knowledge_index.jsonl"
        if not path.exists():
            return {"total": 0, "completed": 0, "coverage": 0.0}

        records: Dict[str, Dict] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        rid = rec.get("id", "")
                        if rid:
                            records[rid] = rec
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        total = len(records)
        completed = sum(
            1 for r in records.values()
            if r.get("status") in ("completed", "learned")
        )
        return {
            "total": total,
            "completed": completed,
            "coverage": completed / max(total, 1),
        }

    def _classify_trajectory(self) -> str:
        """Classify growth trajectory from evaluation reports."""
        path = self._meta / "evaluation_reports.jsonl"
        if not path.exists():
            return "stable"

        velocities = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        v = rec.get("metrics", {}).get("learning_velocity")
                        if v is not None:
                            velocities.append(float(v))
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            return "stable"

        if len(velocities) < 2:
            return "stable"

        # Compare recent half to older half
        mid = len(velocities) // 2
        old_avg = sum(velocities[:mid]) / max(mid, 1)
        new_avg = sum(velocities[mid:]) / max(len(velocities) - mid, 1)

        if new_avg <= 0.01 and old_avg <= 0.01:
            return "stalled"
        if old_avg == 0 and new_avg == 0:
            return "stalled"
        if new_avg > old_avg * 1.2:
            return "accelerating"
        if new_avg < old_avg * 0.8:
            return "slowing"
        return "stable"
