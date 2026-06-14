"""Tests for skill_extractor: candidate generation + DRAFT skill creation."""

import json
from pathlib import Path
from typing import List

import pytest

from agent_core.skills.skill_model import SkillStatus
from agent_core.skills.skill_store import SkillStore
from agent_core.skills.skill_manager import SkillManager
from agent_core.teacher.skill_extractor import (
    DEFAULT_GOAL_MIN_EPISODES,
    SkillCandidate,
    SkillExtractor,
    _slugify,
    action_pattern_to_candidate,
    candidate_to_sections,
    goal_pattern_to_candidate,
)
from agent_core.teacher.trace_analyzer import (
    ActionPattern,
    GoalPattern,
    load_traces,
)


# =========================================================================
# Synthetic traces (reused from test_trace_analyzer pattern)
# =========================================================================


def _make_synthetic_traces_file(path: Path) -> Path:
    """Write a synthetic traces file with one clear skill candidate."""
    rows = []
    # goal-skill: 8 episodes of creative+noop, all success (high quality skill candidate)
    for i in range(8):
        rows.append({
            "episode_id": f"ep-skill-{i}",
            "action_type": "creative" if i % 2 == 0 else "noop",
            "goal_id": "goal-skill",
            "goal_description": "Przerwij stagnacje przez kreatywna refleksje",
            "success": True,
            "started_at": float(100 + i * 100),
            "mode": "active",
        })
    # goal-fail: 6 episodes, 2 success = 33% (below threshold)
    for i in range(6):
        rows.append({
            "episode_id": f"ep-fail-{i}",
            "action_type": "exam",
            "goal_id": "goal-fail",
            "goal_description": "Nauka chaotyczna",
            "success": i < 2,
            "started_at": float(1000 + i * 100),
            "mode": "active",
        })
    # 60 reliable 'review' actions across goals (action_pattern candidate)
    for i in range(60):
        rows.append({
            "episode_id": f"ep-rev-{i}",
            "action_type": "review",
            "goal_id": f"goal-rev-{i % 5}",
            "goal_description": "Cross-goal review",
            "success": True,
            "started_at": float(2000 + i * 10),
            "mode": "active",
        })
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def extractor_setup(tmp_path):
    """Wire SkillStore + SkillManager + SkillExtractor on a synthetic traces file."""
    traces_path = tmp_path / "decision_traces.jsonl"
    _make_synthetic_traces_file(traces_path)
    store = SkillStore(root=tmp_path / "skills")
    store.load()
    audit_log = []
    mgr = SkillManager(
        store=store,
        audit_callback=lambda e, p: audit_log.append((e, p)),
    )
    extractor = SkillExtractor(skill_manager=mgr, traces_path=traces_path)
    return extractor, mgr, audit_log


# =========================================================================
# 1. Slugify
# =========================================================================


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_polish_diacritics(self):
        assert _slugify("Stymulacja postępu") == "stymulacja-postepu"
        assert _slugify("łukasz źrebak") == "lukasz-zrebak"

    def test_punctuation_dropped(self):
        assert _slugify("a.b!c?d:e") == "a-b-c-d-e"

    def test_max_len_cap(self):
        s = _slugify("a" * 200, max_len=20)
        assert len(s) <= 20

    def test_empty_returns_unnamed(self):
        assert _slugify("") == "unnamed"
        assert _slugify("!!!") == "unnamed"


# =========================================================================
# 2. goal_pattern_to_candidate
# =========================================================================


class TestGoalPatternCandidate:
    def test_produces_complete_sections(self):
        p = GoalPattern(
            goal_id="goal-test",
            goal_description="Test goal",
            episode_count=10,
            success_count=10,
            action_histogram={"creative": 5, "noop": 5},
            sample_episode_ids=["ep-1", "ep-2", "ep-3"],
        )
        c = goal_pattern_to_candidate(p)
        assert c.kind == "goal_pattern"
        assert c.when_to_use
        assert c.procedure
        assert c.pitfalls
        assert c.verification
        assert "100%" in c.when_to_use
        assert "creative" in c.procedure

    def test_description_within_limit(self):
        p = GoalPattern(
            goal_id="g", goal_description="x" * 200,
            episode_count=5, success_count=5,
            action_histogram={"a": 5}, sample_episode_ids=["ep1"],
        )
        c = goal_pattern_to_candidate(p)
        assert len(c.description) <= 140

    def test_tags_include_dominant_actions(self):
        p = GoalPattern(
            goal_id="g", goal_description="d",
            episode_count=10, success_count=10,
            action_histogram={"creative": 6, "noop": 4},
            sample_episode_ids=["ep1"],
        )
        c = goal_pattern_to_candidate(p)
        assert "creative" in c.tags


