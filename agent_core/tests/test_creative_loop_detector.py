"""Tests for D3 LoopDetector + CreativeModule integration (2026-04-26).

Covers:
- Detection of abandoned-pattern loops by meta_goal_type fingerprint.
- Window + threshold semantics (self-decaying suppression).
- ``filter_candidates`` split.
- ``CreativeModule._handle_suppressed_loop`` persists, logs, and posts a
  single bulletin entry per suppressed type per cycle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from agent_core.creative.loop_detector import (
    LoopDetector,
    LoopReport,
    DEFAULT_ABANDON_THRESHOLD,
)
from agent_core.creative.creative_model import (
    MetaGoal,
    MetaGoalType,
    MetaGoalStatus,
    RiskLevel,
)
from agent_core.creative.facade import CreativeModule


# =============================================================================
# Fixtures: minimal goal-store stub
# =============================================================================


@dataclass
class _GoalStub:
    id: str
    type: Any
    description: str
    priority: float
    status: Any
    progress: float
    parent_goal_id: Optional[str]
    created_by: str
    created_at: float
    updated_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _StatusStub:
    value: str


@dataclass
class _TypeStub:
    value: str


def _abandoned_goal(
    meta_goal_type: str,
    age_seconds: float,
    created_by: str = "creative",
    has_metadata: bool = True,
) -> _GoalStub:
    now = time.time()
    metadata = {"meta_goal_type": meta_goal_type} if has_metadata else {}
    return _GoalStub(
        id=f"g-{meta_goal_type}-{int(age_seconds)}",
        type=_TypeStub("meta"),
        description=f"abandoned {meta_goal_type}",
        priority=0.7,
        status=_StatusStub("abandoned"),
        progress=0.0,
        parent_goal_id=None,
        created_by=created_by,
        created_at=now - age_seconds,
        updated_at=now - age_seconds,
        metadata=metadata,
    )


class _GoalStoreStub:
    def __init__(self, goals: List[_GoalStub]):
        self._goals = goals

    def get_all(self) -> List[_GoalStub]:
        return list(self._goals)


# =============================================================================
# LoopDetector core
# =============================================================================


class TestLoopDetectorDetect:

    def test_no_goal_store_returns_empty(self):
        det = LoopDetector(goal_store=None)
        report = det.detect()
        assert report.suppressed_types == set()
        assert report.counts == {}

    def test_below_threshold_no_suppression(self):
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", 3600),
            _abandoned_goal("capability_meta", 7200),
        ])
        det = LoopDetector(goal_store=store, abandon_threshold=3)
        report = det.detect()
        assert report.suppressed_types == set()
        assert report.counts == {"capability_meta": 2}

    def test_at_threshold_triggers_suppression(self):
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", 3600),
            _abandoned_goal("capability_meta", 7200),
            _abandoned_goal("capability_meta", 14400),
        ])
        det = LoopDetector(goal_store=store, abandon_threshold=3)
        report = det.detect()
        assert "capability_meta" in report.suppressed_types
        assert report.counts["capability_meta"] == 3

    def test_outside_window_excluded(self):
        nine_days = 9 * 86400
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", nine_days),
            _abandoned_goal("capability_meta", nine_days + 100),
            _abandoned_goal("capability_meta", nine_days + 200),
        ])
        det = LoopDetector(goal_store=store, window_days=7, abandon_threshold=3)
        report = det.detect()
        # All three are older than 7 days -> not counted at all
        assert report.counts == {}
        assert report.suppressed_types == set()

    def test_non_creative_goals_excluded(self):
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", 3600, created_by="critic"),
            _abandoned_goal("capability_meta", 7200, created_by="self_analysis"),
            _abandoned_goal("capability_meta", 14400, created_by="user_conversation"),
        ])
        det = LoopDetector(goal_store=store, abandon_threshold=3)
        report = det.detect()
        assert report.counts == {}

    def test_missing_meta_goal_type_skipped(self):
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", 3600, has_metadata=False),
            _abandoned_goal("capability_meta", 7200, has_metadata=False),
            _abandoned_goal("capability_meta", 14400, has_metadata=False),
        ])
        det = LoopDetector(goal_store=store, abandon_threshold=3)
        report = det.detect()
        assert report.counts == {}

    def test_multiple_types_independently_tracked(self):
        store = _GoalStoreStub([
            *[_abandoned_goal("capability_meta", i * 3600) for i in range(1, 5)],
            *[_abandoned_goal("architectural_meta", i * 3600) for i in range(1, 3)],
            _abandoned_goal("exploration_meta", 3600),
        ])
        det = LoopDetector(goal_store=store, abandon_threshold=3)
        report = det.detect()
        assert "capability_meta" in report.suppressed_types
        assert "architectural_meta" not in report.suppressed_types
        assert "exploration_meta" not in report.suppressed_types
        assert report.counts["capability_meta"] == 4
        assert report.counts["architectural_meta"] == 2
        assert report.counts["exploration_meta"] == 1

    def test_only_abandoned_status_counts(self):
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", 3600),
            _GoalStub(
                id="g-active", type=_TypeStub("meta"), description="x",
                priority=0.5, status=_StatusStub("active"), progress=0.0,
                parent_goal_id=None, created_by="creative",
                created_at=time.time() - 3600, updated_at=time.time() - 3600,
                metadata={"meta_goal_type": "capability_meta"},
            ),
            _GoalStub(
                id="g-pending", type=_TypeStub("meta"), description="x",
                priority=0.5, status=_StatusStub("pending"), progress=0.0,
                parent_goal_id=None, created_by="creative",
                created_at=time.time() - 3600, updated_at=time.time() - 3600,
                metadata={"meta_goal_type": "capability_meta"},
            ),
        ])
        det = LoopDetector(goal_store=store, abandon_threshold=3)
        report = det.detect()
        assert report.counts == {"capability_meta": 1}

    def test_self_decays_when_streak_ages_out(self):
        # Three abandons inside the window — suppressed.
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", 3600),
            _abandoned_goal("capability_meta", 7200),
            _abandoned_goal("capability_meta", 14400),
        ])
        det = LoopDetector(goal_store=store, window_days=7, abandon_threshold=3)
        assert "capability_meta" in det.detect().suppressed_types

        # Same goals 14 days later (outside the 7d window) — suppression lifts.
        future = time.time() + 14 * 86400
        report = det.detect(now=future)
        assert report.suppressed_types == set()


# =============================================================================
# LoopDetector.filter_candidates
# =============================================================================


class _CandidateStub:
    def __init__(self, gtype: str):
        self.goal_type = _TypeStub(gtype)
        self.goal_id = f"mg-{gtype}-{id(self) & 0xffff:x}"
        self.title = f"title {gtype}"


class TestLoopDetectorFilterCandidates:

    def test_no_suppression_keeps_all(self):
        det = LoopDetector(goal_store=_GoalStoreStub([]))
        cands = [_CandidateStub("capability_meta"), _CandidateStub("exploration_meta")]
        kept, suppressed = det.filter_candidates(cands)
        assert len(kept) == 2
        assert suppressed == []

    def test_suppression_splits_correctly(self):
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", i * 3600) for i in range(1, 5)
        ])
        det = LoopDetector(goal_store=store, abandon_threshold=3)
        cands = [
            _CandidateStub("capability_meta"),
            _CandidateStub("exploration_meta"),
            _CandidateStub("capability_meta"),
        ]
        kept, suppressed = det.filter_candidates(cands)
        assert len(kept) == 1
        assert kept[0].goal_type.value == "exploration_meta"
        assert len(suppressed) == 2
        assert all(c.goal_type.value == "capability_meta" for c in suppressed)


# =============================================================================
# CreativeModule integration
# =============================================================================


def _make_meta_goal(goal_type: MetaGoalType, title: str = "x") -> MetaGoal:
    return MetaGoal.create(
        title=title,
        goal_type=goal_type,
        priority=0.7,
        why_now="streak detected",
        evidence_refs=["streak:test"],
        expected_value="value",
        risk_level=RiskLevel.LOW,
    )


class TestCreativeModuleLoopHandling:

    def _make_module(self, tmp_path) -> CreativeModule:
        return CreativeModule(
            data_dir=str(tmp_path / "meta_data"),
            memory_dir=str(tmp_path / "memory"),
        )

    def test_handle_suppressed_loop_persists_and_logs(self, tmp_path):
        from agent_core.creative.creative_store import CreativeStore
        from agent_core.creative import creative_events as events

        module = self._make_module(tmp_path)
        candidates = [
            _make_meta_goal(MetaGoalType.CAPABILITY_META, "title A"),
            _make_meta_goal(MetaGoalType.CAPABILITY_META, "title B"),
        ]

        # Pre-state — no rejected meta-goals or suppress events yet.
        assert module._total_meta_goals_suppressed == 0

        module._handle_suppressed_loop(candidates)

        assert module._total_meta_goals_suppressed == 2

        # Both candidates persisted as REJECTED on the creative store.
        store_path = tmp_path / "meta_data" / "creative_meta_goals.jsonl"
        assert store_path.exists()
        text = store_path.read_text(encoding="utf-8")
        assert candidates[0].goal_id in text
        assert candidates[1].goal_id in text
        assert "rejected" in text.lower()

        # Creative events log carries one suppress event per candidate.
        events_path = tmp_path / "meta_data" / "creative_events.jsonl"
        assert events_path.exists()
        events_text = events_path.read_text(encoding="utf-8")
        assert events_text.count(events.GOAL_SUPPRESSED_LOOP) == 2

    def test_handle_suppressed_loop_posts_one_bulletin_per_type(self, tmp_path):
        module = self._make_module(tmp_path)

        # Wire a bulletin store + matching goal store so the report has counts.
        from agent_core.bulletin import BulletinStore
        bulletin = BulletinStore(
            path=tmp_path / "cognitive_bulletin.jsonl"
        )
        module.set_bulletin_store(bulletin)

        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", i * 3600) for i in range(1, 5)
        ])
        module._loop_detector.set_goal_store(store)

        candidates = [
            _make_meta_goal(MetaGoalType.CAPABILITY_META, "A"),
            _make_meta_goal(MetaGoalType.CAPABILITY_META, "B"),
            _make_meta_goal(MetaGoalType.CAPABILITY_META, "C"),
        ]
        module._handle_suppressed_loop(candidates)

        from agent_core.bulletin.bulletin_model import EntryType
        entries = bulletin.get_by_type(EntryType.IMPROVEMENT)
        # One bulletin entry for the type, even though three candidates were
        # suppressed.
        assert len(entries) == 1
        e = entries[0]
        assert e.requested_by == "creative"
        assert e.metadata["meta_goal_type"] == "capability_meta"
        assert e.metadata["abandon_count"] == 4
        assert "capability_meta" in e.topic

    def test_handle_suppressed_loop_skips_bulletin_when_unwired(self, tmp_path):
        module = self._make_module(tmp_path)
        # No bulletin store wired.
        candidates = [_make_meta_goal(MetaGoalType.CAPABILITY_META)]
        # Should not raise.
        module._handle_suppressed_loop(candidates)
        assert module._total_meta_goals_suppressed == 1

    def test_handle_suppressed_loop_distinct_types_get_distinct_entries(
        self, tmp_path,
    ):
        module = self._make_module(tmp_path)
        from agent_core.bulletin import BulletinStore
        bulletin = BulletinStore(
            path=tmp_path / "cognitive_bulletin.jsonl"
        )
        module.set_bulletin_store(bulletin)

        store = _GoalStoreStub([
            *[_abandoned_goal("capability_meta", i * 3600) for i in range(1, 5)],
            *[_abandoned_goal("architectural_meta", i * 3600) for i in range(1, 5)],
        ])
        module._loop_detector.set_goal_store(store)

        candidates = [
            _make_meta_goal(MetaGoalType.CAPABILITY_META),
            _make_meta_goal(MetaGoalType.ARCHITECTURAL_META),
        ]
        module._handle_suppressed_loop(candidates)

        from agent_core.bulletin.bulletin_model import EntryType
        entries = bulletin.get_by_type(EntryType.IMPROVEMENT)
        assert len(entries) == 2
        types = {e.metadata["meta_goal_type"] for e in entries}
        assert types == {"capability_meta", "architectural_meta"}

    def test_set_goal_store_propagates_to_loop_detector(self, tmp_path):
        module = self._make_module(tmp_path)
        store = _GoalStoreStub([
            _abandoned_goal("capability_meta", 3600) for _ in range(4)
        ])
        module.set_goal_store(store)
        # Detector now sees the store passed via facade.
        report = module._loop_detector.detect()
        assert "capability_meta" in report.suppressed_types
