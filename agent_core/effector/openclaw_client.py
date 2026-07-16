"""
OpenClaw Client - Subprocess client for OpenClaw Gateway.

Maria uses OpenClaw as an effector: she decides WHAT to do (cognitive core),
OpenClaw executes HOW (shell, web, messaging, files).

Integration via CLI subprocess (not HTTP):
- Node tools (exec, read, write): openclaw nodes run --json
- Agent tools (web_fetch, web_search, message, cron): openclaw agent --json

ADR-016: OpenClaw jako efektor (tools/invoke bez LLM), Maria jako mozg.
"""

import json
import logging
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from .tool_specs import (
    is_tool_allowed, validate_args, ALLOWED_TOOLS, DENIED_TOOLS,
)

logger = logging.getLogger(__name__)


# Default configuration
DEFAULT_TIMEOUT_S = 30          # node tools (exec/read/write) — fast
DEFAULT_AGENT_TIMEOUT_S = 180   # agent tools (web_search/web_fetch) —
                                # qwen2.5:3b cold-start (~15-30s) + tool
                                # call (~20-30s) + generation (~20-30s).
                                # With coordinator pre-warm this rarely
                                # needs the full budget.
HEALTH_CHECK_TIMEOUT_S = 10
MAX_RETRIES = 1

# Tools executed via node (system.run) vs agent (LLM)
NODE_TOOLS = {"exec", "read", "write"}
AGENT_TOOLS = {"web_fetch", "web_search", "message", "cron"}


class OpenClawError(Exception):
    """Error from OpenClaw gateway."""

    def __init__(self, message: str, error_type: str = "", status_code: int = 0):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


