"""
Codex CLI Client - ChatGPT as encyclopedia for M.A.R.I.A.

Wraps OpenAI Codex CLI as a subprocess for interactive knowledge exchange.
Uses ChatGPT Plus subscription ($20/month) via OAuth - no API key needed.

Every interaction is logged to meta_data/codex_interactions.jsonl
for analysis, predictions, and trend detection.

Rate limited: max 10 calls per hour.
Graceful: if CLI not available, returns None (caller falls back to NIM/Ollama).

Pattern: follows claude_cli_client.py (subprocess wrapper, rate-limited, fallback).
"""

import json
import logging
import os
import shutil
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from agent_core.llm.master_prompt import build_context_brief
    _CONTEXT_BRIEF = build_context_brief()
except ImportError:
    _CONTEXT_BRIEF = ""

logger = logging.getLogger(__name__)

# Rate limit: max calls per hour
MAX_CALLS_PER_HOUR = 10
RATE_WINDOW_SEC = 3600

# Default log path
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_LOG_PATH = _META_DIR / "codex_interactions.jsonl"


class CodexClient:
    """
    Subprocess wrapper for OpenAI Codex CLI (ChatGPT backend).

    Provides one-shot knowledge queries with full JSONL logging.
    Authentication via OAuth (ChatGPT Plus subscription).
    """

    def __init__(
        self,
        codex_bin: str = os.environ.get(
            "CODEX_BIN", "/home/maria/.npm-global/bin/codex"
        ),
        timeout_s: float = 120,
        log_path: Optional[Path] = None,
    ):
        self._codex_bin = codex_bin
        self._timeout_s = timeout_s
        self._log_path = Path(log_path or _DEFAULT_LOG_PATH)

        # Rate limiting (sliding window)
        self._call_timestamps: deque = deque()

        # Stats
        self._total_calls = 0
        self._total_errors = 0
        self._total_tokens_approx = 0

    def is_available(self) -> bool:
        """Check if Codex CLI is installed and accessible."""
        return shutil.which(self._codex_bin) is not None

    def ask(
        self,
        prompt: str,
        source: str = "unknown",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Send a knowledge query to ChatGPT via Codex CLI.

        Args:
            prompt: Question or request for ChatGPT
            source: Which module is asking (creative, planner, k12, etc.)
            context: Optional metadata for logging

        Returns:
            Response text or None if unavailable/rate-limited/error.
        """
        if not self.is_available():
            logger.debug("[Codex] CLI not available")
            return None

        if not self._check_rate_limit():
            logger.info(
                "[Codex] Rate limit reached (%d/%d per hour)",
                len(self._call_timestamps), MAX_CALLS_PER_HOUR,
            )
            self._log_interaction(
                prompt=prompt, response=None, source=source,
                context=context, success=False, error="rate_limited",
                duration_ms=0,
            )
            return None

        start = time.time()
        result = self._invoke(prompt)
        duration_ms = (time.time() - start) * 1000

        self._total_calls += 1

        if result is not None:
            self._record_call()
            self._total_tokens_approx += len(result) // 4  # rough estimate
            self._log_interaction(
                prompt=prompt, response=result, source=source,
                context=context, success=True, error=None,
                duration_ms=duration_ms,
            )
        else:
            self._total_errors += 1
            self._log_interaction(
                prompt=prompt, response=None, source=source,
                context=context, success=False, error="invoke_failed",
                duration_ms=duration_ms,
            )

        return result

    def _invoke(self, prompt: str) -> Optional[str]:
        """Execute Codex CLI as subprocess (non-interactive exec mode)."""
        try:
            # Prepend context brief so Codex knows it's helping M.A.R.I.A.
            full_prompt = f"{_CONTEXT_BRIEF}\n\n{prompt}" if _CONTEXT_BRIEF else prompt
            out_file = self._log_path.parent / ".codex_last_response.txt"
            cmd = [
                self._codex_bin,
                "exec",                   # non-interactive mode
                "--skip-git-repo-check",  # Maria's context, not a repo question
                "-o", str(out_file),      # write response to file
                full_prompt,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                env=None,  # inherit environment (OAuth tokens)
            )

            # Read response from output file (cleaner than parsing stdout)
            if out_file.exists():
                response = out_file.read_text(encoding="utf-8").strip()
                if response:
                    return response

            # Fallback: parse stdout (last line is the response)
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().splitlines()
                # Skip metadata lines, get actual response
                return lines[-1].strip() if lines else None

            if result.stderr:
                logger.warning("[Codex] stderr: %s", result.stderr[:300])

            return None
        except subprocess.TimeoutExpired:
            logger.warning("[Codex] Timeout after %ds", self._timeout_s)
            return None
        except Exception as e:
            logger.warning("[Codex] Invoke failed: %s", e)
            return None

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limit (sliding window)."""
        now = time.time()
        cutoff = now - RATE_WINDOW_SEC
        while self._call_timestamps and self._call_timestamps[0] < cutoff:
            self._call_timestamps.popleft()
        return len(self._call_timestamps) < MAX_CALLS_PER_HOUR

    def _record_call(self) -> None:
        """Record successful call timestamp."""
        self._call_timestamps.append(time.time())

    def _log_interaction(
        self,
        prompt: str,
        response: Optional[str],
        source: str,
        context: Optional[Dict],
        success: bool,
        error: Optional[str],
        duration_ms: float,
    ) -> None:
        """
        Log every interaction to JSONL for analysis and predictions.

        Each record contains full context for trend detection.
        """
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

            record = {
                "timestamp": time.time(),
                "source": source,
                "prompt_summary": prompt[:200],
                "prompt_length": len(prompt),
                "response_summary": (response[:300] if response else None),
                "response_length": (len(response) if response else 0),
                "success": success,
                "error": error,
                "duration_ms": round(duration_ms, 1),
                "calls_this_hour": len(self._call_timestamps),
                "total_calls": self._total_calls,
            }
            if context:
                record["context"] = {
                    k: str(v)[:100] for k, v in context.items()
                }

            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        except IOError as e:
            logger.debug(f"[Codex] Log write failed: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics for diagnostics."""
        now = time.time()
        cutoff = now - RATE_WINDOW_SEC
        while self._call_timestamps and self._call_timestamps[0] < cutoff:
            self._call_timestamps.popleft()

        return {
            "available": self.is_available(),
            "calls_this_hour": len(self._call_timestamps),
            "max_calls_per_hour": MAX_CALLS_PER_HOUR,
            "remaining": MAX_CALLS_PER_HOUR - len(self._call_timestamps),
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
            "total_tokens_approx": self._total_tokens_approx,
            "log_path": str(self._log_path),
        }

    def get_recent_interactions(self, limit: int = 10) -> List[Dict]:
        """Read recent interactions from log for analysis."""
        if not self._log_path.exists():
            return []
        try:
            records = []
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            return records[-limit:]
        except IOError:
            return []
