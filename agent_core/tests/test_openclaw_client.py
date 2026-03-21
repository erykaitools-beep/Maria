"""
Tests for OpenClaw Effector Client, Tool Specs, and Planner Integration.

All HTTP calls are mocked - zero external dependencies.
"""

import json
from unittest.mock import Mock, patch, MagicMock

import pytest

from agent_core.effector.openclaw_client import (
    OpenClawClient, OpenClawError, DEFAULT_GATEWAY_URL,
)
from agent_core.effector.tool_specs import (
    ToolSpec, TOOL_SPECS, ALLOWED_TOOLS, DENIED_TOOLS,
    is_tool_allowed, validate_args, get_tool_spec,
)


# ============================================================
# TOOL SPECS TESTS
# ============================================================

class TestToolSpecs:
    """Tests for tool_specs.py."""

    def test_allowed_tools_list(self):
        expected = {"exec", "web_fetch", "web_search", "message", "read", "write", "cron"}
        assert ALLOWED_TOOLS == expected

    def test_denied_tools_list(self):
        assert "browser" in DENIED_TOOLS
        assert "sessions_spawn" in DENIED_TOOLS
        assert "gateway" in DENIED_TOOLS

    def test_is_tool_allowed_exec(self):
        assert is_tool_allowed("exec") is True

    def test_is_tool_allowed_browser_denied(self):
        assert is_tool_allowed("browser") is False

    def test_is_tool_allowed_unknown(self):
        assert is_tool_allowed("nonexistent_tool") is False

    def test_validate_args_exec_valid(self):
        ok, reason = validate_args("exec", {"command": "ls -la"})
        assert ok is True

    def test_validate_args_exec_missing_command(self):
        ok, reason = validate_args("exec", {})
        assert ok is False
        assert "command" in reason

    def test_validate_args_web_fetch_valid(self):
        ok, reason = validate_args("web_fetch", {"url": "https://example.com"})
        assert ok is True

    def test_validate_args_web_search_valid(self):
        ok, reason = validate_args("web_search", {"query": "python tutorial"})
        assert ok is True

    def test_validate_args_message_valid(self):
        ok, reason = validate_args("message", {"content": "hello"})
        assert ok is True

    def test_validate_args_write_valid(self):
        ok, reason = validate_args("write", {"path": "/tmp/test.txt", "content": "data"})
        assert ok is True

    def test_validate_args_write_missing_content(self):
        ok, reason = validate_args("write", {"path": "/tmp/test.txt"})
        assert ok is False
        assert "content" in reason

    def test_validate_args_unknown_tool(self):
        ok, reason = validate_args("unknown_tool", {"foo": "bar"})
        assert ok is False
        assert "Unknown" in reason

    def test_validate_args_optional_accepted(self):
        ok, reason = validate_args("exec", {"command": "ls", "workdir": "/tmp", "timeout": 30})
        assert ok is True

    def test_get_tool_spec(self):
        spec = get_tool_spec("exec")
        assert spec is not None
        assert spec.name == "exec"
        assert spec.dangerous is True
        assert "command" in spec.required_args

    def test_get_tool_spec_unknown(self):
        assert get_tool_spec("nonexistent") is None

    def test_tool_spec_frozen(self):
        spec = get_tool_spec("exec")
        with pytest.raises(AttributeError):
            spec.name = "hacked"

    def test_dangerous_tools(self):
        assert get_tool_spec("exec").dangerous is True
        assert get_tool_spec("message").dangerous is True
        assert get_tool_spec("write").dangerous is True
        assert get_tool_spec("web_fetch").dangerous is False
        assert get_tool_spec("web_search").dangerous is False


# ============================================================
# OPENCLAW CLIENT TESTS
# ============================================================

@pytest.fixture
def client():
    """Create client with test config."""
    return OpenClawClient(
        base_url="http://test-gateway:18789",
        token="test-token-123",
        timeout_s=5,
    )


@pytest.fixture
def mock_response():
    """Create a mock requests.Response."""
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": "test output"}
    resp.text = '{"ok": true, "result": "test output"}'
    resp.headers = {}
    return resp


class TestOpenClawClientInit:
    """Tests for client initialization."""

    def test_default_url(self):
        with patch.dict("os.environ", {}, clear=True):
            c = OpenClawClient(token="tok")
            assert c.base_url == DEFAULT_GATEWAY_URL

    def test_env_url(self):
        with patch.dict("os.environ", {"OPENCLAW_GATEWAY_URL": "http://custom:9999"}):
            c = OpenClawClient(token="tok")
            assert c.base_url == "http://custom:9999"

    def test_env_token(self):
        with patch.dict("os.environ", {"OPENCLAW_GATEWAY_TOKEN": "env-token"}):
            c = OpenClawClient()
            assert c.token == "env-token"

    def test_explicit_overrides_env(self):
        with patch.dict("os.environ", {"OPENCLAW_GATEWAY_URL": "http://env:1234"}):
            c = OpenClawClient(base_url="http://explicit:5678", token="tok")
            assert c.base_url == "http://explicit:5678"

    def test_trailing_slash_stripped(self):
        c = OpenClawClient(base_url="http://test:18789/", token="tok")
        assert c.base_url == "http://test:18789"


