"""
Claude CLI Client for K12 Self-Analysis (Phase 2).

Wraps Claude Code CLI as a subprocess for code analysis.
Falls back to OpenClaw exec if Claude installed for deployadmin only.

Rate limited: max 3 calls per 24 hours.
Graceful: if CLI not available, returns None (caller falls back to local model).

Pattern: follows OpenClaw client (agent_core/effector/openclaw_client.py).
"""

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Rate limit: max calls per 24h
MAX_CALLS_PER_DAY = 3


class ClaudeCLIClient:
    """Subprocess wrapper for Claude Code CLI."""

    def __init__(
        self,
        claude_bin: str = "claude",
        timeout_s: float = 120,
        max_tokens: int = 4000,
    ):
        self._claude_bin = claude_bin
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._openclaw_client = None

        # Rate limiting
        self._call_timestamps: list = []

    def set_openclaw_client(self, client):
        """Set OpenClaw client for fallback exec invocation."""
        self._openclaw_client = client

    def is_available(self) -> bool:
        """Check if Claude CLI is installed and accessible."""
        # Direct check
        if shutil.which(self._claude_bin):
            return True

        # OpenClaw exec fallback: check if deployadmin has claude
        if self._openclaw_client:
            try:
                result = self._openclaw_client.invoke_tool(
                    "exec", {"command": f"which {self._claude_bin}"}
                )
                if result and result.get("success"):
                    return True
            except Exception:
                pass

        return False

    def analyze(self, prompt: str) -> Optional[str]:
        """
        Send analysis prompt to Claude CLI.

        Returns response text or None if unavailable/rate-limited.
        """
        if not self._check_rate_limit():
            logger.info("[ClaudeCLI] Rate limit reached (%d/%d per 24h)",
                        len(self._call_timestamps), MAX_CALLS_PER_DAY)
            return None

        # Try direct subprocess first
        result = self._invoke_direct(prompt)
        if result is not None:
            self._record_call()
            return result

        # Fallback: OpenClaw exec
        if self._openclaw_client:
            result = self._invoke_via_openclaw(prompt)
            if result is not None:
                self._record_call()
                return result

        return None

    def _invoke_direct(self, prompt: str) -> Optional[str]:
        """Execute Claude CLI directly as subprocess."""
        if not shutil.which(self._claude_bin):
            return None

        try:
            cmd = [
                self._claude_bin,
                "-p", prompt,
                "--output-format", "text",
            ]
            if self._max_tokens:
                cmd.extend(["--max-tokens", str(self._max_tokens)])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )

            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

            if result.stderr:
                logger.warning("[ClaudeCLI] stderr: %s", result.stderr[:200])

            return None
        except subprocess.TimeoutExpired:
            logger.warning("[ClaudeCLI] Timeout after %ds", self._timeout_s)
            return None
        except Exception as e:
            logger.warning("[ClaudeCLI] Direct invoke failed: %s", e)
            return None

    def _invoke_via_openclaw(self, prompt: str) -> Optional[str]:
        """Execute Claude CLI via OpenClaw exec tool."""
        if not self._openclaw_client:
            return None

        try:
            # Escape prompt for shell
            escaped = prompt.replace("'", "'\\''")
            command = (
                f"{self._claude_bin} -p '{escaped}' "
                f"--output-format text"
            )
            if self._max_tokens:
                command += f" --max-tokens {self._max_tokens}"

            result = self._openclaw_client.invoke_tool(
                "exec", {"command": command}
            )

            if result and result.get("success"):
                output = result.get("output", result.get("stdout", ""))
                if output and output.strip():
                    return output.strip()

            return None
        except Exception as e:
            logger.warning("[ClaudeCLI] OpenClaw invoke failed: %s", e)
            return None

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limit."""
        cutoff = time.time() - 86400  # 24 hours
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]
        return len(self._call_timestamps) < MAX_CALLS_PER_DAY

    def _record_call(self) -> None:
        """Record successful call timestamp."""
        self._call_timestamps.append(time.time())

    def get_stats(self) -> dict:
        """Get client stats."""
        cutoff = time.time() - 86400
        recent = [t for t in self._call_timestamps if t > cutoff]
        return {
            "available": self.is_available(),
            "calls_24h": len(recent),
            "max_calls_24h": MAX_CALLS_PER_DAY,
            "remaining": MAX_CALLS_PER_DAY - len(recent),
        }
