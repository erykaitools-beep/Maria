"""Skill extractor - turns trace patterns into DRAFT Skills.

Phase 2a (2026-05-15): template-based generation (deterministic, no LLM).
Phase 2b: NIM-generated rich body (nemotron-49b per ADR-008), with template
remaining as fallback.

Pipeline:
    traces -> GoalPattern + ActionPattern -> SkillCandidate ->
    SkillManager.create_draft(...)

Maria-style gating preserved: extractor only creates DRAFT. Promotion to
SANDBOX requires Eryk approval via SkillManager.promote(approved_by=...).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.skills.skill_model import Skill, SkillStatus
from agent_core.skills.skill_manager import SkillManager
from agent_core.skills.schema import SkillValidationError
from agent_core.teacher.trace_analyzer import (
    ActionPattern,
    GoalPattern,
    TraceRecord,
    compute_action_patterns,
    compute_goal_patterns,
    load_traces,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SkillCandidate - intermediate form before DRAFT Skill creation
# ---------------------------------------------------------------------------


@dataclass
class SkillCandidate:
    """A pattern strong enough to consider materializing as a Skill."""

    kind: str  # "goal_pattern" | "action_pattern"
    name_hint: str  # used as slug for skill name
    description: str
    when_to_use: str
    procedure: str
    pitfalls: str
    verification: str
    source_episode_ids: List[str] = field(default_factory=list)
    trigger_count: int = 0
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Threshold defaults (per docs/SKILLS_DESIGN.md open questions)
# ---------------------------------------------------------------------------

DEFAULT_GOAL_MIN_EPISODES = 5
DEFAULT_GOAL_MIN_SUCCESS_RATE = 0.8
DEFAULT_ACTION_MIN_EPISODES = 50
DEFAULT_ACTION_MIN_SUCCESS_RATE = 0.95


# ---------------------------------------------------------------------------
# Slug normalization
# ---------------------------------------------------------------------------


def _slugify(text: str, max_len: int = 50) -> str:
    """Normalize a string to lowercase-kebab. Drops non-alphanumeric."""
    import re
    text = text.lower()
    # Polish-ish diacritic strip - rough but sufficient for slug
    diacritics = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    }
    for src, dst in diacritics.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "unnamed"


# ---------------------------------------------------------------------------
# Candidate generation from patterns
# ---------------------------------------------------------------------------


def goal_pattern_to_candidate(p: GoalPattern) -> SkillCandidate:
    """Build a SkillCandidate from a GoalPattern using a deterministic template.

    The template captures *what we observed*: dominant actions, success rate,
    sample episodes. It is intentionally factual - Phase 2b will replace
    this with NIM-generated narrative.
    """
    dominant = p.dominant_actions
    actions_str = " + ".join(dominant) if dominant else "no dominant actions"
    histogram_lines = "\n".join(
        f"- {a}: {c} episodes" for a, c in
        sorted(p.action_histogram.items(), key=lambda x: -x[1])
    )

    name_hint = _slugify(f"goal-pattern-{(p.goal_description or p.goal_id)[:40]}")
    description = (
        f"Pattern from goal '{(p.goal_description or p.goal_id)[:80]}': "
        f"{actions_str}"
    )[:140]

    when_to_use = (
        f"When working on goal type similar to: {p.goal_description or p.goal_id}.\n"
        f"Observed {p.episode_count} episodes with success rate {p.success_rate:.0%}."
    )
    procedure = (
        f"Dominant actions across {p.episode_count} episodes (apply in order of frequency):\n"
        f"{histogram_lines}\n\n"
        f"Sample episode IDs for reference: {', '.join(p.sample_episode_ids[:3])}"
    )
    pitfalls = (
        f"Success rate is {p.success_rate:.0%} - {p.episode_count - p.success_count} "
        f"episodes failed across the observed sample. Investigate failure modes "
        f"before relying on this pattern in production."
    )
    verification = (
        f"After applying this skill, expect action types {', '.join(dominant)} to "
        f"appear in action_audit.jsonl with success=true at a rate similar to the "
        f"baseline {p.success_rate:.0%}."
    )

    return SkillCandidate(
        kind="goal_pattern",
        name_hint=name_hint,
        description=description,
        when_to_use=when_to_use,
        procedure=procedure,
        pitfalls=pitfalls,
        verification=verification,
        source_episode_ids=list(p.sample_episode_ids),
        trigger_count=p.episode_count,
        tags=["pattern", "goal_pattern"] + dominant[:3],
    )


def action_pattern_to_candidate(p: ActionPattern) -> SkillCandidate:
    """Build a SkillCandidate from a cross-goal ActionPattern."""
    name_hint = _slugify(f"action-{p.action_type}-reliable")
    description = (
        f"Cross-goal action '{p.action_type}' "
        f"({p.success_rate:.0%} success across {p.episode_count} episodes)"
    )[:140]

    when_to_use = (
        f"When considering action '{p.action_type}' for any goal. "
        f"Observed reliable across {p.episode_count} episodes "
        f"with {p.success_rate:.0%} success rate."
    )
    procedure = (
        f"1. Invoke action '{p.action_type}' on the active goal.\n"
        f"2. Capture result in action_audit.jsonl.\n"
        f"3. Update goal progress based on outcome."
    )
    pitfalls = (
        f"This pattern aggregates {p.episode_count} historical episodes - "
        f"context may have shifted since they were recorded. Re-verify after "
        f"any architectural change to the action handler."
    )
    verification = (
        f"action_audit.jsonl contains success=true entry for action_type="
        f"'{p.action_type}' with no validation failures."
    )

    return SkillCandidate(
        kind="action_pattern",
        name_hint=name_hint,
        description=description,
        when_to_use=when_to_use,
        procedure=procedure,
        pitfalls=pitfalls,
        verification=verification,
        source_episode_ids=list(p.sample_episode_ids),
        trigger_count=p.episode_count,
        tags=["pattern", "action_pattern", p.action_type],
    )


def candidate_to_sections(c: SkillCandidate) -> Dict[str, str]:
    """Convert SkillCandidate body fields to SKILL.md sections map."""
    return {
        "When to Use": c.when_to_use,
        "Procedure": c.procedure,
        "Pitfalls": c.pitfalls,
        "Verification": c.verification,
    }


# ---------------------------------------------------------------------------
# Top-level extractor
# ---------------------------------------------------------------------------


class SkillExtractor:
    """Coordinates traces -> patterns -> candidates -> DRAFT skills.

    Run via extract() with a SkillManager - typically wired in Phase 2b
    to a homeostasis tick. Phase 2a usage is on-demand (CLI / test).
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        traces_path: Path = Path("meta_data/decision_traces.jsonl"),
        goal_min_episodes: int = DEFAULT_GOAL_MIN_EPISODES,
        goal_min_success_rate: float = DEFAULT_GOAL_MIN_SUCCESS_RATE,
        action_min_episodes: int = DEFAULT_ACTION_MIN_EPISODES,
        action_min_success_rate: float = DEFAULT_ACTION_MIN_SUCCESS_RATE,
    ) -> None:
        self.skill_manager = skill_manager
        self.traces_path = Path(traces_path)
        self.goal_min_episodes = goal_min_episodes
        self.goal_min_success_rate = goal_min_success_rate
        self.action_min_episodes = action_min_episodes
        self.action_min_success_rate = action_min_success_rate

    def find_candidates(
        self, traces: Optional[List[TraceRecord]] = None
    ) -> List[SkillCandidate]:
        """Surface SkillCandidates from traces. No side effects."""
        if traces is None:
            traces = load_traces(self.traces_path)

        candidates: List[SkillCandidate] = []
        for p in compute_goal_patterns(traces, min_episodes=self.goal_min_episodes):
            if p.success_rate < self.goal_min_success_rate:
                continue
            candidates.append(goal_pattern_to_candidate(p))

        for ap in compute_action_patterns(traces, min_episodes=self.action_min_episodes):
            if ap.success_rate < self.action_min_success_rate:
                continue
            candidates.append(action_pattern_to_candidate(ap))

        return candidates

    def extract(
        self, traces: Optional[List[TraceRecord]] = None,
        skip_if_name_exists: bool = True,
    ) -> List[Skill]:
        """Find candidates and materialize them as DRAFT skills.

        Returns list of Skills created. Skips candidates whose name_hint
        is already present in the store (basic dedup - Phase 2b can do
        semantic dedup).

        Never auto-promotes - all skills land in DRAFT.
        """
        created: List[Skill] = []
        existing_names = {s.frontmatter.name for s in self.skill_manager.store.list_all()}

        for c in self.find_candidates(traces=traces):
            if skip_if_name_exists and c.name_hint in existing_names:
                logger.debug("Skipping existing skill name: %s", c.name_hint)
                continue
            try:
                skill = self.skill_manager.create_draft(
                    name=c.name_hint,
                    description=c.description,
                    sections=candidate_to_sections(c),
                    created_by="skill_extractor",
                    source_episode_ids=c.source_episode_ids,
                    trigger_count=c.trigger_count,
                    tags=c.tags,
                )
                created.append(skill)
                existing_names.add(c.name_hint)
            except SkillValidationError as e:
                logger.warning(
                    "Candidate %s failed validation: %s", c.name_hint, e
                )
            except ValueError as e:
                logger.warning(
                    "Candidate %s rejected: %s", c.name_hint, e
                )

        return created
