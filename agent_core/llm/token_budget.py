"""
Token Budget Manager - NIM API token tracking and budget control.

Tracks token usage per day/month and decides whether Maria
can afford to use NIM API or should fall back to Ollama.

Persistence: meta_data/nim_token_usage.json
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, date
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class TokenBudget:
    """
    Manages NIM API token budget.

    Maria knows how many tokens she has used and how many remain.
    When budget is low, she automatically switches to Ollama.

    Usage:
        budget = TokenBudget(daily_limit=100_000)
        if budget.can_use_nim():
            # use NIM API
            budget.record_usage(prompt_tokens=500, completion_tokens=200)
        else:
            # fall back to Ollama
    """

    # RPM (requests per minute) limit - primary gate
    RPM_LIMIT = 40
    RPM_WINDOW_SEC = 60.0

    # Budget status thresholds (for token observability)
    LOW_THRESHOLD = 0.2   # 20% remaining = LOW
    WARN_THRESHOLD = 0.5  # 50% remaining = WARN (for logging)

    def __init__(
        self,
        daily_limit: int = 100_000,
        monthly_limit: int = 2_000_000,
        budget_file: Optional[str] = None,
    ):
        """
        Initialize token budget manager.

        Args:
            daily_limit: Maximum tokens per day
            monthly_limit: Maximum tokens per month
            budget_file: Path to persistence file
                         (default: meta_data/nim_token_usage.json)
        """
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit

        if budget_file is None:
            # Default path relative to project root
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            budget_file = os.path.join(
                project_root, "meta_data", "nim_token_usage.json"
            )
        self.budget_file = budget_file

        self._lock = threading.Lock()
        self._usage: Dict[str, Dict[str, Any]] = {}
        self._request_timestamps: List[float] = []
        self._load()

    # -------------------------------------------------
    # USAGE RECORDING
    # -------------------------------------------------

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "",
    ) -> None:
        """
        Record token usage from a NIM API call.

        Args:
            prompt_tokens: Tokens in the prompt
            completion_tokens: Tokens in the response
            model: Model name (for logging)
        """
        today = self._today_key()

        with self._lock:
            if today not in self._usage:
                self._usage[today] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                }

            entry = self._usage[today]
            entry["prompt_tokens"] += prompt_tokens
            entry["completion_tokens"] += completion_tokens
            entry["total_tokens"] += prompt_tokens + completion_tokens
            entry["calls"] += 1

            self._save()

        total = prompt_tokens + completion_tokens
        remaining = self.get_remaining_today()
        logger.debug(
            f"NIM tokens: +{total} (remaining today: {remaining:,})"
        )

        # Warn if budget is getting low
        if self.get_budget_status() == "LOW":
            logger.warning(
                f"NIM token budget LOW! "
                f"Remaining today: {remaining:,}/{self.daily_limit:,}"
            )

    def record_request(self) -> None:
        """
        Record a NIM API request timestamp for RPM tracking.

        Call this alongside record_usage() after each NIM call.
        """
        now = time.time()
        with self._lock:
            self._request_timestamps.append(now)
            # Prune old timestamps (older than RPM window)
            cutoff = now - self.RPM_WINDOW_SEC
            self._request_timestamps = [
                ts for ts in self._request_timestamps if ts > cutoff
            ]

    def _get_current_rpm(self) -> int:
        """Get number of requests in the current RPM window."""
        now = time.time()
        cutoff = now - self.RPM_WINDOW_SEC
        with self._lock:
            return sum(1 for ts in self._request_timestamps if ts > cutoff)

    # -------------------------------------------------
    # USAGE QUERIES
    # -------------------------------------------------

    def get_today_usage(self) -> Dict[str, int]:
        """
        Get today's token usage.

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens, calls
        """
        today = self._today_key()
        with self._lock:
            entry = self._usage.get(today, {})
        return {
            "prompt_tokens": entry.get("prompt_tokens", 0),
            "completion_tokens": entry.get("completion_tokens", 0),
            "total_tokens": entry.get("total_tokens", 0),
            "calls": entry.get("calls", 0),
        }

    def get_month_usage(self) -> Dict[str, int]:
        """
        Get current month's token usage.

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens, calls
        """
        month_prefix = datetime.now().strftime("%Y-%m")
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

        with self._lock:
            for day_key, entry in self._usage.items():
                if day_key.startswith(month_prefix):
                    totals["prompt_tokens"] += entry.get("prompt_tokens", 0)
                    totals["completion_tokens"] += entry.get(
                        "completion_tokens", 0
                    )
                    totals["total_tokens"] += entry.get("total_tokens", 0)
                    totals["calls"] += entry.get("calls", 0)

        return totals

    # -------------------------------------------------
    # BUDGET DECISIONS
    # -------------------------------------------------

    def get_remaining_today(self) -> int:
        """
        Get remaining tokens for today.

        Returns:
            Number of tokens remaining (can be negative if over-budget)
        """
        used = self.get_today_usage()["total_tokens"]
        return self.daily_limit - used

    def get_remaining_month(self) -> int:
        """
        Get remaining tokens for this month.

        Returns:
            Number of tokens remaining (can be negative if over-budget)
        """
        used = self.get_month_usage()["total_tokens"]
        return self.monthly_limit - used

    def can_use_nim(self) -> bool:
        """
        Check if RPM limit allows NIM API usage.

        Primary gate: RPM sliding window (40 req/min).
        Token tracking remains for observability only.

        Returns:
            True if RPM limit not exceeded
        """
        current_rpm = self._get_current_rpm()
        if current_rpm >= self.RPM_LIMIT:
            logger.debug(
                f"NIM RPM limit reached: {current_rpm}/{self.RPM_LIMIT}"
            )
            return False
        return True

    def get_budget_status(self) -> str:
        """
        Get overall budget status based on RPM.

        Returns:
            "OK" - RPM healthy (<80% of limit)
            "LOW" - RPM getting high (>=80% of limit)
            "DEPLETED" - RPM limit reached
        """
        if not self.can_use_nim():
            return "DEPLETED"

        current_rpm = self._get_current_rpm()
        rpm_ratio = current_rpm / max(self.RPM_LIMIT, 1)

        if rpm_ratio >= 0.8:
            return "LOW"

        return "OK"

    # -------------------------------------------------
    # REPORTING (for Maria's self-awareness)
    # -------------------------------------------------

    def get_status_text(self) -> str:
        """
        Get human-readable budget status for Maria.

        Returns:
            Polish text describing current token budget state
        """
        today = self.get_today_usage()
        month = self.get_month_usage()
        remaining_today = self.get_remaining_today()
        remaining_month = self.get_remaining_month()
        status = self.get_budget_status()

        today_pct = 0
        if self.daily_limit > 0:
            today_pct = (today["total_tokens"] / self.daily_limit) * 100

        month_pct = 0
        if self.monthly_limit > 0:
            month_pct = (month["total_tokens"] / self.monthly_limit) * 100

        current_rpm = self._get_current_rpm()

        lines = []
        lines.append(
            f"NIM RPM: {current_rpm}/{self.RPM_LIMIT} "
            f"(limit na minute)."
        )
        lines.append(
            f"Dzis zuzylam {today['total_tokens']:,} tokenow NIM "
            f"({today_pct:.0f}%). "
            f"Wywolan dzis: {today['calls']}."
        )
        lines.append(
            f"W tym miesiacu: {month['total_tokens']:,} tokenow "
            f"({month_pct:.0f}%)."
        )

        if status == "DEPLETED":
            lines.append("RPM limit osiagniety - korzystam z Ollama.")
        elif status == "LOW":
            lines.append("RPM wysoki - oszczedzam requesty.")
        else:
            lines.append("RPM OK - moge korzystac z NIM.")

        return " ".join(lines)

    def get_status_dict(self) -> Dict[str, Any]:
        """
        Get budget status as dictionary (for API/Web UI).

        Returns:
            Complete budget status
        """
        today = self.get_today_usage()
        month = self.get_month_usage()
        current_rpm = self._get_current_rpm()
        return {
            "status": self.get_budget_status(),
            "can_use_nim": self.can_use_nim(),
            "rpm": {
                "current": current_rpm,
                "limit": self.RPM_LIMIT,
                "headroom": max(0, self.RPM_LIMIT - current_rpm),
            },
            "daily": {
                "used": today["total_tokens"],
                "limit": self.daily_limit,
                "remaining": max(0, self.get_remaining_today()),
                "calls": today["calls"],
            },
            "monthly": {
                "used": month["total_tokens"],
                "limit": self.monthly_limit,
                "remaining": max(0, self.get_remaining_month()),
                "calls": month["calls"],
            },
        }

    # -------------------------------------------------
    # PERSISTENCE
    # -------------------------------------------------

    def _save(self) -> None:
        """Save usage data to JSON file."""
        data = {
            "daily_limit": self.daily_limit,
            "monthly_limit": self.monthly_limit,
            "usage": self._usage,
        }
        try:
            os.makedirs(os.path.dirname(self.budget_file), exist_ok=True)
            with open(self.budget_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save token budget: {e}")

    def _load(self) -> None:
        """Load usage data from JSON file."""
        try:
            if os.path.exists(self.budget_file):
                with open(self.budget_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._usage = data.get("usage", {})
                # Update limits from file only if not explicitly set
                # (env vars take priority)
                logger.debug(
                    f"Token budget loaded: {len(self._usage)} days of history"
                )
            else:
                self._usage = {}
                logger.debug("Token budget: no history file, starting fresh")
        except Exception as e:
            logger.error(f"Failed to load token budget: {e}")
            self._usage = {}

    # -------------------------------------------------
    # HELPERS
    # -------------------------------------------------

    @staticmethod
    def _today_key() -> str:
        """Get today's date as string key."""
        return date.today().isoformat()
