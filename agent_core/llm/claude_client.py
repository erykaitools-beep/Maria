"""
Claude Code CLI Client - Claude as code analyst for M.A.R.I.A.

Wraps Claude Code CLI as subprocess for code analysis and review tasks.
Uses operator's Claude subscription - strict rate limiting required.

Rate limited: max 3 calls per hour (configurable via CLAUDE_MAX_CALLS_PER_HOUR env).
Every interaction logged to meta_data/claude_interactions.jsonl.

Pattern: follows codex_client.py (subprocess wrapper, rate-limited, logged).
"""

import json
import logging
import os
import re
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

# Read-only tool set for the backend. Restores /claude's ability to actually
# read+analyse code (the 2026-06-12 audit's bare --tools "" left it tool-less, so
# it confabulated answers it could not verify -- confirmed live 2026-06-22:
# tool-less Claude invented a wrong heading; read-only Claude read the real one).
# CRITICAL: keep this READ-ONLY (Read/Grep/Glob) -- no Bash/Edit/Write means no
# exec/write on the live repo, preserving the audit's intent. Adding Bash/Write/
# Edit here reopens that hole. Env-overridable (operator owns .env).
_ALLOWED_TOOLS = os.environ.get("CLAUDE_ALLOWED_TOOLS", "Read,Grep,Glob")

# Markers of a hallucinated tool call emitted as plain TEXT (see
# looks_like_tool_hallucination). Even with read-only tools, a request the model
# cannot fulfil (write/exec/send) makes it print one of these as text instead of
# acting. The CLI's format varies by version -- 2026-06-22 it emits "<tool_use>"
# (older logs showed "<tool_call>"), so list every variant. ("<parameter name="
# dropped -- too generic, it appears in legitimate code/markup discussion.)
_TOOL_CALL_MARKERS = (
    "<tool_use", "<tool_call", "<tool_calls", "<tool_name", "<tool_input",
    "<invoke", "<function_call", '"type":"tool_use"', '"type": "tool_use"',
)


def looks_like_tool_hallucination(text: Optional[str]) -> bool:
    """True when CLI output is DOMINATED by hallucinated tool-call syntax.

    The /claude backend runs ``claude --tools ""`` (no tools at all, per the
    2026-06-12 security audit). Asked to DO something -- read a file, send to
    Telegram -- the model emits ``<tool_call>{...}</tool_call>`` pseudo-syntax as
    plain TEXT. That text is non-empty and the process exits 0, so it used to be
    returned as a 'successful' result: a false COMPLETED that shipped gibberish
    to the operator (the 2026-06-22 morning failure). Detect it so the caller
    treats it as no-result and answers honestly instead.

    Tuned to avoid false positives: /claude IS a text analyst that may quote a
    ``<tool_call>`` tag while discussing code. We strip xml-ish tags and JSON
    blocks (iteratively, innermost-first, so a NESTED ``{"arguments": {...}}`` is
    fully removed -- a flat regex cannot), then flag ONLY when the surviving prose
    is BOTH short in absolute terms (<200 chars) AND a small fraction (<1/3) of
    the output -- i.e. tool-call syntax dominates. A substantial analysis, or a
    short answer that merely quotes a tag, survives.
    """
    if not text:
        return False
    low = text.lower()
    if not any(m in low for m in _TOOL_CALL_MARKERS):
        return False
    stripped = re.sub(r"<[^>]+>", " ", text)             # drop xml-ish tags
    prev = None
    while prev != stripped:                              # remove {json} innermost-first
        prev = stripped
        stripped = re.sub(r"\{[^{}]*\}", " ", stripped)
    prose = re.sub(r"\s+", " ", stripped).strip()
    total = len(text.strip())
    return len(prose) < 200 and total > 0 and len(prose) * 3 < total


# Rate limit: strict to avoid overuse
MAX_CALLS_PER_HOUR = int(os.environ.get("CLAUDE_MAX_CALLS_PER_HOUR", "3"))
RATE_WINDOW_SEC = 3600

# Daily cap as safety net
MAX_CALLS_PER_DAY = int(os.environ.get("CLAUDE_MAX_CALLS_PER_DAY", "15"))

# Default paths
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_LOG_PATH = _META_DIR / "claude_interactions.jsonl"


