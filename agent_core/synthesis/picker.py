"""Autonomous synthesis topic picker (Etap 2b, cegla E).

Pure policy, zero LLM, zero side effects in ``decide_synthesis`` -- it only
answers "should Maria synthesize now, and on what topic". The homeostasis
layer owns the clock, the learning-window gate, the NIM/sandbox wiring and
the persisted state file; this module is the brain that chooses.

Selection rule: among topics with cross-source material (>= MIN_DISTINCT_
SOURCES, supplied by ``eligible_topics``), prefer the LEAST-recently
synthesized -- never-touched topics first, then oldest, ties broken by
source count (richer first). This spreads synthesis across the corpus
instead of hammering the single strongest tag every day.

The cooldown is persisted (state file), so a restart cannot turn "once a
day" into "once per restart" -- the exact bug class that bit the NREM
throttle (audyt 2026-06-12). Observe mode discards everything, so the only
cost of a stray run is ~3 min of NIM; persistence keeps even that bounded.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Once per day. The homeostasis phase may CHECK every ~10 min, but the
# cooldown is what actually rate-limits real cycles.
DEFAULT_COOLDOWN_SEC = 24 * 3600


def decide_synthesis(
    eligible: List[Dict[str, Any]],
    state: Dict[str, Any],
    now_ts: float,
    in_window: bool,
    cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
) -> Dict[str, Any]:
    """Decide whether to run an autonomous synthesis, and on what topic.

    Args:
        eligible: output of ``synthesis.eligible_topics`` --
            ``[{"topic": str, "sources": int}, ...]`` strongest first.
        state: picker state (see ``load_state``): ``last_run_ts`` + a
            ``history`` map of ``topic -> last_synthesized_ts``.
        now_ts: current epoch seconds.
        in_window: True if we are inside a learning window right now.
        cooldown_sec: minimum seconds between autonomous cycles.

    Returns ``{"action": "synthesize", "topic", "sources"}`` or
    ``{"action": "skip", "reason"}``. Never raises on shape; treats a
    malformed state as empty.
    """
    if not in_window:
        return {"action": "skip", "reason": "outside_window"}

    last_run = _as_float(state.get("last_run_ts"))
    if now_ts - last_run < cooldown_sec:
        return {"action": "skip", "reason": "cooldown"}

    if not eligible:
        return {"action": "skip", "reason": "no_topics"}

    history = state.get("history") if isinstance(state.get("history"), dict) else {}

    # Least-recently-synthesized first (never-touched = ts 0.0), ties to
    # the richer topic (more distinct sources), then alphabetical for a
    # stable, test-reproducible order.
    def sort_key(entry: Dict[str, Any]):
        topic = entry.get("topic", "")
        last = _as_float(history.get(topic))
        return (last, -int(entry.get("sources", 0)), topic)

    chosen = min(eligible, key=sort_key)
    return {
        "action": "synthesize",
        "topic": chosen.get("topic", ""),
        "sources": int(chosen.get("sources", 0)),
    }


def record_pick(state: Dict[str, Any], topic: str, now_ts: float) -> Dict[str, Any]:
    """Stamp a pick into state: consume the cooldown and remember the topic.

    Called when a cycle STARTS (not when it finishes) so a failing cycle
    still consumes the day's budget -- we want "once a day" even when NIM
    is flaky, not a retry storm.
    """
    history = state.get("history")
    if not isinstance(history, dict):
        history = {}
    history[topic] = now_ts
    return {"last_run_ts": now_ts, "history": history}


def load_state(path: Path) -> Dict[str, Any]:
    """Load picker state; empty (and harmless) on missing/corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"last_run_ts": 0.0, "history": {}}


def save_state(path: Path, state: Dict[str, Any]) -> None:
    """Persist picker state atomically (tmp + replace)."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        tmp.replace(path)
    except OSError as e:
        logger.warning("[SynthPicker] state persist failed: %s", e)


def _as_float(value: Optional[Any]) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
