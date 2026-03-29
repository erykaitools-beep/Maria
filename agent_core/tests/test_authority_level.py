"""
Tests for Phase 5: Authority Level Model + Effector Policy Rule.

Tests:
- AuthorityLevel enum values
- AuthorityConfig defaults, serialization
- AuthorityManager load/save/set_level
- rule_effector_authority at each level
- PolicyContext new fields
- Backward compatibility (non-effector RESTRICTED still blocked)
- AutonomyPolicy authority integration
"""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_core.autonomy.authority_level import (
    AuthorityLevel,
    AuthorityConfig,
    AuthorityManager,
    DEFAULT_TOOL_RATE_LIMITS,
    DEFAULT_FAILURE_COOLDOWN_SEC,
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    level_index,
)
from agent_core.autonomy.policy_rules import (
    PolicyContext,
    PolicyDecision,
    PolicyResult,
    rule_restricted_actions_block,
    rule_effector_authority,
)


# ---- AuthorityLevel enum ----

class TestAuthorityLevel:

    def test_enum_values(self):
        assert AuthorityLevel.OBSERVE.value == "observe"
        assert AuthorityLevel.SUGGEST.value == "suggest"
        assert AuthorityLevel.CONFIRM.value == "confirm"
        assert AuthorityLevel.BOUNDED.value == "bounded"
        assert AuthorityLevel.UNRESTRICTED.value == "unrestricted"

    def test_level_count(self):
        assert len(AuthorityLevel) == 5

    def test_level_index_ordering(self):
        assert level_index(AuthorityLevel.OBSERVE) < level_index(AuthorityLevel.SUGGEST)
        assert level_index(AuthorityLevel.SUGGEST) < level_index(AuthorityLevel.CONFIRM)
        assert level_index(AuthorityLevel.CONFIRM) < level_index(AuthorityLevel.BOUNDED)
        assert level_index(AuthorityLevel.BOUNDED) < level_index(AuthorityLevel.UNRESTRICTED)


# ---- AuthorityConfig ----

class TestAuthorityConfig:

    def test_defaults(self):
        cfg = AuthorityConfig()
        assert cfg.level == "observe"
        assert cfg.tool_rate_limits == DEFAULT_TOOL_RATE_LIMITS
        assert cfg.failure_cooldown_sec == DEFAULT_FAILURE_COOLDOWN_SEC
        assert cfg.max_consecutive_failures == DEFAULT_MAX_CONSECUTIVE_FAILURES
        assert cfg.updated_at == 0.0

    def test_get_level(self):
        cfg = AuthorityConfig(level="bounded")
        assert cfg.get_level() == AuthorityLevel.BOUNDED

    def test_get_level_unknown_defaults_observe(self):
        cfg = AuthorityConfig(level="nonexistent")
        assert cfg.get_level() == AuthorityLevel.OBSERVE

    def test_serialization_roundtrip(self):
        cfg = AuthorityConfig(level="confirm", updated_at=12345.0)
        data = cfg.to_dict()
        restored = AuthorityConfig.from_dict(data)
        assert restored.level == "confirm"
        assert restored.updated_at == 12345.0
        assert restored.tool_rate_limits == cfg.tool_rate_limits

    def test_from_dict_partial(self):
        """Missing keys use defaults."""
        cfg = AuthorityConfig.from_dict({"level": "suggest"})
        assert cfg.get_level() == AuthorityLevel.SUGGEST
        assert cfg.failure_cooldown_sec == DEFAULT_FAILURE_COOLDOWN_SEC

    def test_from_dict_empty(self):
        cfg = AuthorityConfig.from_dict({})
        assert cfg.get_level() == AuthorityLevel.OBSERVE


# ---- AuthorityManager ----

