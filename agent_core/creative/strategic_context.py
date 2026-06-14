"""Builds development-level context from system data sources.

Collects strategic context for Creative module from:
- K12 StateCollector (metrics, gaps, action distribution)
- GoalStore (active/stale goals, proposed goals)
- K6 BeliefStore (world model beliefs)
- K4 Evaluation reports (trends)
- CreativeStore (recent journal, past meta-goals, conversation memory)
- IdentityStore (session count, uptime, traits)
- Planner decisions (recent actions, NOOP ratio)

Zero LLM - pure data aggregation.
"""

import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.planner.decision_filters import IDLE_ACTION_TYPES

logger = logging.getLogger(__name__)


class StrategicContext:
    """Builds development-level context snapshot for Creative reasoning."""

    def __init__(self, data_dir: str = "meta_data", memory_dir: str = "memory"):
        self._meta = Path(data_dir)
        self._memory = Path(memory_dir)

    def build(self, period_hours: float = 24.0) -> Dict[str, Any]:
        """
        Build a strategic context snapshot.

        Returns a compact dict (~1-3KB) with:
        - action_pattern: what Maria has been doing (noop ratio, action distribution)
        - learning_state: coverage, velocity, struggling topics
        - goal_state: active goals, stale goals, proposed count
        - recent_tensions: any previously detected tensions
        - recent_meta_goals: past creative output (for dedup)
        - system_health: mode, stability, resource pressure
        - identity: session count, uptime, trait snapshot
        """
        now = time.time()
        cutoff = now - (period_hours * 3600)

        context = {
            "generated_at": now,
            "period_hours": period_hours,
            "action_pattern": self._collect_action_pattern(cutoff),
            "learning_state": self._collect_learning_state(),
            "goal_state": self._collect_goal_state(now),
            "recent_meta_goals": self._collect_recent_meta_goals(cutoff),
            "system_health": self._collect_system_health(),
            "identity": self._collect_identity(),
        }
        return context

    def _collect_action_pattern(self, cutoff: float) -> Dict[str, Any]:
        """Analyze planner decisions for patterns."""
        path = self._meta / "planner_decisions.jsonl"
        if not path.exists():
            return {"total": 0, "noop_ratio": 1.0, "distribution": {}}

        total = 0
        noops = 0
        dist: Counter = Counter()
        failed = 0

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        ts = record.get("timestamp", 0)
                        if ts < cutoff:
                            continue
                        total += 1
                        action = record.get("action_type", "unknown")
                        dist[action] += 1
                        # T-LEARN-008: planner pisze "skip" (nie "noop") jako idle
                        # marker -- liczenie samego "noop" raportowalo 0.4% przy
                        # realnych ~84% idle i slepilo detekcje tensji K13.
                        if action in IDLE_ACTION_TYPES:
                            noops += 1
                        # T-LEARN-003: skipped attempts (status now SKIPPED at the
                        # source) are not failures; only genuine failures count.
                        if record.get("status") == "failed":
                            failed += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        return {
            "total": total,
            "noop_ratio": noops / max(total, 1),
            "failed_ratio": failed / max(total, 1),
            "distribution": dict(dist.most_common(10)),
        }

    def _collect_learning_state(self) -> Dict[str, Any]:
        """Get learning coverage and velocity."""
        index_path = self._memory / "knowledge_index.jsonl"
        if not index_path.exists():
            return {"total_files": 0, "completed": 0, "coverage": 0.0}

        statuses: Counter = Counter()
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        statuses[record.get("status", "unknown")] += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        total = sum(statuses.values())
        completed = statuses.get("completed", 0)

        # Also check latest evaluation report for retention
        retention = self._get_latest_metric("retention_rate")
        velocity = self._get_latest_metric("learning_velocity")

        return {
            "total_files": total,
            "completed": completed,
            "coverage": completed / max(total, 1),
            "statuses": dict(statuses),
            "retention_rate": retention,
            "learning_velocity": velocity,
        }

    def _collect_goal_state(self, now: float) -> Dict[str, Any]:
        """Get goal distribution and staleness."""
        path = self._meta / "goals.jsonl"
        if not path.exists():
            return {"active": 0, "proposed": 0, "stale": []}

        # MERGE semantics
        goals: Dict[str, Dict] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        gid = record.get("id", "")
                        if gid:
                            goals[gid] = record
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        active = 0
        proposed = 0
        stale = []
        stale_threshold = 72 * 3600  # 72h without progress

        for g in goals.values():
            status = g.get("status", "")
            if status == "active":
                active += 1
                updated = g.get("updated_at", 0)
                if now - updated > stale_threshold:
                    stale.append(g.get("description", "")[:80])
            elif status == "proposed":
                proposed += 1

        return {
            "active": active,
            "proposed": proposed,
            "stale_goals": stale[:5],
            "total": len(goals),
        }

    def _collect_recent_meta_goals(self, cutoff: float) -> List[str]:
        """Get titles of recent creative meta-goals (for dedup)."""
        path = self._meta / "creative_meta_goals.jsonl"
        if not path.exists():
            return []

        titles = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("created_ts", 0) > cutoff:
                            titles.append(record.get("title", ""))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return titles

    def _collect_system_health(self) -> Dict[str, Any]:
        """Get current system mode and stability."""
        stability = self._get_latest_metric("system_stability")
        personality_growth = self._get_latest_metric("personality_growth")

        return {
            "system_stability": stability,
            "personality_growth": personality_growth,
        }

    def _collect_identity(self) -> Dict[str, Any]:
        """Get identity snapshot from consciousness_identity.json."""
        path = self._meta / "consciousness_identity.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "session_count": data.get("session_count", 0),
                "total_uptime_hours": data.get("total_uptime_seconds", 0) / 3600,
                "trait_scores": {
                    k: v.get("score", 0) if isinstance(v, dict) else v
                    for k, v in data.get("trait_scores", {}).items()
                },
            }
        except (OSError, json.JSONDecodeError):
            return {}

    def _get_latest_metric(self, metric_name: str) -> Optional[float]:
        """Get latest metric value from evaluation reports."""
        path = self._meta / "evaluation_reports.jsonl"
        if not path.exists():
            return None

        latest_value = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        metrics = record.get("metrics", {})
                        if metric_name in metrics:
                            latest_value = metrics[metric_name]
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return latest_value
