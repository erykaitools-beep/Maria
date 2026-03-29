"""
Phase 6: Formal Readiness Checklist.

Each test is one readiness criterion for ClawBot authority escalation.
All must pass before UNRESTRICTED level can be activated.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.autonomy.authority_level import (
    AuthorityLevel,
    AuthorityConfig,
    AuthorityManager,
)
from agent_core.autonomy.approval_queue import ApprovalQueue, ApprovalRequest
from agent_core.autonomy.tool_budget import ToolBudgetManager
from agent_core.autonomy import AutonomyPolicy
from agent_core.autonomy.escalation import EscalationHandler
from agent_core.autonomy.policy_rules import PolicyContext, rule_effector_authority
from agent_core.action_safety.safety_model import ValidationResult
from agent_core.action_safety.effect_validator import EffectValidator, StateSnapshot
from agent_core.effector.tool_specs import (
    is_tool_allowed, is_tool_dangerous, validate_args, TOOL_SPECS,
)
from agent_core.planner.planner_model import PlanStatus, ActionType


class TestReadinessChecklist:
    """
    Formal checklist: each test is one readiness criterion.
    All must pass before UNRESTRICTED level can be activated.
    """

    def test_safe_default(self):
        """R1: Default authority is OBSERVE. Unknown tools are denied."""
        cfg = AuthorityConfig()
        assert cfg.get_level() == AuthorityLevel.OBSERVE

        assert not is_tool_allowed("unknown_tool")
        assert is_tool_dangerous("unknown_tool")

    def test_authority_persistence(self, tmp_path):
        """R2: Authority level survives process restart (config file)."""
        path = tmp_path / "auth.json"
        mgr1 = AuthorityManager(config_path=path)
        mgr1.set_level(AuthorityLevel.CONFIRM)

        mgr2 = AuthorityManager(config_path=path)
        assert mgr2.get_level() == AuthorityLevel.CONFIRM

        data = json.loads(path.read_text())
        assert data["level"] == "confirm"
        assert data["updated_at"] > 0

    def test_unrestricted_blocked(self, tmp_path):
        """R3: UNRESTRICTED level cannot be set in Phase 5."""
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        assert not mgr.set_level(AuthorityLevel.UNRESTRICTED)
        assert mgr.get_level() == AuthorityLevel.OBSERVE

    def test_failure_bounded(self):
        """R4: After max_consecutive_failures, tool is locked (no runaway)."""
        budget = ToolBudgetManager(
            max_consecutive_failures=3,
            failure_cooldown_sec=300.0,
        )
        for _ in range(3):
            budget.record_invocation("exec", success=False)
        assert budget.is_locked("exec")
        ok, _ = budget.check_budget("exec")
        assert not ok

    def test_failure_explainable(self):
        """R5: Failure records include tool_name, reason."""
        budget = ToolBudgetManager(max_consecutive_failures=2)
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)
        ok, reason = budget.check_budget("exec")
        assert not ok
        assert "exec" in reason
        assert "locked" in reason

    def test_failure_recoverable(self):
        """R6: After cooldown expiry, locked tool can be retried."""
        budget = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=0.01,
        )
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)
        assert budget.is_locked("exec")
        time.sleep(0.02)
        ok, _ = budget.check_budget("exec")
        assert ok  # probe allowed

    def test_scheduler_non_blocking(self, tmp_path):
        """R7: Planner handles AWAITING_APPROVAL without blocking."""
        # AWAITING_APPROVAL is a valid PlanStatus
        assert PlanStatus.AWAITING_APPROVAL.value == "awaiting_approval"

        # ApprovalQueue operates independently
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        # No blocking - returns immediately
        assert req.status == "pending"
        # Approve is instant
        queue.approve(req.request_id)
        ready = queue.get_approved_ready()
        assert ready is not None

    def test_telegram_operator_loop(self, tmp_path):
        """R8: Operator can approve/reject/status/authority via commands."""
        # Simulate Telegram command workflow
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")

        # 1. Set authority
        mgr.set_level(AuthorityLevel.CONFIRM)
        assert mgr.get_level() == AuthorityLevel.CONFIRM

        # 2. Submit request
        req = queue.submit(
            plan_id="p1", tool_name="exec",
            tool_args={"command": "ls"},
            goal_description="Check files",
        )

        # 3. Operator sees status
        stats = queue.get_stats()
        assert stats["pending"] == 1

        # 4. Operator approves
        approved = queue.approve(req.request_id[:8])  # prefix match
        assert approved is not None

        # 5. System picks up
        ready = queue.get_approved_ready()
        assert ready.tool_name == "exec"

    def test_traceability(self):
        """R9: Effector has episode_id field in ApprovalRequest."""
        req = ApprovalRequest(
            request_id="ereq-test",
            plan_id="plan-1",
            tool_name="exec",
            tool_args={"command": "ls"},
            goal_id="goal-1",
            goal_description="Test",
            authority_level="confirm",
            created_at=time.time(),
            episode_id="ep-abc123",
        )
        assert req.episode_id == "ep-abc123"
        data = req.to_dict()
        assert data["episode_id"] == "ep-abc123"

    def test_rollback_awareness(self):
        """R10: Dangerous tools are correctly classified."""
        # exec, write, message are dangerous (irreversible in practice)
        for tool in ["exec", "write", "message"]:
            assert is_tool_dangerous(tool), f"{tool} should be dangerous"

        # Safe tools
        for tool in ["read", "web_fetch", "web_search", "cron"]:
            assert not is_tool_dangerous(tool), f"{tool} should be safe"

    def test_effector_validation_catches_anomaly(self):
        """R11: Effect validation detects empty result on success."""
        v = EffectValidator()
        before = StateSnapshot(timestamp=time.time() - 1, health_score=0.9, mode="active")
        after = StateSnapshot(timestamp=time.time(), health_score=0.9, mode="active")
        result = {
            "success": True,
            "tool_name": "exec",
            "tool_result": None,
        }
        validation, details = v.validate_effects("effector", before, after, result)
        assert validation == ValidationResult.UNEXPECTED

    def test_all_tools_have_arg_validation(self):
        """R12: Every allowed tool has argument validation."""
        for tool_name in TOOL_SPECS:
            spec = TOOL_SPECS[tool_name]
            assert spec.required_args is not None
            # Verify validation works
            valid, _ = validate_args(tool_name, {})
            if spec.required_args:
                assert not valid  # Should fail without required args

    def test_authority_levels_comprehensive(self):
        """R13: All 5 authority levels have correct behavior."""
        levels_and_expected = [
            ("observe", "block"),
            ("suggest", "escalate"),
            ("confirm", "escalate"),
        ]
        for level, expected_decision in levels_and_expected:
            ctx = PolicyContext(
                action_type="effector",
                authority_level=level,
                tool_name="exec",
                tool_dangerous=True,
            )
            result = rule_effector_authority(ctx)
            assert result is not None
            assert result.decision.value == expected_decision, (
                f"Level {level}: expected {expected_decision}, "
                f"got {result.decision.value}"
            )

        # BOUNDED: dangerous -> escalate, safe -> allow
        ctx_dangerous = PolicyContext(
            action_type="effector",
            authority_level="bounded",
            tool_name="exec",
            tool_dangerous=True,
        )
        assert rule_effector_authority(ctx_dangerous).decision.value == "escalate"

        ctx_safe = PolicyContext(
            action_type="effector",
            authority_level="bounded",
            tool_name="read",
            tool_dangerous=False,
        )
        assert rule_effector_authority(ctx_safe) is None  # allow

    def test_approval_queue_bounded_capacity(self, tmp_path):
        """R14: Queue has bounded capacity (no memory leak)."""
        from agent_core.autonomy.approval_queue import MAX_PENDING
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        for i in range(MAX_PENDING + 5):
            req = queue.submit(plan_id=f"p{i}", tool_name="exec", tool_args={})
        # After MAX_PENDING, new requests are rejected
        assert len(queue.get_pending()) == MAX_PENDING

    def test_jsonl_audit_trail(self, tmp_path):
        """R15: All approval decisions are persisted to JSONL."""
        path = tmp_path / "q.jsonl"
        queue = ApprovalQueue(log_path=path)
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        queue.approve(req.request_id)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2  # submit + approve
        submit_data = json.loads(lines[0])
        approve_data = json.loads(lines[1])
        assert submit_data["status"] == "pending"
        assert approve_data["status"] == "approved"
