"""
StateReporter (K15.1) - Structured self-status reporting.

Maria reports her state honestly, on demand or proactively.
Aggregates data from multiple subsystems into a coherent snapshot.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StateSnapshot:
    """Point-in-time snapshot of Maria's state."""

    timestamp: float
    mode: str  # homeostasis mode
    health_score: float  # 0.0-1.0
    capabilities_available: int
    capabilities_total: int
    active_goals_count: int
    proposed_goals_count: int
    knowledge_files: int
    knowledge_completed: int
    recent_actions: List[Dict]  # last 5 planner decisions
    alerts: List[str]  # active warnings
    uptime_hours: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "health_score": self.health_score,
            "capabilities_available": self.capabilities_available,
            "capabilities_total": self.capabilities_total,
            "active_goals_count": self.active_goals_count,
            "proposed_goals_count": self.proposed_goals_count,
            "knowledge_files": self.knowledge_files,
            "knowledge_completed": self.knowledge_completed,
            "recent_actions": self.recent_actions,
            "alerts": self.alerts,
            "uptime_hours": self.uptime_hours,
        }


class StateReporter:
    """
    Structured self-status on demand and proactive.

    Aggregates from: homeostasis core, capability manifest,
    goal store, knowledge analyzer, planner core.
    """

    def __init__(self, cache_ttl: float = 30.0):
        self._capability_manifest = None
        self._homeostasis_core = None
        self._planner_core = None
        self._goal_store = None
        self._knowledge_analyzer = None
        self._identity_store = None
        self._cache_ttl = cache_ttl
        self._cached_snapshot: Optional[StateSnapshot] = None
        self._cached_at: float = 0.0
        # Proactive reporting state
        self._last_reported_mode: Optional[str] = None
        self._last_reported_health: Optional[float] = None
        self._last_proactive_ts: float = 0.0
        self._proactive_cooldown: float = 3600.0  # 1 hour

    # -- DI setters --

    def set_capability_manifest(self, manifest) -> None:
        self._capability_manifest = manifest

    def set_homeostasis_core(self, core) -> None:
        self._homeostasis_core = core

    def set_planner_core(self, planner) -> None:
        self._planner_core = planner

    def set_goal_store(self, store) -> None:
        self._goal_store = store

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._knowledge_analyzer = analyzer

    def set_identity_store(self, store) -> None:
        self._identity_store = store

    # -- Core API --

    def get_snapshot(self) -> StateSnapshot:
        """Get current state snapshot (cached with TTL)."""
        now = time.time()
        if self._cached_snapshot and (now - self._cached_at) < self._cache_ttl:
            return self._cached_snapshot

        snapshot = self._build_snapshot(now)
        self._cached_snapshot = snapshot
        self._cached_at = now
        return snapshot

    def get_summary_text(self) -> str:
        """Polish human-readable state summary."""
        s = self.get_snapshot()
        lines = ["*Raport stanu:*", ""]
        lines.append(f"Tryb: {s.mode}, health: {s.health_score:.0%}")
        lines.append(
            f"Mozliwosci: {s.capabilities_available}/{s.capabilities_total} dostepnych"
        )
        lines.append(
            f"Wiedza: {s.knowledge_completed}/{s.knowledge_files} plikow"
        )
        lines.append(
            f"Cele: {s.active_goals_count} aktywnych, {s.proposed_goals_count} czeka"
        )

        if s.uptime_hours > 0:
            if s.uptime_hours >= 24:
                days = s.uptime_hours / 24
                lines.append(f"Uptime: {days:.1f} dni")
            else:
                lines.append(f"Uptime: {s.uptime_hours:.1f}h")

        if s.recent_actions:
            lines.append("\nOstatnie akcje:")
            for a in s.recent_actions[:5]:
                action = a.get("action", "?")
                status = a.get("status", "?")
                lines.append(f"  - {action}: {status}")

        if s.alerts:
            lines.append("\nAlerty:")
            for alert in s.alerts:
                lines.append(f"  ! {alert}")

        return "\n".join(lines)

    def get_compact_context(self) -> str:
        """Short version for LLM system prompt injection."""
        s = self.get_snapshot()
        parts = [
            f"mode={s.mode}",
            f"health={s.health_score:.0%}",
            f"caps={s.capabilities_available}/{s.capabilities_total}",
            f"goals={s.active_goals_count}",
            f"knowledge={s.knowledge_completed}/{s.knowledge_files}",
        ]
        if s.alerts:
            parts.append(f"alerts={len(s.alerts)}")
        return "Status: " + ", ".join(parts)

    def should_report_proactively(self) -> bool:
        """Check if state changed significantly since last report."""
        now = time.time()
        if (now - self._last_proactive_ts) < self._proactive_cooldown:
            return False

        s = self.get_snapshot()

        # Mode change
        if self._last_reported_mode and s.mode != self._last_reported_mode:
            return True

        # Health drop below threshold
        if self._last_reported_health is not None:
            if s.health_score < 0.7 and self._last_reported_health >= 0.7:
                return True

        return False

    def get_proactive_message(self) -> Optional[str]:
        """Get proactive state report if needed. Returns None if not needed."""
        if not self.should_report_proactively():
            return None

        s = self.get_snapshot()
        lines = ["*Zmiana stanu:*"]

        if self._last_reported_mode and s.mode != self._last_reported_mode:
            lines.append(
                f"Tryb: {self._last_reported_mode} -> {s.mode}"
            )
        if (
            self._last_reported_health is not None
            and s.health_score < 0.7
            and self._last_reported_health >= 0.7
        ):
            lines.append(
                f"Health spadl: {self._last_reported_health:.0%} -> {s.health_score:.0%}"
            )

        # Update tracking
        self._last_reported_mode = s.mode
        self._last_reported_health = s.health_score
        self._last_proactive_ts = time.time()

        if len(lines) <= 1:
            return None
        return "\n".join(lines)

    # -- Internal --

    def _build_snapshot(self, now: float) -> StateSnapshot:
        """Assemble state from all sources."""
        # Mode & health from homeostasis
        mode = "UNKNOWN"
        health = 0.0
        if self._homeostasis_core:
            try:
                state = self._homeostasis_core.get_state()
                mode = state.get("mode", "UNKNOWN")
                health = state.get("health_score", 0.0)
            except Exception:
                pass

        # Capabilities from manifest
        caps_available = 0
        caps_total = 0
        if self._capability_manifest:
            try:
                caps = self._capability_manifest.get_capabilities()
                caps_total = len(caps)
                caps_available = len([c for c in caps if c.available])
            except Exception:
                pass

        # Goals
        active_goals = 0
        proposed_goals = 0
        if self._goal_store:
            try:
                active_goals = len(self._goal_store.get_active())
                proposed_goals = len(self._goal_store.get_proposed())
            except Exception:
                pass

        # Knowledge
        kn_files = 0
        kn_completed = 0
        if self._knowledge_analyzer:
            try:
                snap = self._knowledge_analyzer.get_knowledge_snapshot()
                kn_files = snap.get("total_files", 0)
                by_status = snap.get("files_by_status", {})
                kn_completed = len(by_status.get("completed", []))
            except Exception:
                pass

        # Recent planner actions
        recent = []
        if self._planner_core:
            try:
                decisions = getattr(self._planner_core, "_decisions_log", [])
                for d in decisions[-5:]:
                    recent.append({
                        "action": d.get("action_type", "?"),
                        "status": d.get("status", "?"),
                    })
            except Exception:
                pass

        # Alerts
        alerts = self._collect_alerts(mode, health)

        # Uptime
        uptime_h = 0.0
        if self._identity_store:
            try:
                uptime_h = self._identity_store.get_uptime_hours()
            except Exception:
                pass

        return StateSnapshot(
            timestamp=now,
            mode=mode,
            health_score=health,
            capabilities_available=caps_available,
            capabilities_total=caps_total,
            active_goals_count=active_goals,
            proposed_goals_count=proposed_goals,
            knowledge_files=kn_files,
            knowledge_completed=kn_completed,
            recent_actions=recent,
            alerts=alerts,
            uptime_hours=uptime_h,
        )

    @staticmethod
    def _collect_alerts(mode: str, health: float) -> List[str]:
        """Collect active alerts/warnings."""
        alerts = []
        if mode not in ("ACTIVE", "UNKNOWN"):
            alerts.append(f"Tryb degradowany: {mode}")
        if health < 0.5:
            alerts.append(f"Niski health: {health:.0%}")
        elif health < 0.7:
            alerts.append(f"Health ponizej normy: {health:.0%}")
        return alerts
