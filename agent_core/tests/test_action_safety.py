"""
Tests for K10 Action Safety Layer.

Tests cover:
- Safety model (enums, dataclasses, serialization)
- Safety classifier (profiles per action type, safe-by-default)
- AuditLog (JSONL persistence, queries, bounded cache, stats)
- EffectValidator (state capture, validation rules, thresholds)
- ActionSafety facade (before/after workflow, is_staged, status)
- PlannerCore integration (set_action_safety, backward compatible)
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.action_safety.safety_model import (
    ActionRecord,
    EffectType,
    Reversibility,
    SafetyMode,
    SafetyProfile,
    StateSnapshot,
    ValidationResult,
    create_action_record,
)
from agent_core.action_safety.safety_classifier import (
    DEFAULT_SAFETY_PROFILES,
    get_safety_profile,
)
from agent_core.action_safety.audit_log import AuditLog, MAX_RECENT
from agent_core.action_safety.effect_validator import (
    EffectValidator,
    HEALTH_DROP_THRESHOLD,
    MAX_GOAL_INCREASE,
)
from agent_core.action_safety import ActionSafety


# ===================== Safety Model =====================


class TestEnums:
    def test_safety_mode_values(self):
        assert len(SafetyMode) == 3
        assert SafetyMode.AUTO_COMMIT.value == "auto_commit"
        assert SafetyMode.STAGED.value == "staged"

    def test_reversibility_values(self):
        assert len(Reversibility) == 3
        assert Reversibility.PARTIALLY_REVERSIBLE.value == "partial"

    def test_effect_type_values(self):
        assert len(EffectType) == 7
        assert EffectType.DEVICE.value == "device"
        assert EffectType.CONFIGURATION.value == "configuration"

    def test_validation_result_values(self):
        assert len(ValidationResult) == 3
        assert ValidationResult.UNEXPECTED.value == "unexpected"


class TestStateSnapshot:
    def test_create_default(self):
        s = StateSnapshot()
        assert s.timestamp == 0.0
        assert s.health_score == 1.0
        assert s.mode == "active"

    def test_serialization(self):
        s = StateSnapshot(
            timestamp=100.0,
            knowledge_file_count=42,
            input_file_count=10,
            goal_active_count=3,
            health_score=0.9,
            mode="sleep",
            custom={"key": "val"},
        )
        d = s.to_dict()
        restored = StateSnapshot.from_dict(d)
        assert restored.knowledge_file_count == 42
        assert restored.input_file_count == 10
        assert restored.mode == "sleep"
        assert restored.custom == {"key": "val"}


class TestSafetyProfile:
    def test_frozen(self):
        p = SafetyProfile(
            SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
            EffectType.NONE, False, False,
        )
        with pytest.raises(AttributeError):
            p.safety_mode = SafetyMode.STAGED


class TestActionRecord:
    def test_create_action_record(self):
        profile = SafetyProfile(
            SafetyMode.AUDIT_ONLY, Reversibility.PARTIALLY_REVERSIBLE,
            EffectType.FILESYSTEM, True, True,
        )
        r = create_action_record(
            plan_id="plan-1",
            action_type="fetch",
            profile=profile,
            action_params={"max_articles": 3},
            goal_id="goal-1",
        )
        assert r.record_id.startswith("arec-")
        assert r.plan_id == "plan-1"
        assert r.safety_mode == "audit_only"
        assert r.reversibility == "partial"
        assert r.effect_type == "filesystem"
        assert r.timestamp > 0

    def test_serialization(self):
        profile = SafetyProfile(
            SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
            EffectType.KNOWLEDGE, False, False,
        )
        before = StateSnapshot(timestamp=100.0, input_file_count=5)
        r = create_action_record(
            plan_id="plan-2",
            action_type="learn",
            profile=profile,
            before_state=before,
            metadata={"source": "test"},
        )
        r.success = True
        r.validation = "valid"
        r.after_state = {"timestamp": 101.0, "input_file_count": 5}

        d = r.to_dict()
        restored = ActionRecord.from_dict(d)
        assert restored.plan_id == "plan-2"
        assert restored.success is True
        assert restored.before_state is not None
        assert restored.after_state is not None
        assert restored.metadata == {"source": "test"}

    def test_record_defaults(self):
        profile = SafetyProfile(
            SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
            EffectType.NONE, False, False,
        )
        r = create_action_record("p1", "noop", profile)
        assert r.success is None
        assert r.validation == "skipped"
        assert r.rollback_available is False
        assert r.before_state is None


# ===================== Safety Classifier =====================


class TestSafetyClassifier:
    def test_learn_profile(self):
        p = get_safety_profile("learn")
        assert p.safety_mode == SafetyMode.AUTO_COMMIT
        assert p.reversibility == Reversibility.REVERSIBLE
        assert p.effect_type == EffectType.KNOWLEDGE
        assert p.needs_before_snapshot is False

    def test_exam_profile(self):
        p = get_safety_profile("exam")
        assert p.safety_mode == SafetyMode.AUTO_COMMIT

    def test_fetch_profile(self):
        p = get_safety_profile("fetch")
        assert p.safety_mode == SafetyMode.AUDIT_ONLY
        assert p.reversibility == Reversibility.PARTIALLY_REVERSIBLE
        assert p.effect_type == EffectType.FILESYSTEM
        assert p.needs_before_snapshot is True
        assert p.needs_after_snapshot is True

    def test_maintenance_profile(self):
        p = get_safety_profile("maintenance")
        assert p.safety_mode == SafetyMode.AUDIT_ONLY
        assert p.effect_type == EffectType.GOAL_STATE

    def test_noop_profile(self):
        p = get_safety_profile("noop")
        assert p.safety_mode == SafetyMode.AUTO_COMMIT
        assert p.effect_type == EffectType.NONE

    def test_evaluate_profile(self):
        p = get_safety_profile("evaluate")
        assert p.safety_mode == SafetyMode.AUTO_COMMIT

    def test_unknown_action_defaults_to_staged(self):
        p = get_safety_profile("smart_home_toggle")
        assert p.safety_mode == SafetyMode.STAGED
        assert p.reversibility == Reversibility.IRREVERSIBLE
        assert p.needs_before_snapshot is True

    def test_all_known_actions_covered(self):
        known = ["learn", "exam", "review", "evaluate", "noop", "maintenance", "fetch"]
        for action in known:
            p = get_safety_profile(action)
            assert p.safety_mode != SafetyMode.STAGED, f"{action} should not be STAGED"


# ===================== AuditLog =====================


class TestAuditLog:
    def _make_record(self, plan_id="p1", action_type="learn", success=True):
        profile = SafetyProfile(
            SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
            EffectType.KNOWLEDGE, False, False,
        )
        r = create_action_record(plan_id, action_type, profile)
        r.success = success
        return r

    def test_record_and_count(self, tmp_path):
        log = AuditLog(path=tmp_path / "audit.jsonl")
        log.record(self._make_record())
        assert log.count() == 1

    def test_get_recent(self, tmp_path):
        log = AuditLog(path=tmp_path / "audit.jsonl")
        for i in range(5):
            log.record(self._make_record(plan_id=f"p{i}"))
        recent = log.get_recent(limit=3)
        assert len(recent) == 3
        assert recent[0]["plan_id"] == "p4"  # newest first

    def test_get_by_action_type(self, tmp_path):
        log = AuditLog(path=tmp_path / "audit.jsonl")
        log.record(self._make_record(action_type="learn"))
        log.record(self._make_record(action_type="fetch"))
        log.record(self._make_record(action_type="learn"))
        result = log.get_by_action_type("learn")
        assert len(result) == 2

    def test_get_by_plan_id(self, tmp_path):
        log = AuditLog(path=tmp_path / "audit.jsonl")
        log.record(self._make_record(plan_id="plan-xyz"))
        found = log.get_by_plan_id("plan-xyz")
        assert found is not None
        assert found["plan_id"] == "plan-xyz"

    def test_get_by_plan_id_not_found(self, tmp_path):
        log = AuditLog(path=tmp_path / "audit.jsonl")
        assert log.get_by_plan_id("nope") is None

    def test_persistence_across_instances(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        log1 = AuditLog(path=path)
        log1.record(self._make_record(plan_id="p1"))
        log1.record(self._make_record(plan_id="p2"))

        log2 = AuditLog(path=path)
        assert log2.count() == 2

    def test_bounded_max_recent(self, tmp_path):
        log = AuditLog(path=tmp_path / "audit.jsonl")
        for i in range(MAX_RECENT + 10):
            log.record(self._make_record(plan_id=f"p{i}"))
        assert log.count() == MAX_RECENT

    def test_stats(self, tmp_path):
        log = AuditLog(path=tmp_path / "audit.jsonl")
        log.record(self._make_record(action_type="learn", success=True))
        log.record(self._make_record(action_type="fetch", success=False))
        log.record(self._make_record(action_type="learn", success=True))
        stats = log.get_stats()
        assert stats["total"] == 3
        assert stats["by_action_type"]["learn"] == 2
        assert stats["by_action_type"]["fetch"] == 1
        assert stats["success"] == 2
        assert stats["failed"] == 1

    def test_corrupt_record_skipped(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        with open(path, "w") as f:
            f.write("not json\n")
            r = self._make_record()
            f.write(json.dumps(r.to_dict()) + "\n")
        log = AuditLog(path=path)
        assert log.count() == 1


# ===================== EffectValidator =====================


class TestEffectValidator:
    def test_capture_state_no_deps(self):
        v = EffectValidator()
        s = v.capture_state()
        assert s.timestamp > 0
        assert s.health_score == 1.0

    def test_capture_state_with_homeostasis(self):
        v = EffectValidator()
        core = MagicMock()
        state = MagicMock()
        state.health_score = 0.8
        state.mode.value = "reduced"
        core.get_state.return_value = state
        v.set_homeostasis_core(core)
        s = v.capture_state()
        assert s.health_score == 0.8
        assert s.mode == "reduced"

    def test_capture_state_with_goal_store(self):
        v = EffectValidator()
        store = MagicMock()
        store.get_active.return_value = [1, 2, 3]
        v.set_goal_store(store)
        s = v.capture_state()
        assert s.goal_active_count == 3

    def test_validate_noop_skipped(self):
        v = EffectValidator()
        before = StateSnapshot(timestamp=100.0)
        after = StateSnapshot(timestamp=101.0)
        result, details = v.validate_effects("noop", before, after, {})
        assert result == ValidationResult.SKIPPED

    def test_validate_learn_skipped(self):
        v = EffectValidator()
        before = StateSnapshot()
        after = StateSnapshot()
        result, _ = v.validate_effects("learn", before, after, {})
        assert result == ValidationResult.SKIPPED

    def test_validate_fetch_valid(self):
        v = EffectValidator()
        before = StateSnapshot(input_file_count=10, health_score=0.9)
        after = StateSnapshot(input_file_count=13, health_score=0.9)
        result, details = v.validate_effects("fetch", before, after, {})
        assert result == ValidationResult.VALID
        assert details["input_files_delta"] == 3

    def test_validate_fetch_files_decreased(self):
        v = EffectValidator()
        before = StateSnapshot(input_file_count=10, health_score=0.9)
        after = StateSnapshot(input_file_count=8, health_score=0.9)
        result, details = v.validate_effects("fetch", before, after, {})
        assert result == ValidationResult.UNEXPECTED
        assert details.get("input_files_decreased") is True

    def test_validate_maintenance_valid(self):
        v = EffectValidator()
        before = StateSnapshot(goal_active_count=5, health_score=0.9)
        after = StateSnapshot(goal_active_count=6, health_score=0.9)
        result, details = v.validate_effects("maintenance", before, after, {})
        assert result == ValidationResult.VALID

    def test_validate_maintenance_goal_explosion(self):
        v = EffectValidator()
        before = StateSnapshot(goal_active_count=3, health_score=0.9)
        after = StateSnapshot(goal_active_count=3 + MAX_GOAL_INCREASE + 1, health_score=0.9)
        result, details = v.validate_effects("maintenance", before, after, {})
        assert result == ValidationResult.UNEXPECTED
        assert details.get("goal_count_explosion") is True

    def test_validate_health_drop(self):
        v = EffectValidator()
        before = StateSnapshot(health_score=0.9, input_file_count=5)
        after = StateSnapshot(health_score=0.5, input_file_count=5)
        result, details = v.validate_effects("fetch", before, after, {})
        assert result == ValidationResult.UNEXPECTED
        assert details.get("health_drop_unexpected") is True

    def test_validate_health_normal_drop(self):
        v = EffectValidator()
        before = StateSnapshot(health_score=0.9, input_file_count=5)
        after = StateSnapshot(health_score=0.8, input_file_count=5)
        result, _ = v.validate_effects("fetch", before, after, {})
        assert result == ValidationResult.VALID


# ===================== ActionSafety Facade =====================


class TestActionSafetyFacade:
    def test_before_action_auto_commit(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        mode = safety.before_action("plan-1", "learn", {})
        assert mode == SafetyMode.AUTO_COMMIT

    def test_before_action_audit_only(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        mode = safety.before_action("plan-1", "fetch", {"max_articles": 3})
        assert mode == SafetyMode.AUDIT_ONLY

    def test_before_action_staged_unknown(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        mode = safety.before_action("plan-1", "smart_home_toggle", {})
        assert mode == SafetyMode.STAGED

    def test_after_action_no_pending(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        result = safety.after_action("no-such-plan", True, {})
        assert result["validation"] == "skipped"

    def test_full_workflow_auto_commit(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        mode = safety.before_action("plan-1", "learn", {})
        assert mode == SafetyMode.AUTO_COMMIT
        result = safety.after_action("plan-1", True, {})
        assert result["validation"] == "skipped"
        assert safety.get_status()["total_records"] == 1

    def test_full_workflow_audit_only(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        safety.before_action("plan-1", "fetch", {})
        result = safety.after_action("plan-1", True, {"articles_fetched": 2})
        # Without deps wired, validation is still computed (no health drop)
        assert result["validation"] in ("valid", "skipped")

    def test_is_staged_known(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        assert safety.is_staged("learn") is False
        assert safety.is_staged("fetch") is False

    def test_is_staged_unknown(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        assert safety.is_staged("smart_home_toggle") is True

    def test_get_status_structure(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        status = safety.get_status()
        assert "total_records" in status
        assert "pending_actions" in status
        assert "by_action_type" in status
        assert "by_safety_mode" in status
        assert "by_validation" in status

    def test_get_recent_records(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        safety.before_action("p1", "learn", {})
        safety.after_action("p1", True, {})
        safety.before_action("p2", "exam", {})
        safety.after_action("p2", True, {})
        records = safety.get_recent_records(limit=5)
        assert len(records) == 2

    def test_get_audit_stats(self, tmp_path):
        safety = ActionSafety(log_path=tmp_path / "audit.jsonl")
        for i in range(3):
            safety.before_action(f"p{i}", "learn", {})
            safety.after_action(f"p{i}", True, {})
        stats = safety.get_audit_stats()
        assert stats["total"] == 3
        assert stats["success"] == 3


# ===================== PlannerCore Integration =====================


class TestPlannerCoreIntegration:
    def test_set_action_safety(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()
        safety = ActionSafety()
        planner.set_action_safety(safety)
        assert planner._action_safety is safety

    def test_action_safety_none_by_default(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()
        assert planner._action_safety is None


# ===================== SharedContext =====================


class TestSharedContextK10:
    def test_action_safety_field_exists(self):
        from agent_core.registry.shared_context import SharedContext
        ctx = SharedContext()
        assert hasattr(ctx, "action_safety")
        assert ctx.action_safety is None