class TestOpenClawClientInvoke:
    """Tests for invoke_tool()."""

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_exec_success(self, mock_post, client, mock_response):
        mock_post.return_value = mock_response
        result = client.invoke_tool("exec", {"command": "echo hello"})

        assert result == {"ok": True, "result": "test output"}
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["tool"] == "exec"
        assert call_kwargs[1]["json"]["args"]["command"] == "echo hello"
        assert "Bearer test-token-123" in call_kwargs[1]["headers"]["Authorization"]

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_web_fetch(self, mock_post, client, mock_response):
        mock_post.return_value = mock_response
        result = client.invoke_tool("web_fetch", {"url": "https://example.com"})
        assert result["ok"] is True

    def test_invoke_denied_tool(self, client):
        with pytest.raises(ValueError, match="explicitly denied"):
            client.invoke_tool("browser", {"task": "open google"})

    def test_invoke_unknown_tool(self, client):
        with pytest.raises(ValueError, match="not in the allowed tools"):
            client.invoke_tool("nonexistent_tool", {})

    def test_invoke_invalid_args(self, client):
        with pytest.raises(ValueError, match="Missing required"):
            client.invoke_tool("exec", {})  # missing "command"

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_auth_error(self, mock_post, client):
        resp = Mock()
        resp.status_code = 401
        resp.json.return_value = {"ok": False, "error": {"message": "Unauthorized"}}
        resp.text = "Unauthorized"
        mock_post.return_value = resp

        with pytest.raises(OpenClawError) as exc_info:
            client.invoke_tool("exec", {"command": "ls"})
        assert exc_info.value.status_code == 401
        assert "Authentication" in str(exc_info.value)

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_tool_not_found(self, mock_post, client):
        resp = Mock()
        resp.status_code = 404
        resp.json.return_value = {"ok": False, "error": {"message": "Not found"}}
        resp.text = "Not found"
        mock_post.return_value = resp

        with pytest.raises(OpenClawError) as exc_info:
            client.invoke_tool("exec", {"command": "ls"})
        assert exc_info.value.status_code == 404

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_rate_limited(self, mock_post, client):
        resp = Mock()
        resp.status_code = 429
        resp.json.return_value = {"ok": False}
        resp.text = "Rate limited"
        resp.headers = {"Retry-After": "60"}
        mock_post.return_value = resp

        with pytest.raises(OpenClawError) as exc_info:
            client.invoke_tool("exec", {"command": "ls"})
        assert exc_info.value.status_code == 429

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_server_error(self, mock_post, client):
        resp = Mock()
        resp.status_code = 500
        resp.json.return_value = {"ok": False, "error": {"type": "internal", "message": "crash"}}
        resp.text = "Internal error"
        mock_post.return_value = resp

        with pytest.raises(OpenClawError) as exc_info:
            client.invoke_tool("exec", {"command": "ls"})
        assert exc_info.value.status_code == 500

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_connection_error_retry(self, mock_post, client):
        """Connection errors should retry once."""
        import requests as req
        mock_post.side_effect = req.ConnectionError("Connection refused")

        with pytest.raises(OpenClawError, match="unreachable"):
            client.invoke_tool("exec", {"command": "ls"})

        # Should have tried twice (1 original + 1 retry)
        assert mock_post.call_count == 2

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_invoke_tracks_stats(self, mock_post, client, mock_response):
        mock_post.return_value = mock_response
        client.invoke_tool("exec", {"command": "ls"})
        client.invoke_tool("web_fetch", {"url": "https://example.com"})

        stats = client.get_stats()
        assert stats["total_calls"] == 2
        assert stats["successful_calls"] == 2
        assert stats["failed_calls"] == 0
        assert stats["token_configured"] is True


class TestOpenClawClientHealth:
    """Tests for health_check()."""

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_health_check_success(self, mock_post, client):
        resp = Mock()
        resp.status_code = 200
        mock_post.return_value = resp
        assert client.health_check() is True

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_health_check_failure(self, mock_post, client):
        import requests as req
        mock_post.side_effect = req.ConnectionError("refused")
        assert client.health_check() is False

    def test_health_check_no_token(self):
        c = OpenClawClient(token="")
        assert c.health_check() is False

    @patch("agent_core.effector.openclaw_client.requests.post")
    def test_health_check_server_error(self, mock_post, client):
        resp = Mock()
        resp.status_code = 500
        mock_post.return_value = resp
        assert client.health_check() is False


