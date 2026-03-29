"""
Tests for Phase 5: Post-Execution Effect Validation for Effector Actions.

Tests:
- Effector action with empty result on success = UNEXPECTED
- Effector action with error on success = UNEXPECTED
- Effector action with proper result = VALID
- Effector health drop = UNEXPECTED
- Non-effector actions unaffected
- is_tool_dangerous utility
"""

import time

import pytest

from agent_core.action_safety.effect_validator import EffectValidator
from agent_core.action_safety.safety_model import (
    StateSnapshot,
    ValidationResult,
)
from agent_core.effector.tool_specs import is_tool_dangerous


class TestEffectorValidation:

    def _make_snapshots(self, health_before=0.9, health_after=0.9):
        before = StateSnapshot(
            timestamp=time.time() - 1,
            health_score=health_before,
            mode="active",
        )
        after = StateSnapshot(
            timestamp=time.time(),
            health_score=health_after,
            mode="active",
        )
        return before, after

    def test_valid_effector_result(self):
        v = EffectValidator()
        before, after = self._make_snapshots()
        result_data = {
            "success": True,
            "tool_name": "exec",
            "tool_result": "file list output",
        }
        validation, details = v.validate_effects("effector", before, after, result_data)
        assert validation == ValidationResult.VALID
        assert details["tool_name"] == "exec"

    def test_empty_result_on_success_unexpected(self):
        v = EffectValidator()
        before, after = self._make_snapshots()
        result_data = {
            "success": True,
            "tool_name": "exec",
            "tool_result": None,
        }
        validation, details = v.validate_effects("effector", before, after, result_data)
        assert validation == ValidationResult.UNEXPECTED
        assert details.get("empty_result_on_success") is True

    def test_empty_string_result_on_success_unexpected(self):
        v = EffectValidator()
        before, after = self._make_snapshots()
        result_data = {
            "success": True,
            "tool_name": "read",
            "tool_result": "",
        }
        validation, details = v.validate_effects("effector", before, after, result_data)
        assert validation == ValidationResult.UNEXPECTED
        assert details.get("empty_result_on_success") is True

    def test_zero_result_is_valid(self):
        """Numeric 0 result should not trigger empty check."""
        v = EffectValidator()
        before, after = self._make_snapshots()
        result_data = {
            "success": True,
            "tool_name": "exec",
            "tool_result": 0,
        }
        validation, _ = v.validate_effects("effector", before, after, result_data)
        assert validation == ValidationResult.VALID

    def test_error_on_success_unexpected(self):
        v = EffectValidator()
        before, after = self._make_snapshots()
        result_data = {
            "success": True,
            "tool_name": "exec",
            "tool_result": "output",
            "error": "warning: something went wrong",
        }
        validation, details = v.validate_effects("effector", before, after, result_data)
        assert validation == ValidationResult.UNEXPECTED
        assert "error_on_success" in details

    def test_health_drop_unexpected(self):
        v = EffectValidator()
        before, after = self._make_snapshots(health_before=0.9, health_after=0.5)
        result_data = {
            "success": True,
            "tool_name": "exec",
            "tool_result": "ok",
        }
        validation, details = v.validate_effects("effector", before, after, result_data)
        assert validation == ValidationResult.UNEXPECTED
        assert details.get("health_drop_unexpected") is True

    def test_failed_effector_no_empty_check(self):
        """Failed actions should not trigger empty-result check."""
        v = EffectValidator()
        before, after = self._make_snapshots()
        result_data = {
            "success": False,
            "tool_name": "exec",
            "tool_result": None,
            "error": "command failed",
        }
        validation, details = v.validate_effects("effector", before, after, result_data)
        # No empty_result_on_success because success=False
        assert details.get("empty_result_on_success") is None

    def test_non_effector_unaffected(self):
        """Non-effector AUDIT_ONLY actions don't have effector-specific checks."""
        v = EffectValidator()
        before, after = self._make_snapshots()
        result_data = {
            "success": True,
            "tool_name": "",
            "tool_result": None,
        }
        # fetch action - should not trigger effector checks
        validation, details = v.validate_effects("fetch", before, after, result_data)
        assert details.get("empty_result_on_success") is None

    def test_learn_still_skipped(self):
        """FREE actions still SKIPPED."""
        v = EffectValidator()
        before, after = self._make_snapshots()
        validation, _ = v.validate_effects("learn", before, after, {})
        assert validation == ValidationResult.SKIPPED


class TestIsToolDangerous:

    def test_exec_dangerous(self):
        assert is_tool_dangerous("exec") is True

    def test_write_dangerous(self):
        assert is_tool_dangerous("write") is True

    def test_message_dangerous(self):
        assert is_tool_dangerous("message") is True

    def test_web_fetch_safe(self):
        assert is_tool_dangerous("web_fetch") is False

    def test_web_search_safe(self):
        assert is_tool_dangerous("web_search") is False

    def test_read_safe(self):
        assert is_tool_dangerous("read") is False

    def test_cron_safe(self):
        assert is_tool_dangerous("cron") is False

    def test_unknown_dangerous(self):
        assert is_tool_dangerous("rm_rf") is True
