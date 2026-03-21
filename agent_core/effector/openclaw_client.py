"""
OpenClaw Client - HTTP client for OpenClaw Gateway tools/invoke API.

Maria uses OpenClaw as an effector: she decides WHAT to do (cognitive core),
OpenClaw executes HOW (shell, web, messaging, files).

API: POST http://127.0.0.1:18789/tools/invoke
Auth: Bearer token
Docs: docs.openclaw.ai/gateway/tools-invoke-http-api

ADR-016: OpenClaw jako efektor (tools/invoke bez LLM), Maria jako mozg.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from .tool_specs import (
    is_tool_allowed, validate_args, ALLOWED_TOOLS, DENIED_TOOLS,
)

logger = logging.getLogger(__name__)


# Default configuration
DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789"
DEFAULT_TIMEOUT_S = 30
HEALTH_CHECK_TIMEOUT_S = 5
MAX_RETRIES = 1


class OpenClawError(Exception):
    """Error from OpenClaw gateway."""

    def __init__(self, message: str, error_type: str = "", status_code: int = 0):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


class OpenClawClient:
    """
    HTTP client for OpenClaw Gateway.

    Sends tool invocation requests to the gateway and returns results.
    All tools go through whitelist validation before being sent.

    Usage:
        client = OpenClawClient()
        if client.health_check():
            result = client.invoke_tool("exec", {"command": "df -h"})
            print(result)  # {"ok": True, "result": "..."}
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ):
        """
        Initialize OpenClaw client.

        Args:
            base_url: Gateway URL (default: env OPENCLAW_GATEWAY_URL or localhost:18789)
            token: Auth token (default: env OPENCLAW_GATEWAY_TOKEN)
            timeout_s: Request timeout in seconds
        """
        self.base_url = (
            base_url
            or os.environ.get("OPENCLAW_GATEWAY_URL", "")
            or DEFAULT_GATEWAY_URL
        ).rstrip("/")

        self.token = token or os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
        self.timeout_s = timeout_s

        # Stats
        self._total_calls = 0
        self._successful_calls = 0
        self._failed_calls = 0
        self._last_error: Optional[str] = None

    def invoke_tool(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        session_key: str = "main",
    ) -> Dict[str, Any]:
        """
        Invoke an OpenClaw tool via the gateway HTTP API.

        Args:
            tool_name: Tool to invoke (e.g. "exec", "web_fetch")
            args: Tool-specific arguments
            session_key: Target session (default "main")

        Returns:
            Dict with "ok", "result" or "error" keys

        Raises:
            OpenClawError: On gateway errors (4xx, 5xx)
            ValueError: If tool is not allowed or args invalid
        """
        args = args or {}

        # Whitelist check
        if not is_tool_allowed(tool_name):
            if tool_name in DENIED_TOOLS:
                raise ValueError(
                    f"Tool '{tool_name}' is explicitly denied for HTTP invocation"
                )
            raise ValueError(
                f"Tool '{tool_name}' is not in the allowed tools list: "
                f"{sorted(ALLOWED_TOOLS)}"
            )

        # Validate args
        valid, reason = validate_args(tool_name, args)
        if not valid:
            raise ValueError(f"Invalid args for {tool_name}: {reason}")

        # Build request
        payload = {
            "tool": tool_name,
            "args": args,
            "sessionKey": session_key,
        }

        self._total_calls += 1

        # Send with retry
        last_error = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                response = self._post(payload)
                self._successful_calls += 1
                self._last_error = None
                return response
            except requests.ConnectionError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"[OpenClaw] Connection error (attempt {attempt + 1}), retrying..."
                    )
                    time.sleep(1)
            except Exception as e:
                self._failed_calls += 1
                self._last_error = str(e)
                raise

        # All retries exhausted
        self._failed_calls += 1
        self._last_error = str(last_error)
        raise OpenClawError(
            f"Gateway unreachable after {MAX_RETRIES + 1} attempts: {last_error}",
            error_type="connection_error",
        )

    def health_check(self) -> bool:
        """
        Check if OpenClaw gateway is reachable.

        Sends a minimal exec command to verify the gateway is alive.
        Returns False gracefully if gateway is down.

        Returns:
            True if gateway responds, False otherwise
        """
        if not self.token:
            logger.debug("[OpenClaw] No token configured, skipping health check")
            return False

        try:
            response = requests.post(
                f"{self.base_url}/tools/invoke",
                json={
                    "tool": "exec",
                    "args": {"command": "echo ok"},
                    "sessionKey": "main",
                },
                headers=self._headers(),
                timeout=HEALTH_CHECK_TIMEOUT_S,
            )
            return response.status_code == 200
        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            "base_url": self.base_url,
            "token_configured": bool(self.token),
            "total_calls": self._total_calls,
            "successful_calls": self._successful_calls,
            "failed_calls": self._failed_calls,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        """Build request headers with auth token."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _post(self, payload: Dict) -> Dict[str, Any]:
        """
        Send POST request to gateway.

        Returns:
            Parsed response dict

        Raises:
            OpenClawError: On non-200 responses
        """
        url = f"{self.base_url}/tools/invoke"

        response = requests.post(
            url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_s,
        )

        # Parse response
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = {"ok": False, "error": {"message": response.text[:500]}}

        # Handle error responses
        if response.status_code == 401:
            raise OpenClawError(
                "Authentication failed - check OPENCLAW_GATEWAY_TOKEN",
                error_type="auth_error",
                status_code=401,
            )
        elif response.status_code == 404:
            tool = payload.get("tool", "unknown")
            raise OpenClawError(
                f"Tool '{tool}' not found or blocked by gateway policy",
                error_type="tool_not_found",
                status_code=404,
            )
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise OpenClawError(
                f"Rate limited by gateway (retry after {retry_after}s)",
                error_type="rate_limited",
                status_code=429,
            )
        elif response.status_code >= 400:
            error_msg = data.get("error", {}).get("message", response.text[:200])
            raise OpenClawError(
                f"Gateway error ({response.status_code}): {error_msg}",
                error_type=data.get("error", {}).get("type", "unknown"),
                status_code=response.status_code,
            )

        return data