class TestAuthorityManager:

    def test_default_level_observe(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        assert mgr.get_level() == AuthorityLevel.OBSERVE

    def test_set_level_confirm(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        ok = mgr.set_level(AuthorityLevel.CONFIRM)
        assert ok
        assert mgr.get_level() == AuthorityLevel.CONFIRM

    def test_set_level_bounded(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        ok = mgr.set_level(AuthorityLevel.BOUNDED)
        assert ok
        assert mgr.get_level() == AuthorityLevel.BOUNDED

    def test_set_level_unrestricted_blocked(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        ok = mgr.set_level(AuthorityLevel.UNRESTRICTED)
        assert not ok
        assert mgr.get_level() == AuthorityLevel.OBSERVE  # unchanged

    def test_persistence(self, tmp_path):
        path = tmp_path / "auth.json"
        mgr1 = AuthorityManager(config_path=path)
        mgr1.set_level(AuthorityLevel.BOUNDED)

        # New manager loads from same file
        mgr2 = AuthorityManager(config_path=path)
        assert mgr2.get_level() == AuthorityLevel.BOUNDED

    def test_corrupted_file_defaults(self, tmp_path):
        path = tmp_path / "auth.json"
        path.write_text("not json", encoding="utf-8")
        mgr = AuthorityManager(config_path=path)
        assert mgr.get_level() == AuthorityLevel.OBSERVE

    def test_get_config_snapshot(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        mgr.set_level(AuthorityLevel.CONFIRM)
        cfg = mgr.get_config()
        assert cfg.get_level() == AuthorityLevel.CONFIRM

    def test_get_tool_rate_limit(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        assert mgr.get_tool_rate_limit("exec") == 5
        assert mgr.get_tool_rate_limit("web_fetch") == 20
        assert mgr.get_tool_rate_limit("unknown_tool") == 5  # default

    def test_get_status(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        status = mgr.get_status()
        assert status["authority_level"] == "observe"
        assert "tool_rate_limits" in status

    def test_updated_at_set_on_change(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        before = time.time()
        mgr.set_level(AuthorityLevel.CONFIRM)
        cfg = mgr.get_config()
        assert cfg.updated_at >= before


# ---- rule_effector_authority ----

class TestRuleEffectorAuthority:

    def _make_ctx(self, level="observe", tool_name="", dangerous=False, **kwargs):
        return PolicyContext(
            action_type="effector",
            authority_level=level,
            tool_name=tool_name,
            tool_dangerous=dangerous,
            **kwargs,
        )

    def test_observe_blocks(self):
        ctx = self._make_ctx(level="observe", tool_name="exec")
        result = rule_effector_authority(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.BLOCK
        assert "observe" in result.reasons[0]
        assert result.rule_name == "effector_authority"

    def test_suggest_escalates(self):
        ctx = self._make_ctx(level="suggest", tool_name="web_fetch")
        result = rule_effector_authority(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.ESCALATE
        assert "suggest" in result.reasons[0]

    def test_confirm_escalates(self):
        ctx = self._make_ctx(level="confirm", tool_name="read")
        result = rule_effector_authority(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.ESCALATE
        assert "confirm" in result.reasons[0]

    def test_bounded_safe_tool_allows(self):
        ctx = self._make_ctx(level="bounded", tool_name="web_fetch", dangerous=False)
        result = rule_effector_authority(ctx)
        assert result is None  # None = allow (pass through)

    def test_bounded_dangerous_tool_escalates(self):
        ctx = self._make_ctx(level="bounded", tool_name="exec", dangerous=True)
        result = rule_effector_authority(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.ESCALATE
        assert "dangerous" in result.reasons[0]
        assert "exec" in result.reasons[0]

    def test_unrestricted_allows(self):
        ctx = self._make_ctx(level="unrestricted", tool_name="exec", dangerous=True)
        result = rule_effector_authority(ctx)
        assert result is None  # allow

    def test_unknown_level_blocks(self):
        ctx = self._make_ctx(level="nonexistent", tool_name="read")
        result = rule_effector_authority(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.BLOCK

    def test_empty_tool_name(self):
        ctx = self._make_ctx(level="observe", tool_name="")
        result = rule_effector_authority(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.BLOCK


# ---- rule_restricted_actions_block backward compat ----

class TestRestrictedActionsBlockCompat:

    def test_forbidden_still_blocked(self):
        """Non-effector FORBIDDEN actions still blocked."""
        ctx = PolicyContext(action_type="delete_all")
        # delete_all is unknown -> RESTRICTED
        result = rule_restricted_actions_block(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.ESCALATE

    def test_effector_delegates_to_authority(self):
        """Effector actions go through authority rule."""
        ctx = PolicyContext(
            action_type="effector",
            authority_level="observe",
            tool_name="exec",
            tool_dangerous=True,
        )
        result = rule_restricted_actions_block(ctx)
        assert result is not None
        assert result.rule_name == "effector_authority"

    def test_free_action_passes(self):
        """FREE actions are not affected."""
        ctx = PolicyContext(action_type="learn")
        result = rule_restricted_actions_block(ctx)
        assert result is None

    def test_guarded_action_passes(self):
        """GUARDED actions are not affected by this rule."""
        ctx = PolicyContext(action_type="fetch")
        result = rule_restricted_actions_block(ctx)
        assert result is None


# ---- PolicyContext new fields ----

class TestPolicyContextNewFields:

    def test_default_values(self):
        ctx = PolicyContext(action_type="learn")
        assert ctx.authority_level == "observe"
        assert ctx.tool_name == ""
        assert ctx.tool_dangerous is False

    def test_custom_values(self):
        ctx = PolicyContext(
            action_type="effector",
            authority_level="bounded",
            tool_name="exec",
            tool_dangerous=True,
        )
        assert ctx.authority_level == "bounded"
        assert ctx.tool_name == "exec"
        assert ctx.tool_dangerous is True

    def test_frozen(self):
        ctx = PolicyContext(action_type="effector", tool_name="exec")
        with pytest.raises(AttributeError):
            ctx.tool_name = "write"


# ---- AutonomyPolicy authority integration ----

class TestAutonomyPolicyAuthority:

    def _make_policy(self, tmp_path, level="observe"):
        from agent_core.autonomy import AutonomyPolicy
        from agent_core.autonomy.escalation import EscalationHandler

        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        if level != "observe":
            mgr.set_level(AuthorityLevel(level))

        return AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
            authority_manager=mgr,
        )

    def test_observe_blocks_effector(self, tmp_path):
        policy = self._make_policy(tmp_path, level="observe")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "exec"},
        )
        assert not result.allowed
        assert result.decision == "block"

    def test_confirm_escalates_effector(self, tmp_path):
        policy = self._make_policy(tmp_path, level="confirm")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "exec"},
        )
        assert not result.allowed
        assert result.decision == "escalate"

    def test_bounded_allows_safe_tool(self, tmp_path):
        policy = self._make_policy(tmp_path, level="bounded")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "web_fetch"},
        )
        assert result.allowed

    def test_bounded_escalates_dangerous_tool(self, tmp_path):
        policy = self._make_policy(tmp_path, level="bounded")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "exec"},
        )
        assert not result.allowed
        assert result.decision == "escalate"

    def test_no_authority_manager_defaults_observe(self, tmp_path):
        from agent_core.autonomy import AutonomyPolicy
        from agent_core.autonomy.escalation import EscalationHandler

        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        )
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "read"},
        )
        assert not result.allowed
        assert result.decision == "block"

    def test_set_authority_level(self, tmp_path):
        policy = self._make_policy(tmp_path, level="observe")
        assert policy.get_authority_level() == AuthorityLevel.OBSERVE
        ok = policy.set_authority_level(AuthorityLevel.CONFIRM)
        assert ok
        assert policy.get_authority_level() == AuthorityLevel.CONFIRM

    def test_set_authority_unrestricted_blocked(self, tmp_path):
        policy = self._make_policy(tmp_path, level="observe")
        ok = policy.set_authority_level(AuthorityLevel.UNRESTRICTED)
        assert not ok
        assert policy.get_authority_level() == AuthorityLevel.OBSERVE

    def test_non_effector_unchanged(self, tmp_path):
        """Non-effector actions unaffected by authority level."""
        policy = self._make_policy(tmp_path, level="bounded")
        # learn is FREE, should always be allowed
        result = policy.check(action_type="learn")
        assert result.allowed

    def test_authority_status(self, tmp_path):
        policy = self._make_policy(tmp_path, level="confirm")
        status = policy.get_authority_status()
        assert status["authority_level"] == "confirm"

    def test_unknown_tool_treated_as_dangerous(self, tmp_path):
        """Unknown tool names are treated as dangerous."""
        policy = self._make_policy(tmp_path, level="bounded")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "unknown_tool"},
        )
        # unknown tool = dangerous, BOUNDED + dangerous = ESCALATE
        assert not result.allowed
        assert result.decision == "escalate"


# ---- is_tool_dangerous ----

class TestIsToolDangerous:

    def test_dangerous_tools(self):
        from agent_core.effector.tool_specs import is_tool_dangerous
        assert is_tool_dangerous("exec") is True
        assert is_tool_dangerous("write") is True
        assert is_tool_dangerous("message") is True

    def test_safe_tools(self):
        from agent_core.effector.tool_specs import is_tool_dangerous
        assert is_tool_dangerous("web_fetch") is False
        assert is_tool_dangerous("web_search") is False
        assert is_tool_dangerous("read") is False
        assert is_tool_dangerous("cron") is False

    def test_unknown_tool_dangerous(self):
        from agent_core.effector.tool_specs import is_tool_dangerous
        assert is_tool_dangerous("nonexistent") is True