class OpenClawClient:
    """
    Subprocess client for OpenClaw Gateway.

    Sends tool invocation requests via CLI and returns results.
    All tools go through whitelist validation before being sent.

    Node tools (exec, read, write) use: openclaw nodes run
    Agent tools (web_fetch, web_search) use: openclaw agent

    Usage:
        client = OpenClawClient()
        if client.health_check():
            result = client.invoke_tool("exec", {"command": "df -h"})
            print(result)  # {"ok": True, "result": {...}}
    """

    def __init__(
        self,
        node_name: Optional[str] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        agent_timeout_s: float = DEFAULT_AGENT_TIMEOUT_S,
        openclaw_bin: Optional[str] = None,
        run_as_user: Optional[str] = None,
    ):
        """
        Initialize OpenClaw client.

        Args:
            node_name: Node name for node tools (default: env OPENCLAW_NODE_NAME or "maria")
            timeout_s: Timeout for node tools (exec/read/write) in seconds
            agent_timeout_s: Timeout for agent tools (web_search/web_fetch) in
                seconds — larger because qwen2.5:3b must cold-start and run
                an LLM turn + tool invocation + generation
            openclaw_bin: Path to openclaw binary (auto-detected if None)
            run_as_user: Run openclaw as this user via sudo (default: env OPENCLAW_RUN_AS or "deployadmin")
        """
        self.node_name = (
            node_name
            or os.environ.get("OPENCLAW_NODE_NAME", "")
            or "maria"
        )
        self.timeout_s = timeout_s
        self.agent_timeout_s = agent_timeout_s
        self.openclaw_bin = openclaw_bin or shutil.which("openclaw") or "openclaw"
        if run_as_user is not None:
            self.run_as_user = run_as_user
        else:
            self.run_as_user = os.environ.get("OPENCLAW_RUN_AS", "deployadmin")

        # Stats
        self._total_calls = 0
        self._successful_calls = 0
        self._failed_calls = 0
        self._last_error: Optional[str] = None

    def invoke_tool(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Invoke an OpenClaw tool.

        Args:
            tool_name: Tool to invoke (e.g. "exec", "web_fetch")
            args: Tool-specific arguments

        Returns:
            Dict with "ok" and "result" or "error" keys

        Raises:
            OpenClawError: On execution errors
            ValueError: If tool is not allowed or args invalid
        """
        args = args or {}

        # Whitelist check
        if not is_tool_allowed(tool_name):
            if tool_name in DENIED_TOOLS:
                raise ValueError(
                    f"Tool '{tool_name}' is explicitly denied"
                )
            raise ValueError(
                f"Tool '{tool_name}' is not in the allowed tools list: "
                f"{sorted(ALLOWED_TOOLS)}"
            )

        # Validate args
        valid, reason = validate_args(tool_name, args)
        if not valid:
            raise ValueError(f"Invalid args for {tool_name}: {reason}")

        self._total_calls += 1

        # Route to node or agent
        last_error = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                if tool_name in NODE_TOOLS:
                    result = self._invoke_node(tool_name, args)
                else:
                    result = self._invoke_agent(tool_name, args)
                self._successful_calls += 1
                self._last_error = None
                return result
            except OpenClawError:
                raise
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"[OpenClaw] Error (attempt {attempt + 1}), retrying: {e}"
                    )
                    time.sleep(1)

        self._failed_calls += 1
        self._last_error = str(last_error)
        raise OpenClawError(
            f"Failed after {MAX_RETRIES + 1} attempts: {last_error}",
            error_type="execution_error",
        )

    def _cli_prefix(self) -> list:
        """Build command prefix (sudo -u deployadmin if needed)."""
        if self.run_as_user:
            return ["sudo", "-u", self.run_as_user, self.openclaw_bin]
        return [self.openclaw_bin]

    def health_check(self) -> bool:
        """
        Check if OpenClaw is reachable.

        Sends a minimal command through the node to verify connectivity.

        Returns:
            True if OpenClaw responds, False otherwise
        """
        if not shutil.which(self.openclaw_bin):
            logger.debug("[OpenClaw] Binary not found, skipping health check")
            return False

        try:
            result = subprocess.run(
                self._cli_prefix() + [
                    "nodes", "run",
                    "--node", self.node_name,
                    "--security", "full",
                    "--json",
                    "--", "echo", "ok",
                ],
                capture_output=True,
                text=True,
                timeout=HEALTH_CHECK_TIMEOUT_S,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("ok", False)
            return False
        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            "node_name": self.node_name,
            "openclaw_bin": self.openclaw_bin,
            "total_calls": self._total_calls,
            "successful_calls": self._successful_calls,
            "failed_calls": self._failed_calls,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Internal: Node tools (exec, read, write)
    # ------------------------------------------------------------------

    def _invoke_node(self, tool_name: str, args: Dict) -> Dict[str, Any]:
        """
        Invoke a tool via openclaw nodes run (system.run on node).

        For exec: runs command directly.
        For read: runs cat <path>.
        For write: runs tee to write content.
        """
        if tool_name == "exec":
            # Prefer an explicit argv list (each element passed as ONE argument, no
            # whitespace re-splitting) when the caller provides it -- e.g. the undo
            # inverse 'rm -- <path>' for a path with spaces. Re-splitting a
            # shlex.quote-d command string here would destroy the quoting and
            # delete the wrong path. Fall back to the legacy split for existing
            # string-command callers.
            argv = args.get("argv")
            if isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv):
                cmd_parts = list(argv)
            else:
                command = args["command"]
                cmd_parts = command.split()
        elif tool_name == "read":
            path = args["path"]
            import shlex
            cmd_parts = ["cat", "--", path]  # -- prevents path starting with -
        elif tool_name == "write":
            path = args["path"]
            content = args["content"]
            # Use tee for writing (content via stdin not supported by nodes run)
            # Fall back to shell: printf 'content' > path
            import shlex
            cmd_parts = ["sh", "-c", f"printf '%s' {shlex.quote(self._escape_shell(content))} > {shlex.quote(path)}"]
        else:
            raise OpenClawError(f"Unknown node tool: {tool_name}")

        cli_args = self._cli_prefix() + [
            "nodes", "run",
            "--node", self.node_name,
            "--security", "full",
            "--json",
            "--timeout", str(int(self.timeout_s * 1000)),
            "--",
        ] + cmd_parts

        logger.info(f"[OpenClaw] Node invoke: {tool_name} -> {' '.join(cmd_parts)[:100]}")

        result = subprocess.run(
            cli_args,
            capture_output=True,
            text=True,
            timeout=self.timeout_s + 5,  # extra buffer for CLI overhead
        )

        return self._parse_node_result(result, tool_name)

    def _parse_node_result(self, result: subprocess.CompletedProcess, tool_name: str) -> Dict[str, Any]:
        """Parse openclaw nodes run --json output."""
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            raise OpenClawError(
                f"Node command failed: {error_msg}",
                error_type="node_error",
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise OpenClawError(
                f"Invalid JSON from node: {result.stdout[:200]}",
                error_type="parse_error",
            )

        if not data.get("ok", False):
            error = data.get("error", {})
            msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise OpenClawError(msg, error_type="node_error")

        # Extract payload
        payload = data.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {"stdout": payload}

        return {
            "ok": payload.get("success", True),
            "result": payload.get("stdout", "").rstrip("\n"),
            "stderr": payload.get("stderr", ""),
            "exit_code": payload.get("exitCode", 0),
        }

    # ------------------------------------------------------------------
    # Internal: Agent tools (web_fetch, web_search, message, cron)
    # ------------------------------------------------------------------

    def _invoke_agent(self, tool_name: str, args: Dict) -> Dict[str, Any]:
        """
        Invoke a tool via openclaw agent (LLM-powered).

        Sends a structured message to the agent asking it to use a specific tool.
        """
        # Build instruction message
        message = self._build_agent_message(tool_name, args)

        cli_args = self._cli_prefix() + [
            "agent",
            "--session-id", "maria-effector",
            "--message", message,
            "--json",
            "--timeout", str(int(self.agent_timeout_s)),
        ]

        logger.info(f"[OpenClaw] Agent invoke: {tool_name}")

        result = subprocess.run(
            cli_args,
            capture_output=True,
            text=True,
            timeout=self.agent_timeout_s + 10,
        )

        return self._parse_agent_result(result, tool_name)

    def _build_agent_message(self, tool_name: str, args: Dict) -> str:
        """Build a message for the agent to invoke a specific tool."""
        if tool_name == "web_fetch":
            url = args["url"]
            return f"Fetch this URL and return the content: {url}"
        elif tool_name == "web_search":
            query = args["query"]
            count = args.get("count", 5)
            return f"Search the web for: {query} (return top {count} results)"
        elif tool_name == "message":
            content = args["content"]
            channel = args.get("channel", "")
            if channel:
                return f"Send this message via {channel}: {content}"
            return f"Send this message: {content}"
        elif tool_name == "cron":
            action = args["action"]
            name = args.get("name", "")
            return f"Cron action '{action}' for job '{name}': {json.dumps(args)}"
        else:
            return f"Use the {tool_name} tool with args: {json.dumps(args)}"

    def _parse_agent_result(self, result: subprocess.CompletedProcess, tool_name: str) -> Dict[str, Any]:
        """Parse openclaw agent --json output."""
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            raise OpenClawError(
                f"Agent command failed: {error_msg}",
                error_type="agent_error",
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Agent may return non-JSON text
            return {
                "ok": True,
                "result": result.stdout.strip(),
                "status": "",
            }

        # Openclaw's real format (verified 2026-04-18):
        #   top-level `status` is often "ok" even when the agent aborted;
        #   the ground truth lives at result.meta.aborted (bool).
        # So we must look both places and extract the user-facing text
        # from result.payloads[0].text when the nested result is a dict.
        status = str(data.get("status", "")).lower()
        result_obj = data.get("result")
        meta = (
            result_obj.get("meta", {})
            if isinstance(result_obj, dict) else {}
        )
        inner_aborted = bool(meta.get("aborted"))
        if inner_aborted and status not in (
            "aborted", "error", "failed", "timeout",
        ):
            status = "aborted"

        ok = (not data.get("error")) and status not in (
            "aborted", "error", "failed", "timeout",
        )

        # Prefer the first payload's text — that's the actual agent reply.
        response_text = None
        if isinstance(result_obj, dict):
            payloads = result_obj.get("payloads") or []
            if payloads and isinstance(payloads[0], dict):
                response_text = payloads[0].get("text")

        return {
            "ok": ok,
            "result": (
                response_text
                or data.get("response")
                or result_obj
                or result.stdout.strip()
            ),
            "status": status,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_shell(s: str) -> str:
        """Escape single quotes in string for shell."""
        return s.replace("'", "'\\''")
