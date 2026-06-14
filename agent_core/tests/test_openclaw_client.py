"""
Tests for OpenClaw Effector Client, Tool Specs, and Planner Integration.

All subprocess calls are mocked - zero external dependencies.
"""

import json
import subprocess
from unittest.mock import patch, MagicMock

from agent_core.tests.spec_helpers import specced

import pytest

from agent_core.effector.openclaw_client import (
    OpenClawClient, OpenClawError, NODE_TOOLS, AGENT_TOOLS,
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
# TOOL ROUTING TESTS
# ============================================================

class TestToolRouting:
    """Tests for node vs agent tool routing."""

    def test_node_tools(self):
        assert NODE_TOOLS == {"exec", "read", "write"}

    def test_agent_tools(self):
        assert AGENT_TOOLS == {"web_fetch", "web_search", "message", "cron"}

    def test_all_allowed_tools_routed(self):
        """Every allowed tool must be in NODE_TOOLS or AGENT_TOOLS."""
        assert ALLOWED_TOOLS == NODE_TOOLS | AGENT_TOOLS


# ============================================================
# OPENCLAW CLIENT TESTS
# ============================================================

def _make_node_result(stdout="", stderr="", exit_code=0, ok=True):
    """Helper to create mock node JSON output."""
    payload = {
        "exitCode": exit_code,
        "timedOut": False,
        "success": exit_code == 0,
        "stdout": stdout,
        "stderr": stderr,
        "error": None,
    }
    return json.dumps({
        "ok": ok,
        "nodeId": "test-node-id",
        "command": "system.run",
        "payload": payload,
    })


def _make_subprocess_result(stdout="", stderr="", returncode=0):
    """Helper to create mock subprocess.CompletedProcess."""
    return subprocess.CompletedProcess(
        args=["openclaw"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


@pytest.fixture
def client():
    """Create client with test config."""
    return OpenClawClient(
        node_name="test-node",
        timeout_s=5,
        openclaw_bin="/usr/bin/openclaw",
    )


class TestOpenClawClientInit:
    """Tests for client initialization."""

    def test_default_node_name(self):
        with patch.dict("os.environ", {}, clear=True):
            c = OpenClawClient()
            assert c.node_name == "maria"

    def test_env_node_name(self):
        with patch.dict("os.environ", {"OPENCLAW_NODE_NAME": "custom-node"}):
            c = OpenClawClient()
            assert c.node_name == "custom-node"

    def test_explicit_overrides_env(self):
        with patch.dict("os.environ", {"OPENCLAW_NODE_NAME": "env-node"}):
            c = OpenClawClient(node_name="explicit-node")
            assert c.node_name == "explicit-node"

    @patch("shutil.which", return_value="/usr/local/bin/openclaw")
    def test_auto_detect_binary(self, mock_which):
        c = OpenClawClient()
        assert c.openclaw_bin == "/usr/local/bin/openclaw"

    def test_default_run_as_user(self):
        with patch.dict("os.environ", {}, clear=True):
            c = OpenClawClient()
            assert c.run_as_user == "deployadmin"

    def test_env_run_as_user(self):
        with patch.dict("os.environ", {"OPENCLAW_RUN_AS": "admin"}):
            c = OpenClawClient()
            assert c.run_as_user == "admin"

    def test_cli_prefix_with_user(self):
        c = OpenClawClient(openclaw_bin="/usr/bin/openclaw", run_as_user="deployadmin")
        assert c._cli_prefix() == ["sudo", "-u", "deployadmin", "/usr/bin/openclaw"]

    def test_cli_prefix_without_user(self):
        c = OpenClawClient(openclaw_bin="/usr/bin/openclaw", run_as_user="")
        assert c._cli_prefix() == ["/usr/bin/openclaw"]


class TestOpenClawClientInvokeNode:
    """Tests for invoke_tool() with node tools (exec, read, write)."""

    @patch("subprocess.run")
    def test_invoke_exec_success(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=_make_node_result(stdout="hello world\n"),
        )

        result = client.invoke_tool("exec", {"command": "echo hello world"})

        assert result["ok"] is True
        assert result["result"] == "hello world"
        assert result["exit_code"] == 0
        mock_run.assert_called_once()

        # Verify CLI args contain expected parts
        call_args = mock_run.call_args[0][0]
        assert "--node" in call_args
        assert "test-node" in call_args
        assert "--security" in call_args
        assert "full" in call_args
        assert "--json" in call_args

    @patch("subprocess.run")
    def test_invoke_read_success(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=_make_node_result(stdout="file contents here\n"),
        )

        result = client.invoke_tool("read", {"path": "/tmp/test.txt"})

        assert result["ok"] is True
        assert result["result"] == "file contents here"

        # Verify cat is used for read
        call_args = mock_run.call_args[0][0]
        assert "cat" in call_args
        assert "/tmp/test.txt" in call_args

    @patch("subprocess.run")
    def test_invoke_exec_nonzero_exit(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=_make_node_result(
                stdout="", stderr="command not found", exit_code=127,
            ),
        )

        result = client.invoke_tool("exec", {"command": "nonexistent"})
        assert result["exit_code"] == 127
        assert result["stderr"] == "command not found"

    @patch("subprocess.run")
    def test_invoke_exec_cli_error(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout="",
            stderr="openclaw: error connecting",
            returncode=1,
        )

        with pytest.raises(OpenClawError, match="Node command failed"):
            client.invoke_tool("exec", {"command": "ls"})

    @patch("subprocess.run")
    def test_invoke_exec_node_error(self, mock_run, client):
        error_json = json.dumps({
            "ok": False,
            "error": {"type": "not_found", "message": "Node not connected"},
        })
        mock_run.return_value = _make_subprocess_result(stdout=error_json)

        with pytest.raises(OpenClawError, match="Node not connected"):
            client.invoke_tool("exec", {"command": "ls"})

    def test_invoke_denied_tool(self, client):
        with pytest.raises(ValueError, match="explicitly denied"):
            client.invoke_tool("browser", {"task": "open google"})

    def test_invoke_unknown_tool(self, client):
        with pytest.raises(ValueError, match="not in the allowed tools"):
            client.invoke_tool("nonexistent_tool", {})

    def test_invoke_invalid_args(self, client):
        with pytest.raises(ValueError, match="Missing required"):
            client.invoke_tool("exec", {})  # missing "command"

    @patch("subprocess.run")
    def test_invoke_timeout(self, mock_run, client):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="openclaw", timeout=5)

        with pytest.raises(OpenClawError, match="Failed after"):
            client.invoke_tool("exec", {"command": "sleep 100"})

    @patch("subprocess.run")
    def test_invoke_retry_on_exception(self, mock_run, client):
        """Generic exceptions should retry once."""
        mock_run.side_effect = OSError("broken pipe")

        with pytest.raises(OpenClawError, match="Failed after"):
            client.invoke_tool("exec", {"command": "ls"})

        # Should have tried twice (1 original + 1 retry)
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_invoke_tracks_stats(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=_make_node_result(stdout="ok\n"),
        )
        client.invoke_tool("exec", {"command": "echo ok"})

        stats = client.get_stats()
        assert stats["total_calls"] == 1
        assert stats["successful_calls"] == 1
        assert stats["failed_calls"] == 0

    @patch("subprocess.run")
    def test_invoke_invalid_json(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(stdout="not json at all")

        with pytest.raises(OpenClawError, match="Invalid JSON"):
            client.invoke_tool("exec", {"command": "ls"})

    @patch("subprocess.run")
    def test_cli_uses_sudo(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=_make_node_result(stdout="ok\n"),
        )
        client.run_as_user = "deployadmin"
        client.invoke_tool("exec", {"command": "echo ok"})

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "sudo"
        assert call_args[1] == "-u"
        assert call_args[2] == "deployadmin"

    @patch("subprocess.run")
    def test_cli_no_sudo_when_no_user(self, mock_run):
        c = OpenClawClient(node_name="test", openclaw_bin="/usr/bin/openclaw", run_as_user="")
        mock_run.return_value = _make_subprocess_result(
            stdout=_make_node_result(stdout="ok\n"),
        )
        c.invoke_tool("exec", {"command": "echo ok"})

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "/usr/bin/openclaw"


class TestOpenClawClientInvokeAgent:
    """Tests for invoke_tool() with agent tools (web_fetch, web_search, etc.)."""

    @patch("subprocess.run")
    def test_invoke_web_fetch(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({"response": "Page content here"}),
        )

        result = client.invoke_tool("web_fetch", {"url": "https://example.com"})
        assert result["ok"] is True
        assert result["result"] == "Page content here"

        # Verify agent CLI args
        call_args = mock_run.call_args[0][0]
        assert "agent" in call_args
        assert "--session-id" in call_args
        assert "--json" in call_args

    @patch("subprocess.run")
    def test_invoke_web_search(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({"response": "search results"}),
        )

        result = client.invoke_tool("web_search", {"query": "python tutorial"})
        assert result["ok"] is True

    @patch("subprocess.run")
    def test_invoke_message(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({"response": "sent"}),
        )

        result = client.invoke_tool("message", {"content": "hello", "channel": "telegram"})
        assert result["ok"] is True

    @patch("subprocess.run")
    def test_invoke_agent_error(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout="", stderr="Agent error: no model", returncode=1,
        )

        with pytest.raises(OpenClawError, match="Agent command failed"):
            client.invoke_tool("web_fetch", {"url": "https://example.com"})

    @patch("subprocess.run")
    def test_invoke_agent_non_json_response(self, mock_run, client):
        """Agent may return plain text."""
        mock_run.return_value = _make_subprocess_result(
            stdout="Plain text response from agent",
        )

        result = client.invoke_tool("web_search", {"query": "test"})
        assert result["ok"] is True
        assert result["result"] == "Plain text response from agent"

    @patch("subprocess.run")
    def test_invoke_agent_aborted_status_is_not_ok(self, mock_run, client):
        """Openclaw can return exit 0 + JSON with status=aborted; ok=False."""
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({
                "status": "aborted",
                "response": "agent timed out before completing",
            }),
        )

        result = client.invoke_tool("web_search", {"query": "test"})
        assert result["ok"] is False
        assert result["status"] == "aborted"

    @patch("subprocess.run")
    def test_invoke_agent_error_status_is_not_ok(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({"status": "error", "response": "bad"}),
        )
        result = client.invoke_tool("web_fetch", {"url": "https://x"})
        assert result["ok"] is False
        assert result["status"] == "error"

    @patch("subprocess.run")
    def test_invoke_agent_meta_aborted_overrides_top_status_ok(self, mock_run, client):
        """Real openclaw format: status=ok BUT result.meta.aborted=True."""
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({
                "runId": "x",
                "status": "ok",
                "summary": "completed",
                "result": {
                    "payloads": [{"text": "Request timed out...", "mediaUrl": None}],
                    "meta": {"durationMs": 10448, "aborted": True},
                },
            }),
        )
        result = client.invoke_tool("web_search", {"query": "test"})
        assert result["ok"] is False
        assert result["status"] == "aborted"
        # text from payloads is surfaced
        assert "timed out" in result["result"].lower()

    @patch("subprocess.run")
    def test_invoke_agent_payload_text_on_success(self, mock_run, client):
        """Real openclaw success: text lives in result.payloads[0].text."""
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({
                "runId": "x",
                "status": "ok",
                "summary": "completed",
                "result": {
                    "payloads": [{"text": "Berlin weather: 12°C, cloudy"}],
                    "meta": {"durationMs": 5000, "aborted": False},
                },
            }),
        )
        result = client.invoke_tool("web_search", {"query": "berlin weather"})
        assert result["ok"] is True
        assert result["result"] == "Berlin weather: 12°C, cloudy"

    @patch("subprocess.run")
    def test_invoke_agent_ok_when_status_clean(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({
                "status": "ok",
                "response": "results here",
            }),
        )
        result = client.invoke_tool("web_search", {"query": "test"})
        assert result["ok"] is True
        assert result["result"] == "results here"

    @patch("subprocess.run")
    def test_invoke_cron(self, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=json.dumps({"response": "job scheduled"}),
        )

        result = client.invoke_tool("cron", {"action": "list"})
        assert result["ok"] is True


