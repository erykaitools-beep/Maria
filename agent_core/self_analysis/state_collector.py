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

from agent_core.planner.decision_filters import is_real_action, result_is_skipped

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
        """Find low-confidence topics. Uses MemoryQuery (Phase 2) or falls back to raw JSONL.

        Legacy fallback mirrors MemoryQuery.get_knowledge_gaps aggregation:
        fact beliefs (linked via tags) and completed knowledge_index files count
        as evidence against a gap, preventing false positives from decayed
        observation beliefs.
        """
        # Phase 2: unified query (includes beliefs + exam_failed files)
        if self._memory_query:
            try:
                return self._memory_query.get_knowledge_gaps(top_k=10)
            except Exception:
                pass  # Fall through to legacy

        # Legacy: read beliefs directly + aggregate evidence
        beliefs = self._read_jsonl_all(self._meta / "beliefs.jsonl")
        by_id = {}
        for b in beliefs:
            bid = b.get("belief_id", "")
            if bid:
                by_id[bid] = b
        # Drop superseded AND quarantined/retracted (status != active). Missing
        # status key on an old record means active (backward compatible).
        active_beliefs = [
            b for b in by_id.values()
            if not b.get("superseded_by") and b.get("status", "active") == "active"
        ]

        facts = [b for b in active_beliefs if b.get("belief_type") == "fact"]
        candidates = [b for b in active_beliefs if b.get("belief_type") != "fact"]

        # Knowledge index for file-score evidence
        ki_records = self._read_jsonl_all(self._memory / "knowledge_index.jsonl")
        ki_by_id: Dict[str, Dict[str, Any]] = {}
        for r in ki_records:
            rid = r.get("id", "")
            if rid:
                ki_by_id[rid] = r

        gaps = []
        for b in candidates:
            entity = b.get("entity", "")
            if not entity:
                continue
            obs_conf = b.get("confidence", 0.5)
            entity_lower = entity.lower()

            supporting_facts = [
                f for f in facts
                if any(t.lower() == entity_lower for t in f.get("tags", []))
            ]
            max_fact_conf = max(
                (f.get("confidence", 0.0) for f in supporting_facts),
                default=0.0,
            )

            topic_token = entity_lower.replace(" ", "_").replace("-", "_")
            supporting_scores: List[float] = []
            for krec in ki_by_id.values():
                fname = (krec.get("file") or "").lower()
                name_match = (topic_token in fname) or (entity_lower in fname)
                if name_match and krec.get("status") == "completed":
                    scores = krec.get("last_scores", [])
                    if scores:
                        supporting_scores.append(max(scores))
            max_file_score = max(supporting_scores, default=0.0)

            effective = max(obs_conf, max_fact_conf, max_file_score)
            if effective >= 0.5:
                continue

            has_evidence = bool(supporting_facts or supporting_scores)
            gaps.append({
                "topic": entity,
                "confidence": round(effective, 2),
                "belief_count": 1 + len(supporting_facts),
                "reason": "low_confidence_aggregate" if has_evidence else "low_confidence_belief",
                "evidence": {
                    "observation_conf": round(obs_conf, 2),
                    "fact_count": len(supporting_facts),
                    "max_fact_conf": round(max_fact_conf, 2),
                    "file_count": len(supporting_scores),
                    "max_file_score": round(max_file_score, 2),
                } if has_evidence else {},
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
            # T-LEARN-003: skip planner idle markers (rest) and skipped attempts
            # so the distribution reflects real, attempted actions only -- not
            # the off-window "skip" markers that drove the false "0% success" storm.
            if not is_real_action(d):
                continue
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

        # Recent teacher plans (last 20). Exclude skipped attempts (declined
        # before any work -- e.g. no fresh material) so the rate measures
        # ATTEMPTED learns only, matching _collect_action_distribution and
        # decision_filters (T-LEARN-003: skips are neither success nor failure;
        # counting them as failures drove the phantom "0% success" storm).
        teacher_plans = self._read_jsonl_recent(
            self._meta / "teacher_plans.jsonl", 0, limit=20
        )
        attempted = [
            p for p in teacher_plans if not result_is_skipped(p.get("result"))
        ]
        learn_success = sum(1 for p in attempted if p.get("result", {}).get("success"))
        learn_total = len(attempted)

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