class TestOpenClawClientStats:
    """Tests for get_stats()."""

    def test_initial_stats(self, client):
        stats = client.get_stats()
        assert stats["total_calls"] == 0
        assert stats["base_url"] == "http://test-gateway:18789"
        assert stats["token_configured"] is True
        assert stats["last_error"] is None


# ============================================================
# PLANNER INTEGRATION TESTS
# ============================================================

class TestActionTypeEffector:
    """Tests for ActionType.EFFECTOR integration."""

    def test_action_type_exists(self):
        from agent_core.planner.planner_model import ActionType
        assert hasattr(ActionType, "EFFECTOR")
        assert ActionType.EFFECTOR.value == "effector"

    def test_k7_classification(self):
        from agent_core.autonomy.action_class import (
            classify_action, ActionClassification,
        )
        assert classify_action("effector") == ActionClassification.RESTRICTED

    def test_k7_rate_limit(self):
        from agent_core.autonomy.rate_limiter import DEFAULT_RATE_LIMITS
        assert "effector" in DEFAULT_RATE_LIMITS
        assert DEFAULT_RATE_LIMITS["effector"] == 10

    def test_k10_safety_profile(self):
        from agent_core.action_safety.safety_classifier import (
            get_safety_profile,
        )
        from agent_core.action_safety.safety_model import (
            SafetyMode, Reversibility, EffectType,
        )
        profile = get_safety_profile("effector")
        assert profile.safety_mode == SafetyMode.AUDIT_ONLY
        assert profile.reversibility == Reversibility.PARTIALLY_REVERSIBLE
        assert profile.effect_type == EffectType.EXTERNAL_API
        assert profile.needs_before_snapshot is True
        assert profile.needs_after_snapshot is True


class TestActionExecutorEffector:
    """Tests for _exec_effector in ActionExecutor."""

    def test_exec_effector_no_client(self):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import ActionType, Plan, PlanStatus
        import uuid, time as t

        executor = ActionExecutor()
        plan = Plan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            timestamp=t.time(),
            goal_id=None,
            goal_description="test",
            action_type=ActionType.EFFECTOR,
            action_params={"tool_name": "exec", "tool_args": {"command": "ls"}},
            status=PlanStatus.EXECUTING,
        )
        result = executor.execute(plan)
        assert result["success"] is False
        assert "No OpenClaw" in result["error"]

    def test_exec_effector_no_tool_name(self):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import ActionType, Plan, PlanStatus
        import uuid, time as t

        executor = ActionExecutor()
        mock_client = Mock()
        executor.set_openclaw_client(mock_client)

        plan = Plan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            timestamp=t.time(),
            goal_id=None,
            goal_description="test",
            action_type=ActionType.EFFECTOR,
            action_params={},  # no tool_name
            status=PlanStatus.EXECUTING,
        )
        result = executor.execute(plan)
        assert result["success"] is False
        assert "tool_name" in result["error"]

    def test_exec_effector_success(self):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import ActionType, Plan, PlanStatus
        import uuid, time as t

        executor = ActionExecutor()
        mock_client = Mock()
        mock_client.invoke_tool.return_value = {"ok": True, "result": "file list"}
        executor.set_openclaw_client(mock_client)

        plan = Plan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            timestamp=t.time(),
            goal_id=None,
            goal_description="test",
            action_type=ActionType.EFFECTOR,
            action_params={"tool_name": "exec", "tool_args": {"command": "ls"}},
            status=PlanStatus.EXECUTING,
        )
        result = executor.execute(plan)
        assert result["success"] is True
        assert result["tool_name"] == "exec"
        assert result["tool_result"] == "file list"
        mock_client.invoke_tool.assert_called_once_with(
            tool_name="exec", args={"command": "ls"},
        )

    def test_exec_effector_client_error(self):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import ActionType, Plan, PlanStatus
        import uuid, time as t

        executor = ActionExecutor()
        mock_client = Mock()
        mock_client.invoke_tool.side_effect = OpenClawError("Gateway down")
        executor.set_openclaw_client(mock_client)

        plan = Plan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            timestamp=t.time(),
            goal_id=None,
            goal_description="test",
            action_type=ActionType.EFFECTOR,
            action_params={"tool_name": "exec", "tool_args": {"command": "ls"}},
            status=PlanStatus.EXECUTING,
        )
        result = executor.execute(plan)
        assert result["success"] is False
        assert "Gateway down" in result["error"]