class TestOpenClawClientHealth:
    """Tests for health_check()."""

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/openclaw")
    def test_health_check_success(self, mock_which, mock_run, client):
        mock_run.return_value = _make_subprocess_result(
            stdout=_make_node_result(stdout="ok\n"),
        )
        assert client.health_check() is True

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/openclaw")
    def test_health_check_failure(self, mock_which, mock_run, client):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="openclaw", timeout=10)
        assert client.health_check() is False

    @patch("shutil.which", return_value=None)
    def test_health_check_no_binary(self, mock_which):
        c = OpenClawClient(openclaw_bin="openclaw")
        assert c.health_check() is False

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/openclaw")
    def test_health_check_cli_error(self, mock_which, mock_run, client):
        mock_run.return_value = _make_subprocess_result(returncode=1, stderr="error")
        assert client.health_check() is False


class TestOpenClawClientStats:
    """Tests for get_stats()."""

    def test_initial_stats(self, client):
        stats = client.get_stats()
        assert stats["total_calls"] == 0
        assert stats["node_name"] == "test-node"
        assert stats["last_error"] is None


class TestOpenClawClientHelpers:
    """Tests for internal helper methods."""

    def test_escape_shell_quotes(self):
        assert OpenClawClient._escape_shell("it's a test") == "it'\\''s a test"

    def test_escape_shell_normal(self):
        assert OpenClawClient._escape_shell("hello world") == "hello world"

    def test_build_agent_message_web_fetch(self, client):
        msg = client._build_agent_message("web_fetch", {"url": "https://example.com"})
        assert "https://example.com" in msg

    def test_build_agent_message_web_search(self, client):
        msg = client._build_agent_message("web_search", {"query": "test", "count": 3})
        assert "test" in msg
        assert "3" in msg

    def test_build_agent_message_message(self, client):
        msg = client._build_agent_message("message", {"content": "hi", "channel": "telegram"})
        assert "telegram" in msg
        assert "hi" in msg


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
        # action_class.py:46: post-24h-test plank up keeps effector GUARDED.
        assert classify_action("effector") == ActionClassification.GUARDED

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
        mock_client = specced(OpenClawClient)
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
        mock_client = specced(OpenClawClient)
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
        mock_client = specced(OpenClawClient)
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
