"""
K12 Self-Analysis: StateCollector.

Reads existing JSONL log files and compresses Maria's cognitive state
into a compact summary (~2-4KB) suitable for external AI analysis.

Zero LLM - pure rule-based aggregation from existing data sources.
"""

import json
import hashlib
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Default paths relative to project root
_DEFAULT_META = "meta_data"
_DEFAULT_MEMORY = "memory"


class StateCollector:
    """Collect and compress Maria's cognitive state from JSONL logs."""

    def __init__(self, project_root: str = "."):
        self._root = Path(project_root)
        self._meta = self._root / _DEFAULT_META
        self._memory = self._root / _DEFAULT_MEMORY
        self._memory_query = None

    def set_memory_query(self, mq) -> None:
        """Set MemoryQuery for unified knowledge gap detection (Phase 2)."""
        self._memory_query = mq

    def collect(self, period_days: int = 7) -> Dict[str, Any]:
        """
        Collect compressed state summary.

        Returns a dict suitable for JSON serialization (~2-4KB).
        Zero LLM calls - pure file reads and aggregation.
        """
        now = time.time()
        cutoff = now - (period_days * 86400)

        summary = {
            "generated_at": now,
            "period_days": period_days,
            "metrics_trend": self._collect_metrics_trend(cutoff),
            "knowledge_gaps": self._collect_knowledge_gaps(),
            "struggling_topics": self._collect_struggling_topics(cutoff),
            "action_distribution": self._collect_action_distribution(cutoff),
            "stale_goals": self._collect_stale_goals(now),
            "learning_progress": self._collect_learning_progress(),
            "system_health": self._collect_system_health(cutoff),
        }

        # Generate hash for dedup
        summary["input_hash"] = hashlib.sha256(
            json.dumps(summary, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        return summary

    def collect_with_prompt(self, period_days: int = 7) -> Dict[str, Any]:
        """Collect state + append analysis prompt for external AI."""
        summary = self.collect(period_days)
        summary["analysis_prompt"] = (
            "You are analyzing the performance logs of M.A.R.I.A., "
            "an autonomous AI learning agent. Based on the data above, provide:\n"
            "1. The 3 most impactful knowledge gaps to address (topics to learn)\n"
            "2. Any systemic issues in the learning strategy\n"
            "3. Specific topics to search for educational materials\n\n"
            "Return ONLY a JSON object with keys:\n"
            '- "recommendations": array of {category, topic, description, priority (0-1), suggested_action}\n'
            '  category: "knowledge_gap" | "retention_problem" | "strategy_change" | "new_topic"\n'
            '  suggested_action: "learn" | "fetch" | "review" | "experiment"\n'
            '- "systemic_issues": array of strings\n'
            '- "summary": one paragraph summary\n'
            "Max 5 recommendations. Be specific and actionable."
        )
        return summary

    def collect_with_code_context(self, period_days: int = 7) -> Dict[str, Any]:
        """Collect state + code context for Claude CLI analysis (K12 Phase 2)."""
        summary = self.collect_with_prompt(period_days)

        # Add code self-model issues (from introspection v1)
        code_model_path = self._meta / "code_self_model.json"
        if code_model_path.exists():
            try:
                with open(code_model_path, "r", encoding="utf-8") as f:
                    model = json.load(f)
                summary["code_context"] = {
                    "total_files": model.get("statistics", {}).get("total_files", 0),
                    "total_lines": model.get("statistics", {}).get("total_lines", 0),
                    "issues": model.get("issues", [])[:10],
                    "packages": list(model.get("packages", {}).keys()),
                }
            except Exception:
                pass

        # Add recent LLM tape errors
        tape_path = self._meta / "llm_tape.jsonl"
        if tape_path.exists():
            try:
                errors = []
                for line in open(tape_path, "r", encoding="utf-8"):
                    try:
                        d = json.loads(line.strip())
                        if not d.get("success", True):
                            errors.append({
                                "model": d.get("model", "?"),
                                "role": d.get("role", "?"),
                                "response_preview": d.get("raw_response", "")[:100],
                            })
                    except json.JSONDecodeError:
                        pass
                if errors:
                    summary["recent_llm_errors"] = errors[-5:]  # last 5
            except Exception:
                pass

        return summary

    # --- Internal collectors ---

    def _collect_metrics_trend(self, cutoff: float) -> Dict[str, List[float]]:
        """Read last K4 evaluation reports and extract metric trends."""
        reports = self._read_jsonl_recent(
            self._meta / "evaluation_reports.jsonl", cutoff, limit=10
        )

        trend = {
            "learning_velocity": [],
            "retention_rate": [],
            "knowledge_coverage": [],
            "system_stability": [],
        }

        for r in reports:
            metrics = r.get("metrics", {})
            for key in trend:
                val = metrics.get(key)
                if val is not None:
                    trend[key].append(round(float(val), 3))

        return trend

    def _collect_knowledge_gaps(self) -> List[Dict[str, Any]]:
        """Find low-confidence topics. Uses MemoryQuery (Phase 2) or falls back to raw JSONL."""
        # Phase 2: unified query (includes beliefs + exam_failed files)
        if self._memory_query:
            try:
                return self._memory_query.get_knowledge_gaps(top_k=10)
            except Exception:
                pass  # Fall through to legacy

        # Legacy: read beliefs directly
        beliefs = self._read_jsonl_all(self._meta / "beliefs.jsonl")

        by_id = {}
        for b in beliefs:
            bid = b.get("belief_id", "")
            if bid:
                by_id[bid] = b

        topic_confidence: Dict[str, List[float]] = {}
        for b in by_id.values():
            entity = b.get("entity", "")
            conf = b.get("confidence", 0.5)
            if entity:
                topic_confidence.setdefault(entity, []).append(conf)

        gaps = []
        for topic, confs in topic_confidence.items():
            avg_conf = sum(confs) / len(confs)
            if avg_conf < 0.6:
                gaps.append({
                    "topic": topic,
                    "confidence": round(avg_conf, 2),
                    "belief_count": len(confs),
                })

        gaps.sort(key=lambda g: g["confidence"])
        return gaps[:10]

    def _collect_struggling_topics(self, cutoff: float) -> List[str]:
        """Read K9 reflections and find topics with repeated mismatches."""
        reflections = self._read_jsonl_recent(
            self._meta / "reflections.jsonl", cutoff, limit=100
        )

        mismatch_topics: Counter = Counter()
        for r in reflections:
            if r.get("outcome_match") == "mismatch" or not r.get("actual_success", True):
                # Try to extract topic from assumptions or context
                for assumption in r.get("assumptions", []):
                    desc = assumption.get("description", "")
                    if desc:
                        # Simple heuristic: first few words as topic hint
                        words = desc.split()[:3]
                        if words:
                            mismatch_topics[" ".join(words)] += 1

        # Topics with 2+ mismatches
        return [topic for topic, count in mismatch_topics.most_common(5) if count >= 2]

    def _collect_action_distribution(self, cutoff: float) -> Dict[str, Dict[str, Any]]:
        """Read planner decisions and compute action type distribution."""
        decisions = self._read_jsonl_recent(
            self._meta / "planner_decisions.jsonl", cutoff, limit=200
        )

        dist: Dict[str, Dict[str, int]] = {}
        for d in decisions:
            action = d.get("action_type", "unknown")
            if action not in dist:
                dist[action] = {"count": 0, "success": 0, "failed": 0}
            dist[action]["count"] += 1
            result = d.get("result", {})
            if result.get("success"):
                dist[action]["success"] += 1
            elif d.get("status") == "failed":
                dist[action]["failed"] += 1

        # Compute success percentage
        result = {}
        for action, counts in dist.items():
            total = counts["count"]
            result[action] = {
                "count": total,
                "success_pct": round(counts["success"] / total, 2) if total > 0 else 0,
                "failed": counts["failed"],
            }

        return result

    def _collect_stale_goals(self, now: float) -> List[Dict[str, Any]]:
        """Find goals that are ACTIVE but old (stale)."""
        goals = self._read_jsonl_all(self._meta / "goals.jsonl")

        # MERGE semantics
        by_id = {}
        for g in goals:
            gid = g.get("id") or g.get("goal_id", "")
            if gid:
                by_id[gid] = g

        stale = []
        for g in by_id.values():
            status = (g.get("status") or "").upper()
            if status in ("ACTIVE", "PENDING"):
                created = g.get("created_at", now)
                age_days = (now - created) / 86400
                if age_days > 2:  # Stale if active > 2 days
                    stale.append({
                        "id": g.get("id") or g.get("goal_id", ""),
                        "description": (g.get("description", ""))[:80],
                        "days_stale": round(age_days, 1),
                    })

        stale.sort(key=lambda s: s["days_stale"], reverse=True)
        return stale[:5]

    def _collect_learning_progress(self) -> Dict[str, Any]:
        """Read knowledge_index and teacher plans for learning stats."""
        # Knowledge index
        ki_records = self._read_jsonl_all(self._memory / "knowledge_index.jsonl")
        by_id = {}
        for r in ki_records:
            rid = r.get("id", "")
            if rid:
                by_id[rid] = r

        status_counts: Counter = Counter()
        for r in by_id.values():
            status_counts[r.get("status", "unknown")] += 1

        # Recent teacher plans (last 20)
        teacher_plans = self._read_jsonl_recent(
            self._meta / "teacher_plans.jsonl", 0, limit=20
        )
        learn_success = sum(1 for p in teacher_plans if p.get("result", {}).get("success"))
        learn_total = len(teacher_plans)

        return {
            "total_files": len(by_id),
            "by_status": dict(status_counts),
            "recent_learn_success_rate": round(learn_success / learn_total, 2) if learn_total > 0 else 0,
            "recent_learn_count": learn_total,
        }

    def _collect_system_health(self, cutoff: float) -> Dict[str, Any]:
        """Read homeostasis events for health summary."""
        events = self._read_jsonl_recent(
            self._meta / "homeostasis_events.jsonl", cutoff, limit=50
        )

        health_scores = []
        mode_counts: Counter = Counter()

        for e in events:
            et = e.get("event_type", e.get("event", ""))
            if et == "state_snapshot":
                hs = e.get("health_score")
                if hs is not None:
                    health_scores.append(float(hs))
                mode = e.get("mode", "active")
                mode_counts[mode] += 1

        return {
            "avg_health": round(sum(health_scores) / len(health_scores), 3) if health_scores else 1.0,
            "min_health": round(min(health_scores), 3) if health_scores else 1.0,
            "mode_distribution": dict(mode_counts),
        }

    # --- JSONL helpers ---

    def _read_jsonl_all(self, path: Path) -> List[Dict[str, Any]]:
        """Read all records from JSONL file."""
        if not path.exists():
            return []
        records = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except IOError:
            pass
        return records

    def _read_jsonl_recent(
        self, path: Path, cutoff: float, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Read last N records from JSONL, optionally filtered by timestamp."""
        all_records = self._read_jsonl_all(path)

        # Take last `limit` records
        recent = all_records[-limit:] if limit > 0 else all_records

        # Filter by cutoff if set
        if cutoff > 0:
            recent = [
                r for r in recent
                if r.get("timestamp", r.get("ts", r.get("period_end", 0))) >= cutoff
            ]

        return recent