# =========================================================================
# 3. action_pattern_to_candidate
# =========================================================================


class TestActionPatternCandidate:
    def test_produces_action_pattern_kind(self):
        p = ActionPattern(
            action_type="creative",
            episode_count=100, success_count=100,
            sample_episode_ids=["ep1", "ep2"],
        )
        c = action_pattern_to_candidate(p)
        assert c.kind == "action_pattern"
        assert "creative" in c.tags
        assert "action_pattern" in c.tags


# =========================================================================
# 4. candidate_to_sections
# =========================================================================


class TestCandidateToSections:
    def test_all_required_sections_present(self):
        c = SkillCandidate(
            kind="goal_pattern",
            name_hint="x",
            description="d",
            when_to_use="when",
            procedure="proc",
            pitfalls="pit",
            verification="verif",
        )
        sections = candidate_to_sections(c)
        assert sections["When to Use"] == "when"
        assert sections["Procedure"] == "proc"
        assert sections["Pitfalls"] == "pit"
        assert sections["Verification"] == "verif"


# =========================================================================
# 5. SkillExtractor.find_candidates
# =========================================================================


class TestFindCandidates:
    def test_high_quality_pattern_surfaced(self, extractor_setup):
        extractor, _, _ = extractor_setup
        candidates = extractor.find_candidates()
        # goal-skill (8 ep, 100% success) -> candidate
        assert any(c.kind == "goal_pattern" and "stymulacja" in c.name_hint.lower()
                   or "stagnacje" in c.name_hint.lower()
                   or "przerwij" in c.name_hint.lower()
                   for c in candidates)

    def test_low_success_filtered_out(self, extractor_setup):
        extractor, _, _ = extractor_setup
        candidates = extractor.find_candidates()
        # goal-fail (33% success) - should NOT make it
        assert not any("chaotyczna" in c.name_hint or "fail" in c.name_hint
                       for c in candidates)

    def test_action_pattern_surfaced(self, extractor_setup):
        extractor, _, _ = extractor_setup
        candidates = extractor.find_candidates()
        # 60 reliable 'review' actions -> ActionPattern candidate
        assert any(c.kind == "action_pattern" and "review" in c.name_hint
                   for c in candidates)

    def test_min_episodes_threshold_respected(self, tmp_path):
        # Only 4 episodes - below default min_episodes=5
        traces_path = tmp_path / "few.jsonl"
        rows = [
            {"episode_id": f"ep-{i}", "action_type": "creative", "goal_id": "g",
             "goal_description": "d", "success": True, "started_at": float(i),
             "mode": "active"}
            for i in range(4)
        ]
        traces_path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        store = SkillStore(root=tmp_path / "sk")
        store.load()
        mgr = SkillManager(store=store)
        extractor = SkillExtractor(skill_manager=mgr, traces_path=traces_path)
        assert extractor.find_candidates() == []


# =========================================================================
# 6. SkillExtractor.extract - creates DRAFT skills
# =========================================================================


class TestExtractCreatesDrafts:
    def test_creates_at_least_one_draft(self, extractor_setup):
        extractor, mgr, audit_log = extractor_setup
        created = extractor.extract()
        assert len(created) >= 1
        for skill in created:
            assert skill.frontmatter.status == SkillStatus.DRAFT
            assert skill.frontmatter.created_by == "skill_extractor"

    def test_drafts_have_source_episodes(self, extractor_setup):
        extractor, _, _ = extractor_setup
        created = extractor.extract()
        for skill in created:
            assert skill.frontmatter.source_episode_ids  # non-empty

    def test_audit_emitted(self, extractor_setup):
        extractor, _, audit_log = extractor_setup
        extractor.extract()
        events = [e for e, _ in audit_log]
        assert "skill_created" in events

    def test_idempotent_no_duplicates(self, extractor_setup):
        extractor, mgr, _ = extractor_setup
        first = extractor.extract()
        # Second run with same traces: skip existing names
        second = extractor.extract()
        assert len(second) == 0
        # Store size unchanged
        assert mgr.store.count() == len(first)


# =========================================================================
# 7. Integration with real schema validation
# =========================================================================


class TestSchemaCompatibility:
    def test_drafts_pass_validation(self, extractor_setup):
        """SkillManager.create_draft raises if validation fails - so the fact
        that extract() returned anything means schema was respected."""
        extractor, mgr, _ = extractor_setup
        created = extractor.extract()
        for skill in created:
            # Re-validate by reloading from disk
            reloaded_store = SkillStore(root=mgr.store.root)
            reloaded_store.load()
            assert reloaded_store.exists(skill.skill_id)
