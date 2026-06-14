"""StateSnapshot: dual-representation snapshot of Maria's state at time t.

Foundation for the predictive layer (B0/B0.1). A snapshot captures both
a semantic projection (free text -> embedding) and a numeric projection
(small fixed vector of system-health features), so downstream surprise
scoring can compare two snapshots along independent channels.

Decisions ratified 2026-05-09 (B0_IMPLEMENTATION_SHORTLIST rev 4):
  - Separate semantic + numeric (no concat) -- #1
  - 5 numeric features: cpu_percent, ram_gb, error_count_window,
    n_active_goals, mode_index -- #9
  - Missing feature -> skip (no crash), tracked in numeric_features_used
  - health_score = optional diagnostic, NOT a distance feature -- #9
  - In-memory only, no SSoT, no persistence -- #8
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


# Stable order of the 5 numeric features (decision #9). The order
# determines the numeric_vector() index layout and must not be reshuffled
# without a calibration reset. Missing features are skipped (omitted from
# both numeric_vector() and numeric_features_used).
NUMERIC_FEATURE_ORDER: List[str] = [
    "cpu_percent",
    "ram_gb",
    "error_count_window",
    "n_active_goals",
    "mode_index",
]

# Mode -> int mapping for numeric distance. Unknown modes -> None (skip).
_MODE_INDEX_MAP: Dict[str, int] = {
    "ACTIVE": 0,
    "ANALYTICAL": 1,
    "REDUCED": 2,
    "SLEEP": 3,
}


def _mode_index(mode: Optional[str]) -> Optional[int]:
    """Map mode name to numeric index. Unknown -> None (skip)."""
    if mode is None:
        return None
    return _MODE_INDEX_MAP.get(mode.upper())


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable snapshot of Maria's state at one moment.

    Built via :py:meth:`from_context` from a dict of inputs (homeostasis
    summary, goals count, last decision trace). Subsequent surprise
    scoring consumes :py:meth:`semantic_embedding` and
    :py:meth:`numeric_vector` to compute distances against a previous
    snapshot.

    Snapshots are NOT persisted -- the predictive layer keeps an
    in-memory rolling buffer (decision #8).
    """

    timestamp: float
    semantic_text: str
    numeric_features: Dict[str, float]
    mode: Optional[str] = None
    last_action_type: Optional[str] = None
    health_score: Optional[float] = None
    episode_id: Optional[str] = None

    @property
    def numeric_features_used(self) -> List[str]:
        """Stable-order list of feature names actually present.

        Mirrors NUMERIC_FEATURE_ORDER but omits any feature that was
        unavailable when this snapshot was built. Surfaced into the
        bulletin payload (decision #9) so downstream consumers can audit
        which channels contributed to a surprise event.
        """
        return [f for f in NUMERIC_FEATURE_ORDER if f in self.numeric_features]

    def numeric_vector(self) -> List[float]:
        """Numeric features as a stable-order vector.

        Length equals ``len(self.numeric_features_used)`` -- missing
        features are omitted, NOT zero-filled. The scorer is responsible
        for aligning vectors of two snapshots (which may have different
        feature subsets) before computing distance.
        """
        return [
            float(self.numeric_features[f])
            for f in NUMERIC_FEATURE_ORDER
            if f in self.numeric_features
        ]

    def semantic_embedding(
        self,
        embed_fn: Callable[[str], List[float]],
    ) -> List[float]:
        """Embed semantic_text via the supplied embedding function.

        The function is injected (not imported) so this module stays
        decoupled from agent_core.semantic and remains trivially
        unit-testable with a fake embedder.
        """
        return embed_fn(self.semantic_text)

    @classmethod
    def from_context(
        cls,
        timestamp: float,
        homeostasis_summary: Optional[Dict[str, Any]] = None,
        n_active_goals: Optional[int] = None,
        last_decision: Optional[Dict[str, Any]] = None,
        episode_id: Optional[str] = None,
        extra_semantic_lines: Optional[List[str]] = None,
    ) -> "StateSnapshot":
        """Build a snapshot from raw context dicts.

        All inputs are dicts/primitives -- keeping the constructor free
        of agent_core dependencies makes unit-testing trivial. The live
        adapter (later commit) is responsible for fetching the dicts
        from homeostasis / goals / decision_traces.

        Missing-feature contract (decision #9): any feature whose
        upstream input is None is silently omitted. The snapshot stays
        valid; numeric_features_used reflects what actually landed.
        """
        homeo = homeostasis_summary or {}

        numeric: Dict[str, float] = {}
        cpu = homeo.get("cpu_percent")
        if cpu is not None:
            numeric["cpu_percent"] = float(cpu)

        ram = homeo.get("ram_gb")
        if ram is not None:
            numeric["ram_gb"] = float(ram)

        err = homeo.get("error_count_window")
        if err is not None:
            numeric["error_count_window"] = float(err)

        if n_active_goals is not None:
            numeric["n_active_goals"] = float(n_active_goals)

        mode_str = homeo.get("mode")
        mi = _mode_index(mode_str)
        if mi is not None:
            numeric["mode_index"] = float(mi)

        last_action_type: Optional[str] = None
        if last_decision is not None:
            last_action_type = last_decision.get("action_type")

        health = homeo.get("health_score")
        if health is not None:
            health = float(health)

        semantic_text = _build_semantic_text(
            mode=mode_str,
            n_active_goals=n_active_goals,
            last_action_type=last_action_type,
            health_score=health,
            extra_lines=extra_semantic_lines,
        )

        return cls(
            timestamp=float(timestamp),
            semantic_text=semantic_text,
            numeric_features=numeric,
            mode=mode_str,
            last_action_type=last_action_type,
            health_score=health,
            episode_id=episode_id,
        )


def _build_semantic_text(
    mode: Optional[str],
    n_active_goals: Optional[int],
    last_action_type: Optional[str],
    health_score: Optional[float],
    extra_lines: Optional[List[str]],
) -> str:
    """Render a short multi-line text summarizing the snapshot.

    Stable line ordering matters: the embedding model encodes positional
    cues, so two snapshots with the same data must produce the same text.
    Empty fields are skipped rather than rendered as 'None' -- keeps the
    embedding focused on what is actually known.
    """
    lines: List[str] = []
    if mode:
        lines.append(f"mode={mode}")
    if n_active_goals is not None:
        lines.append(f"active_goals={n_active_goals}")
    if last_action_type:
        lines.append(f"last_action={last_action_type}")
    if health_score is not None:
        lines.append(f"health={health_score:.2f}")
    if extra_lines:
        lines.extend(extra_lines)
    return "\n".join(lines)
