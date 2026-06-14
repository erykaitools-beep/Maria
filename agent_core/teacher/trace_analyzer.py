"""Decision traces analyzer for skill extraction.

Reads meta_data/decision_traces.jsonl (episode-based traces, ADR-022),
groups by goal_id, surfaces repeating action_type patterns with sufficient
sample size and success rate for the SkillExtractor to consider.

Pure analysis - does not write anything. SkillExtractor consumes
GoalPattern results and decides which become DRAFT skills.

Phase 2a (2026-05-15) - first cut, no LLM yet (Phase 2b adds NIM body
generation). See docs/SKILLS_DESIGN.md.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight trace record (subset of decision_traces.jsonl fields)
# ---------------------------------------------------------------------------


@dataclass
class TraceRecord:
    """Minimal projection of a decision_traces.jsonl entry."""

    episode_id: str
    action_type: str
    goal_id: Optional[str]
    goal_description: str
    success: bool
    started_at: float
    mode: str = ""
    duration_ms: float = 0.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["TraceRecord"]:
        """Build a TraceRecord from a parsed JSONL line. Returns None if
        the trace has no action_type (preliminary / aborted entry)."""
        atype = d.get("action_type", "")
        if not atype:
            return None
        return cls(
            episode_id=d.get("episode_id", ""),
            action_type=atype,
            goal_id=d.get("goal_id"),
            goal_description=d.get("goal_description") or "",
            success=bool(d.get("success", False)),
            started_at=float(d.get("started_at", 0.0)),
            mode=d.get("mode", ""),
            duration_ms=float(d.get("duration_ms", 0.0)),
        )


# ---------------------------------------------------------------------------
# Goal-level pattern aggregate
# ---------------------------------------------------------------------------


@dataclass
class GoalPattern:
    """Aggregate of all traces sharing a goal_id."""

    goal_id: str
    goal_description: str
    episode_count: int
    success_count: int
    action_histogram: Dict[str, int] = field(default_factory=dict)
    action_sequence: List[str] = field(default_factory=list)  # chronological
    sample_episode_ids: List[str] = field(default_factory=list)  # up to 5

    @property
    def success_rate(self) -> float:
        return self.success_count / self.episode_count if self.episode_count else 0.0

    @property
    def dominant_actions(self) -> List[str]:
        """Action types that account for at least 10% of episodes, sorted desc."""
        threshold = max(1, self.episode_count // 10)
        return [
            a for a, c in sorted(
                self.action_histogram.items(), key=lambda x: -x[1]
            )
            if c >= threshold
        ]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_traces(path: Path) -> List[TraceRecord]:
    """Load decision_traces.jsonl into TraceRecord list.

    Silently skips malformed lines and entries without action_type (those
    are typically partial trace stubs from interrupted episodes).
    """
    out: List[TraceRecord] = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            tr = TraceRecord.from_dict(d)
            if tr is not None:
                out.append(tr)
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def group_by_goal(traces: List[TraceRecord]) -> Dict[str, List[TraceRecord]]:
    """Group traces by goal_id. Traces without goal_id are dropped."""
    out: Dict[str, List[TraceRecord]] = defaultdict(list)
    for t in traces:
        if t.goal_id:
            out[t.goal_id].append(t)
    return out


def compute_goal_patterns(
    traces: List[TraceRecord],
    min_episodes: int = 5,
) -> List[GoalPattern]:
    """Compute GoalPattern for each goal that meets min_episodes threshold.

    Default min_episodes=5 mirrors the Hermes "5+ tool calls" heuristic but
    counted at goal scope rather than per-task. Adjusted via parameter.
    """
    grouped = group_by_goal(traces)
    patterns: List[GoalPattern] = []
    for gid, ts in grouped.items():
        if len(ts) < min_episodes:
            continue
        ts_sorted = sorted(ts, key=lambda x: x.started_at)
        histogram = dict(Counter(t.action_type for t in ts_sorted))
        success_count = sum(1 for t in ts_sorted if t.success)
        patterns.append(GoalPattern(
            goal_id=gid,
            goal_description=ts_sorted[0].goal_description,
            episode_count=len(ts_sorted),
            success_count=success_count,
            action_histogram=histogram,
            action_sequence=[t.action_type for t in ts_sorted],
            sample_episode_ids=[t.episode_id for t in ts_sorted[:5]],
        ))
    # Highest success rate first, ties broken by episode_count desc
    patterns.sort(key=lambda p: (-p.success_rate, -p.episode_count))
    return patterns


# ---------------------------------------------------------------------------
# Single-action patterns (cross-goal frequency of standalone actions)
# ---------------------------------------------------------------------------


@dataclass
class ActionPattern:
    """Cross-goal aggregate of a single action_type."""

    action_type: str
    episode_count: int
    success_count: int
    sample_episode_ids: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.episode_count if self.episode_count else 0.0


def compute_action_patterns(
    traces: List[TraceRecord],
    min_episodes: int = 20,
) -> List[ActionPattern]:
    """Aggregate by action_type across all goals (not per-goal).

    Useful when the same action_type works consistently regardless of which
    goal triggers it - candidate for a generic skill independent of goal.
    """
    by_action: Dict[str, List[TraceRecord]] = defaultdict(list)
    for t in traces:
        by_action[t.action_type].append(t)

    out: List[ActionPattern] = []
    for atype, ts in by_action.items():
        if len(ts) < min_episodes:
            continue
        out.append(ActionPattern(
            action_type=atype,
            episode_count=len(ts),
            success_count=sum(1 for t in ts if t.success),
            sample_episode_ids=[t.episode_id for t in ts[:5]],
        ))
    out.sort(key=lambda p: (-p.success_rate, -p.episode_count))
    return out
