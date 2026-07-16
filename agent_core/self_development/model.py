"""Data model + tuning constants for the self-development board."""

from dataclasses import dataclass, field
from typing import Dict, List

# --- Loop / "stuck" thresholds (module constants, easy to tune) ---
# A theme is "stuck" when Maria keeps asking for it but nothing ever happens.
STUCK_MIN_ASKED = 10        # N: proposed at least this many times
STUCK_MIN_DAYS = 14.0       # M: first proposed at least this long ago

# --- Embedding seed-set clustering (used from INC-4 onward) ---
# Cosine threshold for assigning a new title to a known seed theme.
# Measured on the live nomic-embed-text model: 0.62 collapses everything into
# one blob; 0.82-0.85 yields the desired 6-8 distinct themes.
THEME_SIM_THRESHOLD = 0.82

# --- Realized signal: which bulletin close-reasons count as "really done" ---
# Verified as actually emitted in the codebase (action_executor, telegram cmds).
WHITELIST_REALIZED_REASONS = frozenset({
    "material_fetched",
    "learned_material",
    "operator_acknowledged",
})
# Reasons that explicitly do NOT count as realized (anti false-comfort).
NON_REALIZED_REASONS = frozenset({
    "stale_timeout",
    "skip_measurement_artifact",
    "task_expired",
    "task_blocked_cleanup",
    "suggestion_expired",
})

# realized_join_status values
JOIN_LIVE = "live"                  # at least one theme has a real close
JOIN_BRIDGE_BROKEN = "bridge_broken"  # zero real closes anywhere (current truth)
JOIN_NOT_COMPUTED = "not_computed"  # INC-1: realized join not wired yet


@dataclass(frozen=True)
class SelfDevTheme:
    """One curated self-development theme (a cluster of meta-goal variants).

    asked_count counts UNIQUE goal_ids (after later-wins dedup), not raw rows --
    counting rows would inflate by ~24% (status transitions append extra lines).
    oldest_ts is the first time Maria raised this theme ("od kiedy prosi").
    """

    theme_id: str
    display_title: str
    asked_count: int
    oldest_ts: float
    newest_ts: float
    days_old: float
    norm_aliases: List[str] = field(default_factory=list)
    status_breakdown: Dict[str, int] = field(default_factory=dict)
    realized: bool = False
    realized_evidence: List[str] = field(default_factory=list)
    stuck: bool = False
    realized_join_status: str = JOIN_NOT_COMPUTED
