"""
Evidence Collector for State-Grounded Operator Responses.

Reads operational data from JSONL files and runtime objects,
returns structured Evidence facts with source attribution.

Design:
- READ-ONLY (ADR-006)
- Runtime objects via DI setters (REPL path: full wiring)
- JSONL file fallback when objects are None (Web UI path)
- Each Evidence has: key, value, source, confidence, timestamp
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.introspection.query_router import ResponseMode

logger = logging.getLogger(__name__)

# How many recent entries to read from JSONL files
_TAIL_LIMIT = 10


@dataclass
class Evidence:
    """Single fact from operational data."""
    key: str               # e.g. "planner.last_action"
    value: str             # e.g. "EXAM"
    source: str            # e.g. "planner_decisions.jsonl"
    confidence: str        # "high" | "medium" | "low"
    timestamp: float = 0.0  # when this fact was recorded


class EvidenceCollector:
    """
    Collects operational facts for grounded responses.

    Can work in two modes:
    - Full wiring (REPL): runtime objects + JSONL files
    - File-only (Web UI): JSONL files only (objects = None)
    """

    def __init__(self, project_root: str = "."):
        self._root = Path(project_root)
        self._meta = self._root / "meta_data"

        # Runtime object references (set via DI)
        self._homeostasis_core = None
        self._planner_core = None
        self._knowledge_analyzer = None
        self._evaluation_observer = None
        self._llm_tape = None
        self._self_analysis = None
        self._goal_store = None

        # Compact summary cache
        self._summary_cache: str = ""
        self._summary_ts: float = 0.0
        self._summary_ttl: float = 30.0  # seconds

    # -- DI setters --

    def set_homeostasis_core(self, core):
        self._homeostasis_core = core

    def set_planner_core(self, pc):
        self._planner_core = pc

    def set_knowledge_analyzer(self, ka):
        self._knowledge_analyzer = ka

    def set_evaluation_observer(self, eo):
        self._evaluation_observer = eo

    def set_llm_tape(self, tape):
        self._llm_tape = tape

    def set_self_analysis(self, sa):
        self._self_analysis = sa

    def set_goal_store(self, gs):
        self._goal_store = gs

    # -- Public API --

    def collect_for_mode(self, mode: ResponseMode) -> List[Evidence]:
        """Collect evidence relevant to the given response mode."""
        collectors = {
            ResponseMode.GROUNDED_STATUS: self.collect_status,
            ResponseMode.GROUNDED_ERROR: self.collect_error,
            ResponseMode.GROUNDED_LEARNING: self.collect_learning,
            ResponseMode.GROUNDED_PLANNER: self.collect_planner,
        }
        fn = collectors.get(mode, self.collect_status)
        try:
            return fn()
        except Exception as e:
            logger.debug(f"[EvidenceCollector] collect failed for {mode}: {e}")
            return []

    def collect_status(self) -> List[Evidence]:
        """General status: mode, health, last action, learning progress."""
        evidence = []

        # Homeostasis state
        evidence.extend(self._collect_homeostasis())

        # Last planner action
        evidence.extend(self._collect_planner_last())

        # Learning summary
        evidence.extend(self._collect_learning_summary())

        # LLM tape stats
        evidence.extend(self._collect_tape_stats())

        return evidence

    def collect_error(self) -> List[Evidence]:
        """Errors: failures, blocked actions, alerts, tape errors."""
        evidence = []

        # Homeostasis alerts
        evidence.extend(self._collect_homeostasis())

        # Planner failures (recent blocked/failed plans)
        evidence.extend(self._collect_planner_failures())

        # LLM tape errors
        evidence.extend(self._collect_tape_errors())

        # Autonomy blocks
        evidence.extend(self._collect_autonomy_blocks())

        return evidence

    def collect_learning(self) -> List[Evidence]:
        """Learning: files, chunks, exams, retention, strategy."""
        evidence = []

        evidence.extend(self._collect_learning_summary())
        evidence.extend(self._collect_recent_exams())
        evidence.extend(self._collect_planner_last())
        evidence.extend(self._collect_evaluation_metrics())

        return evidence

    def collect_planner(self) -> List[Evidence]:
        """Planner: active goal, strategy, recent decisions."""
        evidence = []

        evidence.extend(self._collect_planner_last())
        evidence.extend(self._collect_planner_failures())
        evidence.extend(self._collect_goals())

        return evidence

    def build_compact_summary(self) -> str:
        """
        Build ~500 token compact summary for system prompt background.
        Cached for 30 seconds.
        """
        now = time.time()
        if self._summary_cache and (now - self._summary_ts) < self._summary_ttl:
            return self._summary_cache

        parts = []

        # Homeostasis
        hs = self._collect_homeostasis()
        if hs:
            mode_ev = next((e for e in hs if e.key == "homeostasis.mode"), None)
            health_ev = next((e for e in hs if e.key == "homeostasis.health"), None)
            if mode_ev or health_ev:
                mode_str = mode_ev.value if mode_ev else "?"
                health_str = health_ev.value if health_ev else "?"
                parts.append(f"Tryb: {mode_str}, zdrowie: {health_str}")

        # Planner
        pl = self._collect_planner_last()
        if pl:
            action_ev = next((e for e in pl if e.key == "planner.last_action"), None)
            if action_ev:
                parts.append(f"Ostatnia akcja: {action_ev.value}")

        # Learning
        ls = self._collect_learning_summary()
        if ls:
            files_ev = next((e for e in ls if e.key == "learning.total_files"), None)
            learned_ev = next((e for e in ls if e.key == "learning.completed"), None)
            if files_ev:
                learned = learned_ev.value if learned_ev else "?"
                parts.append(f"Pliki: {files_ev.value} ({learned} ukoncz.)")

        # LLM stats
        ts = self._collect_tape_stats()
        if ts:
            calls_ev = next((e for e in ts if e.key == "llm.total_calls_24h"), None)
            if calls_ev:
                parts.append(f"LLM: {calls_ev.value} wywolan/24h")

        summary = "[Stan operacyjny: " + ". ".join(parts) + ".]" if parts else ""
        self._summary_cache = summary[:600]  # hard limit
        self._summary_ts = now
        return self._summary_cache

    # -- Private collectors --

    def _collect_homeostasis(self) -> List[Evidence]:
        """Homeostasis mode, health, last alert."""
        evidence = []

        # Try runtime object first
        if self._homeostasis_core:
            try:
                state = self._homeostasis_core.get_state()
                evidence.append(Evidence(
                    key="homeostasis.mode",
                    value=state.mode.value if hasattr(state.mode, 'value') else str(state.mode),
                    source="homeostasis_core (runtime)",
                    confidence="high",
                    timestamp=time.time(),
                ))
                evidence.append(Evidence(
                    key="homeostasis.health",
                    value=str(round(state.health_score, 2)),
                    source="homeostasis_core (runtime)",
                    confidence="high",
                    timestamp=time.time(),
                ))
                return evidence
            except Exception:
                pass

        # Fallback: read JSONL
        events = self._tail_jsonl("homeostasis_events.jsonl", limit=5)
        if events:
            last = events[-1]
            mode = last.get("mode", last.get("data", {}).get("mode", "unknown"))
            health = last.get("health", last.get("data", {}).get("health_score", "?"))
            evidence.append(Evidence(
                key="homeostasis.mode", value=str(mode),
                source="homeostasis_events.jsonl",
                confidence="medium", timestamp=last.get("ts", 0),
            ))
            evidence.append(Evidence(
                key="homeostasis.health", value=str(health),
                source="homeostasis_events.jsonl",
                confidence="medium", timestamp=last.get("ts", 0),
            ))

        return evidence

    def _collect_planner_last(self) -> List[Evidence]:
        """Last planner decision."""
        evidence = []
        decisions = self._tail_jsonl("planner_decisions.jsonl", limit=3)
        if decisions:
            last = decisions[-1]
            action = last.get("action_type", "?")
            goal = last.get("goal_description", last.get("goal_id", "?"))
            status = last.get("status", "?")
            ts = last.get("timestamp", 0)

            evidence.append(Evidence(
                key="planner.last_action", value=action,
                source="planner_decisions.jsonl",
                confidence="high", timestamp=ts,
            ))
            evidence.append(Evidence(
                key="planner.last_goal", value=str(goal)[:100],
                source="planner_decisions.jsonl",
                confidence="high", timestamp=ts,
            ))
            evidence.append(Evidence(
                key="planner.last_status", value=status,
                source="planner_decisions.jsonl",
                confidence="high", timestamp=ts,
            ))

        return evidence

    def _collect_planner_failures(self) -> List[Evidence]:
        """Recent planner failures and blocked actions."""
        evidence = []
        decisions = self._tail_jsonl("planner_decisions.jsonl", limit=20)
        if not decisions:
            return evidence

        # Count recent failures
        failures = [d for d in decisions if d.get("status") == "failed"]
        if failures:
            # Count repeated actions
            action_counts = {}
            for f in failures:
                a = f.get("action_type", "?")
                action_counts[a] = action_counts.get(a, 0) + 1

            for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
                if count >= 3:
                    # Pattern detected: repeated failures
                    reason = ""
                    last_fail = [f for f in failures if f.get("action_type") == action][-1]
                    result = last_fail.get("result", {})
                    if isinstance(result, dict):
                        reasons = result.get("reasons", [])
                        if reasons:
                            reason = reasons[0][:100] if isinstance(reasons[0], str) else str(reasons[0])[:100]

                    evidence.append(Evidence(
                        key=f"planner.repeated_failure.{action}",
                        value=f"{count} razy w ostatnich {len(decisions)} decyzjach"
                              + (f" ({reason})" if reason else ""),
                        source="planner_decisions.jsonl",
                        confidence="high",
                        timestamp=last_fail.get("timestamp", 0),
                    ))

        return evidence

    def _collect_learning_summary(self) -> List[Evidence]:
        """Learning progress: file counts."""
        evidence = []

        # Try knowledge analyzer
        if self._knowledge_analyzer:
            try:
                stats = self._knowledge_analyzer.get_stats()
                evidence.append(Evidence(
                    key="learning.total_files", value=str(stats.get("total_files", 0)),
                    source="knowledge_analyzer (runtime)",
                    confidence="high", timestamp=time.time(),
                ))
                evidence.append(Evidence(
                    key="learning.completed", value=str(stats.get("completed", 0)),
                    source="knowledge_analyzer (runtime)",
                    confidence="high", timestamp=time.time(),
                ))
                return evidence
            except Exception:
                pass

        # Fallback: count input/ files
        try:
            input_dir = self._root / "input"
            if input_dir.exists():
                files = list(input_dir.glob("*.txt"))
                evidence.append(Evidence(
                    key="learning.total_files", value=str(len(files)),
                    source="input/ directory",
                    confidence="medium", timestamp=time.time(),
                ))
        except Exception:
            pass

        return evidence

    def _collect_recent_exams(self) -> List[Evidence]:
        """Recent exam results from teacher plans."""
        evidence = []
        plans = self._tail_jsonl("teacher_plans.jsonl", limit=10)

        exams = [p for p in plans if p.get("result", {}).get("type") == "exam"]
        if exams:
            last = exams[-1]
            result = last.get("result", {})
            score = result.get("score", "?")
            passed = result.get("passed", "?")
            file_id = result.get("file_id", "?")
            evidence.append(Evidence(
                key="learning.last_exam",
                value=f"{file_id}: {score} ({'zdany' if passed else 'niezdany'})",
                source="teacher_plans.jsonl",
                confidence="high",
                timestamp=last.get("timestamp", 0),
            ))

        return evidence

    def _collect_evaluation_metrics(self) -> List[Evidence]:
        """Retention rate and learning velocity."""
        evidence = []
        reports = self._tail_jsonl("evaluation_reports.jsonl", limit=3)
        if reports:
            last = reports[-1]
            metrics = last.get("metrics", last)
            retention = metrics.get("retention_rate")
            velocity = metrics.get("learning_velocity")

            if retention is not None:
                evidence.append(Evidence(
                    key="evaluation.retention_rate",
                    value=str(round(float(retention), 2)),
                    source="evaluation_reports.jsonl",
                    confidence="high",
                    timestamp=last.get("timestamp", 0),
                ))
            if velocity is not None:
                evidence.append(Evidence(
                    key="evaluation.learning_velocity",
                    value=str(round(float(velocity), 2)),
                    source="evaluation_reports.jsonl",
                    confidence="high",
                    timestamp=last.get("timestamp", 0),
                ))

        return evidence

    def _collect_tape_stats(self) -> List[Evidence]:
        """LLM tape statistics."""
        evidence = []
        if self._llm_tape:
            try:
                stats = self._llm_tape.get_stats(period_hours=24)
                evidence.append(Evidence(
                    key="llm.total_calls_24h",
                    value=str(stats.get("total_calls", 0)),
                    source="llm_tape.jsonl",
                    confidence="high", timestamp=time.time(),
                ))
                if stats.get("error_count", 0) > 0:
                    evidence.append(Evidence(
                        key="llm.error_rate_24h",
                        value=f"{stats['error_count']} bledow ({stats['error_rate']*100:.1f}%)",
                        source="llm_tape.jsonl",
                        confidence="high", timestamp=time.time(),
                    ))
                return evidence
            except Exception:
                pass

        # Fallback: check file existence
        tape_path = self._meta / "llm_tape.jsonl"
        if tape_path.exists():
            evidence.append(Evidence(
                key="llm.tape_available", value="tak",
                source="llm_tape.jsonl",
                confidence="low", timestamp=time.time(),
            ))

        return evidence

    def _collect_tape_errors(self) -> List[Evidence]:
        """Recent LLM errors from tape."""
        evidence = []
        if self._llm_tape:
            try:
                errors = self._llm_tape.get_recent_errors(limit=3)
                for err in errors:
                    evidence.append(Evidence(
                        key="llm.error",
                        value=f"model={err.get('model','?')} role={err.get('role','?')} "
                              f"response='{err.get('raw_response','')[:80]}'",
                        source="llm_tape.jsonl",
                        confidence="high",
                        timestamp=err.get("ts", 0),
                    ))
            except Exception:
                pass

        return evidence

    def _collect_autonomy_blocks(self) -> List[Evidence]:
        """Recent autonomy policy blocks."""
        evidence = []
        decisions = self._tail_jsonl("autonomy_decisions.jsonl", limit=10)
        blocks = [d for d in decisions if d.get("decision") == "block"]
        if blocks:
            # Summarize recent blocks
            reasons = {}
            for b in blocks:
                rule = b.get("rule_name", "unknown")
                reasons[rule] = reasons.get(rule, 0) + 1

            for rule, count in sorted(reasons.items(), key=lambda x: -x[1]):
                evidence.append(Evidence(
                    key=f"autonomy.block.{rule}",
                    value=f"{count} blokad w ostatnich {len(decisions)} decyzjach",
                    source="autonomy_decisions.jsonl",
                    confidence="high",
                    timestamp=blocks[-1].get("ts", blocks[-1].get("timestamp", 0)),
                ))

        return evidence

    def _collect_goals(self) -> List[Evidence]:
        """Active goals."""
        evidence = []

        if self._goal_store:
            try:
                goals = self._goal_store.get_all()
                active = [g for g in goals if g.status.value == "active"]
                for g in active[:5]:
                    evidence.append(Evidence(
                        key=f"goal.{g.id}",
                        value=f"[{g.goal_type.value}] {g.title}",
                        source="goal_store (runtime)",
                        confidence="high", timestamp=time.time(),
                    ))
                return evidence
            except Exception:
                pass

        # Fallback: read JSONL
        goals_data = self._read_merge_jsonl("goals.jsonl")
        active = [g for g in goals_data.values() if g.get("status") == "active"]
        for g in active[:5]:
            evidence.append(Evidence(
                key=f"goal.{g.get('goal_id', '?')}",
                value=f"[{g.get('goal_type', '?')}] {g.get('title', '?')}",
                source="goals.jsonl",
                confidence="medium", timestamp=time.time(),
            ))

        return evidence

    # -- JSONL helpers --

    def _tail_jsonl(self, filename: str, limit: int = _TAIL_LIMIT) -> List[Dict]:
        """Read last N lines from a JSONL file in meta_data/."""
        path = self._meta / filename
        if not path.exists():
            return []

        try:
            entries = []
            file_size = path.stat().st_size
            with open(path, "r", encoding="utf-8") as f:
                if file_size < 500_000:  # < 500KB: read all
                    lines = f.readlines()
                else:
                    seek_pos = max(0, file_size - limit * 500)
                    f.seek(seek_pos)
                    if seek_pos > 0:
                        f.readline()
                    lines = f.readlines()

                for line in lines[-limit:]:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            return entries
        except Exception as e:
            logger.debug(f"[EvidenceCollector] _tail_jsonl({filename}) failed: {e}")
            return []

    def _read_merge_jsonl(self, filename: str) -> Dict[str, Dict]:
        """Read JSONL with MERGE semantics (last record per id wins)."""
        path = self._meta / filename
        if not path.exists():
            return {}

        merged = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        key = d.get("goal_id", d.get("id", d.get("file_id", "")))
                        if key:
                            merged[key] = d
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        return merged
