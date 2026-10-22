"""K12 analysis shift: when the analyst works, and for how long.

Until now K12's periodic trigger fired every 4h round the clock, so the heaviest
reasoning call in the system landed at arbitrary moments -- including inside the
09:00-18:59 learning window, where it competes for `_heavy_lock` and for the
thermal envelope that already blocked 87 of 132 plans.

This concentrates the periodic analysis into one evening shift and caps how much
wall-clock it may consume per day. Two rules matter:

1. The budget is a CEILING, not a quota. A quiet evening may finish in fifteen
   minutes; nothing here pushes the analyst to keep producing increasingly
   speculative findings just because time remains.

2. Only the PERIODIC trigger is window-gated. K9 needs_human and low-retention
   triggers are alarms, and an alarm that waits until 19:00 is not an alarm.
   Their cost is still recorded against the budget, so the ledger stays honest.

The default window (19:00-21:59 Berlin) is the gap between the learning window
closing and QUIET opening at 22:00 -- the only stretch of the day where a long
heavy inference is not taking bread out of learning's mouth.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent_core.environment.environment_model import berlin_now

logger = logging.getLogger(__name__)

# Evening gap between the learning window (09-18:59) and QUIET (22:00-06:59).
_DEFAULT_SHIFT_HOURS = "19,20,21"
# "godzine dwie dziennie" -- 90 min sits inside that, leaving headroom before
# QUIET even if the last run overruns.
_DEFAULT_BUDGET_MIN = 90.0
# Inside the shift this -- not the 4h round-the-clock interval -- is what paces
# the analyst. 60 min over a 3h window means at most three passes an evening,
# which is what "an hour or two of work a day" actually looks like. Set it too
# low and the shift becomes the recommendation flood it was built to end.
_DEFAULT_MIN_GAP_MIN = 60.0

_STATE_FILENAME = "k12_shift_state.json"


def safe_shift_status(analysis: Any) -> Optional[Dict[str, Any]]:
    """Shift status for the operator card, or None if it cannot be produced.

    Takes the analysis facade, not the shift, so that reaching for `.shift`
    happens inside the guard: passing `analysis.shift` as an argument would
    raise at the call site, before this function could catch anything.

    The K12 Telegram notification sits inside a bare `except Exception: pass`,
    so anything that raises while building the card silently costs the operator
    the whole report. A footer line must never have that much power: if the
    ledger cannot be read, the card goes out without the footer.
    """
    try:
        return analysis.shift.status()
    except Exception as e:
        logger.debug(f"[K12-shift] status unavailable for the report card: {e}")
        return None


def _parse_hours(raw: str) -> Tuple[int, ...]:
    """Parse "19,20,21" into (19, 20, 21), dropping anything not an hour."""
    hours = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h = int(part)
        except ValueError:
            continue
        if 0 <= h <= 23:
            hours.append(h)
    return tuple(sorted(set(hours)))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


class AnalysisShift:
    """Window + daily wall-clock budget for K12's periodic self-analysis."""

    def __init__(self, project_root: str = ".", meta_dir: Optional[Path] = None):
        self._state_path = (
            Path(meta_dir) if meta_dir else Path(project_root) / "meta_data"
        ) / _STATE_FILENAME
        self.hours = _parse_hours(
            os.getenv("K12_SHIFT_HOURS", _DEFAULT_SHIFT_HOURS)
        )
        self.budget_sec = max(0.0, _env_float("K12_SHIFT_BUDGET_MIN", _DEFAULT_BUDGET_MIN) * 60.0)
        self.min_gap_sec = max(0.0, _env_float("K12_SHIFT_MIN_GAP_MIN", _DEFAULT_MIN_GAP_MIN) * 60.0)
        self.enabled = (os.getenv("K12_SHIFT_ENABLED", "true") or "").strip().lower() not in (
            "0", "false", "no", "off",
        )

    # --- window ---

    def is_in_window(self, now=None) -> bool:
        """True when Berlin wall-clock sits inside the configured shift hours.

        An empty hour list means "no window restriction" -- the operator has
        explicitly opted out of concentrating the shift, not misconfigured it.
        """
        if not self.hours:
            return True
        if now is None:
            now = berlin_now()
        return now.hour in self.hours

    # --- budget ledger ---

    def _today_key(self, now=None) -> str:
        """Berlin calendar date.

        Safe as a ledger key only because the shift window never crosses
        midnight: 19-21 sits wholly inside one date. A window that spanned
        midnight would need keying by the dark stretch instead, the way the
        night exam pool had to be rekeyed on 2026-08-15 -- two unlit stretches
        of one date belong to two different nights.
        """
        if now is None:
            now = berlin_now()
        return now.strftime("%Y-%m-%d")

    def _load(self, now=None) -> Dict[str, Any]:
        key = self._today_key(now)
        blank = {"date": key, "spent_sec": 0.0, "runs": 0, "last_run_ts": 0.0}
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (IOError, OSError, json.JSONDecodeError):
            return blank
        if not isinstance(data, dict) or data.get("date") != key:
            return blank  # stale day -> fresh budget
        data.setdefault("spent_sec", 0.0)
        data.setdefault("runs", 0)
        data.setdefault("last_run_ts", 0.0)
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except (IOError, OSError) as e:
            logger.warning(f"[K12-shift] could not persist ledger: {e}")

    def spent_sec(self, now=None) -> float:
        return float(self._load(now).get("spent_sec", 0.0))

    def remaining_sec(self, now=None) -> float:
        if self.budget_sec <= 0:
            return 0.0
        return max(0.0, self.budget_sec - self.spent_sec(now))

    def record_run(self, duration_sec: float, now=None) -> None:
        """Charge a completed analysis against today's budget.

        Alarm-triggered runs are recorded too. They are not gated by the
        budget, but hiding their cost would make the ledger lie about how much
        heavy inference the day actually carried.
        """
        if duration_sec is None or duration_sec < 0:
            return
        data = self._load(now)
        data["spent_sec"] = float(data.get("spent_sec", 0.0)) + float(duration_sec)
        data["runs"] = int(data.get("runs", 0)) + 1
        data["last_run_ts"] = (now or berlin_now()).timestamp()
        self._save(data)

    # --- decision ---

    def should_run_periodic(self, now=None) -> Tuple[bool, str]:
        """Decide whether the scheduled (non-alarm) analysis may start now.

        Returns (allowed, reason) -- the reason is logged either way, so a shift
        that never runs says why instead of looking like a dead code path.
        """
        if not self.enabled:
            return False, "shift_disabled"
        if now is None:
            now = berlin_now()
        if not self.is_in_window(now):
            return False, f"outside_window(hour={now.hour},window={list(self.hours)})"

        data = self._load(now)
        if self.budget_sec > 0:
            spent = float(data.get("spent_sec", 0.0))
            if spent >= self.budget_sec:
                return False, f"budget_exhausted({spent / 60:.0f}/{self.budget_sec / 60:.0f}min)"

        last = float(data.get("last_run_ts", 0.0))
        if last and self.min_gap_sec > 0:
            gap = now.timestamp() - last
            if gap < self.min_gap_sec:
                return False, f"min_gap({gap / 60:.0f}<{self.min_gap_sec / 60:.0f}min)"

        return True, "in_shift"

    def status(self, now=None) -> Dict[str, Any]:
        """Operator-facing snapshot (for /selfstatus and the shift report)."""
        if now is None:
            now = berlin_now()
        data = self._load(now)
        allowed, reason = self.should_run_periodic(now)
        return {
            "enabled": self.enabled,
            "window_hours": list(self.hours),
            "in_window": self.is_in_window(now),
            "budget_min": round(self.budget_sec / 60.0, 1),
            "spent_min": round(float(data.get("spent_sec", 0.0)) / 60.0, 1),
            "remaining_min": round(self.remaining_sec(now) / 60.0, 1),
            "runs_today": int(data.get("runs", 0)),
            "periodic_allowed": allowed,
            "reason": reason,
        }