class ClaudeClient:
    """
    Subprocess wrapper for Claude Code CLI.

    Strict rate limiting (3/h, 15/day default) to protect operator's subscription.
    Use for high-value tasks only: code analysis, review, complex reasoning.
    For simple questions use Codex or NIM instead.
    """

    def __init__(
        self,
        claude_bin: str = os.environ.get(
            "CLAUDE_BIN", shutil.which("claude") or "claude"
        ),
        timeout_s: float = 180,
        log_path: Optional[Path] = None,
        max_per_hour: int = MAX_CALLS_PER_HOUR,
        max_per_day: int = MAX_CALLS_PER_DAY,
    ):
        self._claude_bin = claude_bin
        self._timeout_s = timeout_s
        self._log_path = Path(log_path or _DEFAULT_LOG_PATH)
        self._max_per_hour = max_per_hour
        self._max_per_day = max_per_day

        # Rate limiting (sliding windows)
        self._hour_timestamps: deque = deque()
        self._day_timestamps: deque = deque()

        # Stats
        self._total_calls = 0
        self._total_errors = 0

    def is_available(self) -> bool:
        """Check if Claude CLI is installed and accessible."""
        return shutil.which(self._claude_bin) is not None

    def ask(
        self,
        prompt: str,
        source: str = "unknown",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Send a task to Claude Code CLI.

        Args:
            prompt: Task description or question
            source: Which module is asking (telegram, planner, etc.)
            context: Optional metadata for logging

        Returns:
            Response text or None if unavailable/rate-limited/error.
        """
        if not self.is_available():
            logger.debug("[Claude] CLI not available")
            return None

        blocked, reason = self._check_rate_limit()
        if blocked:
            logger.info("[Claude] Rate limit: %s", reason)
            self._log_interaction(
                prompt=prompt, response=None, source=source,
                context=context, success=False, error=f"rate_limited: {reason}",
                duration_ms=0,
            )
            return None

        start = time.time()
        result = self._invoke(prompt)
        duration_ms = (time.time() - start) * 1000

        self._total_calls += 1
        # The subprocess ran (we passed the availability + rate-limit gates), so
        # it spent a real call against the operator's subscription regardless of
        # whether the output was usable -- count it toward the limit. A None
        # result (timeout, error, or a discarded tool-call hallucination) still
        # means a real CLI call happened (ban-risk safety, 2026-06-22 review).
        self._record_call()

        if result is not None:
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
        """Execute Claude CLI as subprocess."""
        try:
            # Prepend context brief so Claude knows it's helping M.A.R.I.A.
            full_prompt = f"{_CONTEXT_BRIEF}\n\n{prompt}" if _CONTEXT_BRIEF else prompt
            # Audyt 2026-06-12 wylaczyl WSZYSTKIE narzedzia (--tools "") bo
            # --dangerously-skip-permissions na zywym repo dawal kazdemu z
            # dostepem do .ask() (webui za PIN-em, telegram) exec/write. Ale to
            # zostawilo /claude SLEPYM -- nie umial przeczytac pliku, wiec
            # konfabulowal (2026-06-22). READ-ONLY (Read/Grep/Glob) przywraca
            # analize kodu BEZ exec/write -- intencja audytu zachowana. NIE
            # dawac tu Bash/Edit/Write (otwiera dziure). Brak
            # --dangerously-skip-permissions: read-only auto-allowuje sie w -p.
            cmd = [
                self._claude_bin,
                "--tools", _ALLOWED_TOOLS,
                "-p", full_prompt,
                "--output-format", "text",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                cwd=str(Path(__file__).resolve().parents[2]),  # project root
            )

            if result.returncode == 0 and result.stdout.strip():
                out = result.stdout.strip()
                if looks_like_tool_hallucination(out):
                    # Tool-less backend tried to "act" and emitted pseudo
                    # tool-calls as text. Not a real answer -> treat as no-result
                    # so the caller stays honest instead of shipping gibberish.
                    logger.warning(
                        "[Claude] Output looks like hallucinated tool-calls "
                        "(tool-less backend cannot act); treating as no-result."
                    )
                    return None
                return out

            if result.stderr:
                logger.warning("[Claude] stderr: %s", result.stderr[:300])

            return None
        except subprocess.TimeoutExpired:
            logger.warning("[Claude] Timeout after %ds", self._timeout_s)
            return None
        except Exception as e:
            logger.warning("[Claude] Invoke failed: %s", e)
            return None

    def _check_rate_limit(self) -> tuple:
        """Check hourly and daily limits. Returns (blocked: bool, reason: str)."""
        now = time.time()

        # Clean hourly window
        cutoff_h = now - RATE_WINDOW_SEC
        while self._hour_timestamps and self._hour_timestamps[0] < cutoff_h:
            self._hour_timestamps.popleft()

        if len(self._hour_timestamps) >= self._max_per_hour:
            return True, f"{len(self._hour_timestamps)}/{self._max_per_hour} per hour"

        # Clean daily window
        cutoff_d = now - 86400
        while self._day_timestamps and self._day_timestamps[0] < cutoff_d:
            self._day_timestamps.popleft()

        if len(self._day_timestamps) >= self._max_per_day:
            return True, f"{len(self._day_timestamps)}/{self._max_per_day} per day"

        return False, ""

    def _record_call(self) -> None:
        """Record successful call timestamp."""
        now = time.time()
        self._hour_timestamps.append(now)
        self._day_timestamps.append(now)

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
        """Log every interaction to JSONL."""
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
                "calls_this_hour": len(self._hour_timestamps),
                "calls_today": len(self._day_timestamps),
                "total_calls": self._total_calls,
            }
            if context:
                record["context"] = {
                    k: str(v)[:100] for k, v in context.items()
                }

            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        except IOError as e:
            logger.debug(f"[Claude] Log write failed: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        now = time.time()
        # Clean windows
        cutoff_h = now - RATE_WINDOW_SEC
        while self._hour_timestamps and self._hour_timestamps[0] < cutoff_h:
            self._hour_timestamps.popleft()
        cutoff_d = now - 86400
        while self._day_timestamps and self._day_timestamps[0] < cutoff_d:
            self._day_timestamps.popleft()

        return {
            "available": self.is_available(),
            "calls_this_hour": len(self._hour_timestamps),
            "max_per_hour": self._max_per_hour,
            "remaining_hour": self._max_per_hour - len(self._hour_timestamps),
            "calls_today": len(self._day_timestamps),
            "max_per_day": self._max_per_day,
            "remaining_day": self._max_per_day - len(self._day_timestamps),
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
        }
