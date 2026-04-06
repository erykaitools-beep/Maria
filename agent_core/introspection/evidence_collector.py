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
        self._memory_query = None
        self._vision_cortex = None

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

    def set_memory_query(self, mq):
        self._memory_query = mq

    def set_vision_cortex(self, vc):
        self._vision_cortex = vc

    # -- Public API --

    def collect_for_mode(self, mode: ResponseMode, query_text: str = "") -> List[Evidence]:
        """Collect evidence relevant to the given response mode."""
        collectors = {
            ResponseMode.GROUNDED_STATUS: self.collect_status,
            ResponseMode.GROUNDED_ERROR: self.collect_error,
            ResponseMode.GROUNDED_LEARNING: self.collect_learning,
            ResponseMode.GROUNDED_PLANNER: self.collect_planner,
            ResponseMode.GROUNDED_VISION: self.collect_vision,
        }

        # Knowledge mode needs the query text to extract topic
        if mode == ResponseMode.GROUNDED_KNOWLEDGE:
            return self.collect_knowledge(query_text)
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
        """Learning: files, chunks, exams, retention, strategy, gaps."""
        evidence = []

        evidence.extend(self._collect_learning_summary())
        evidence.extend(self._collect_recent_exams())
        evidence.extend(self._collect_planner_last())
        evidence.extend(self._collect_evaluation_metrics())
        evidence.extend(self._collect_knowledge_gaps())

        return evidence

    def collect_planner(self) -> List[Evidence]:
        """Planner: active goal, strategy, recent decisions."""
        evidence = []

        evidence.extend(self._collect_planner_last())
        evidence.extend(self._collect_planner_failures())
        evidence.extend(self._collect_goals())

        return evidence

    def collect_knowledge(self, query_text: str) -> List[Evidence]:
        """Knowledge: what Maria knows about a topic (Phase 2 MemoryQuery)."""
        evidence = []

        # Extract topic from query (remove common prefixes)
        topic = query_text.lower().strip()
        for prefix in ("co wiesz o ", "co wiesz na temat ", "co znasz ",
                       "powiedz mi o ", "opowiedz o ", "opowiedz mi o ",
                       "what do you know about ", "tell me about ",
                       "ile wiesz o ", "jak dobrze znasz "):
            if topic.startswith(prefix):
                topic = topic[len(prefix):].strip().rstrip("?.,!")
                break

        if not topic or len(topic) < 2:
            evidence.append(Evidence(
                key="knowledge.query",
                value="Nie rozumiem o czym pytasz.",
                source="memory_query",
                confidence="low",
            ))
            return evidence

        if not self._memory_query:
            evidence.append(Evidence(
                key="knowledge.query",
                value=f"MemoryQuery niedostepny, nie moge sprawdzic wiedzy o: {topic}",
                source="memory_query",
                confidence="low",
            ))
            return evidence

        try:
            results = self._memory_query.query_topic(topic, top_k=8)
            summary = self._memory_query.get_topic_summary(topic)

            if not summary.get("known"):
                evidence.append(Evidence(
                    key="knowledge.topic_status",
                    value=f"Nie mam wiedzy na temat: {topic}",
                    source="memory_query",
                    confidence="high",
                ))
                return evidence

            avg_conf = summary.get("avg_confidence", 0)
            conf_str = "high" if avg_conf >= 0.7 else ("medium" if avg_conf >= 0.4 else "low")
            evidence.append(Evidence(
                key="knowledge.topic_summary",
                value=(
                    f"Temat '{topic}': "
                    f"{summary.get('files_count', 0)} plikow, "
                    f"{summary.get('beliefs_count', 0)} przekonan, "
                    f"pewnosc: {avg_conf:.0%}, "
                    f"swiezosc: {summary.get('freshness', 0):.0%}"
                ),
                source="memory_query",
                confidence=conf_str,
            ))

            for r in results[:5]:
                conf_str = "high" if r.confidence >= 0.7 else ("medium" if r.confidence >= 0.4 else "low")
                evidence.append(Evidence(
                    key=f"knowledge.{r.source.value}",
                    value=r.content,
                    source=r.provenance.get("source", r.source.value),
                    confidence=conf_str,
                ))

        except Exception as e:
            logger.debug(f"[EvidenceCollector] knowledge query failed: {e}")

        return evidence

    def collect_vision(self) -> List[Evidence]:
        """Vision: what Maria sees through her camera.

        On-demand: triggers LLaVA snap for natural language scene description.
        Fallback: sensor statistics (lighting, colors, motion, quality).
        """
        evidence = []

        # Try live cortex first, then state file
        last = None
        source = "vision_cortex"
        if self._vision_cortex:
            last = self._vision_cortex.last_percept

        # On-demand LLaVA description (fresh frame, ~30s)
        llava_desc = None
        if self._vision_cortex:
            try:
                llava_desc = self._vision_cortex.describe_scene_llava()
            except Exception as e:
                logger.debug(f"[EvidenceCollector] LLaVA snap failed: {e}")

        if llava_desc:
            evidence.append(Evidence(
                key="vision_scene",
                value=llava_desc,
                source="llava",
                confidence=0.85,
            ))
            evidence.append(Evidence(
                key="vision_summary",
                value=f"Moje oko (kamera USB) widzi: {llava_desc}",
                source="llava",
                confidence=0.85,
            ))
        elif last:
            # Fallback: stats-based description from last tick
            parts = []
            if last.scene:
                s = last.scene
                lighting_pl = {
                    "bright": "jasno", "very_bright": "bardzo jasno",
                    "dim": "przyciemnione", "dark": "ciemno",
                }.get(s.lighting, s.lighting)
                colors_pl = ", ".join(s.dominant_colors[:3])
                parts.append(f"Jest {lighting_pl}")
                parts.append(f"dominujace kolory: {colors_pl}")
                if s.complexity > 0.7:
                    parts.append("widze wiele szczegulow i krawedzi")
                elif s.complexity < 0.3:
                    parts.append("obraz jest prosty, niewiele elementow")

            if last.motion and last.motion.motion_detected:
                cls_pl = {
                    "person_movement": "ruch osoby",
                    "object_movement": "ruch obiektu",
                    "camera_shake": "drgania kamery",
                }.get(last.motion.classification.value, "ruch")
                parts.append(f"wykrywam {cls_pl} (poziom {last.motion.motion_level:.0%})")
            elif last.motion:
                parts.append("nie wykrywam ruchu")

            description = ". ".join(parts) + "." if parts else last.summary
            evidence.append(Evidence(
                key="vision_summary",
                value=f"Moje oko (kamera USB) widzi: {description}",
                source=source,
                confidence=0.9,
            ))

        if last:
            evidence.append(Evidence(
                key="vision_quality",
                value=f"jakosc obrazu {last.quality:.0%}, zdrowie sensora {last.vision_health.overall:.0%}",
                source=source,
                confidence=0.9,
            ))
        else:
            # Try state file fallback
            try:
                state_path = Path(self._project_root) / "meta_data" / "vision_state.json"
                if state_path.exists():
                    import json as _json
                    with open(state_path, "r", encoding="utf-8") as f:
                        state = _json.loads(f.read())
                    percept = state.get("last_percept", {})
                    scene = percept.get("scene", {})
                    if scene:
                        lighting = scene.get("lighting", "unknown")
                        colors = ", ".join(scene.get("dominant_colors", []))
                        motion = percept.get("motion", {})
                        motion_str = "nie wykrywam ruchu" if not motion.get("motion_detected") else "wykrywam ruch"
                        evidence.append(Evidence(
                            key="vision_summary",
                            value=f"Moje oko (kamera USB) widzi: oswietlenie {lighting}, kolory: {colors}, {motion_str}.",
                            source="vision_state.json",
                            confidence=0.8,
                        ))
                    elif percept.get("summary"):
                        evidence.append(Evidence(
                            key="vision_summary",
                            value=f"Moje oko (kamera USB) widzi: {percept['summary']}",
                            source="vision_state.json",
                            confidence=0.8,
                        ))
            except Exception:
                pass

        if not evidence:
            evidence.append(Evidence(
                key="vision_summary",
                value="Kamera jest podlaczona ale nie mam jeszcze danych z obrazu.",
                source="vision_cortex",
                confidence=0.5,
            ))

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
        pf = self._collect_planner_failures()
        if pl:
            action_ev = next((e for e in pl if e.key == "planner.last_action"), None)
            if action_ev:
                parts.append(f"Ostatnia akcja: {action_ev.value}")
        # NOOP loop warning in summary
        noop_ev = next((e for e in pf if e.key == "planner.noop_loop"), None)
        if noop_ev:
            parts.append(f"UWAGA: {noop_ev.value}")

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

        # Detect NOOP loop pattern (common stuck state)
        noop_count = sum(1 for d in decisions if d.get("action_type") == "noop")
        if noop_count >= 10:
            # Identify which goal is stuck
            noop_goals = {}
            for d in decisions:
                if d.get("action_type") == "noop":
                    gid = d.get("goal_id", "unknown")
                    noop_goals[gid] = noop_goals.get(gid, 0) + 1
            stuck_goal = max(noop_goals, key=noop_goals.get) if noop_goals else "?"
            evidence.append(Evidence(
                key="planner.noop_loop",
                value=f"{noop_count}/{len(decisions)} ostatnich decyzji to NOOP "
                      f"(cel: {stuck_goal[:20]}). Planner nie ma co robic - "
                      f"brak nowych materialow lub cel jest zbyt abstrakcyjny.",
                source="planner_decisions.jsonl",
                confidence="high",
                timestamp=decisions[-1].get("timestamp", 0),
            ))

        # Detect low action diversity
        action_counts = {}
        for d in decisions:
            a = d.get("action_type", "?")
            action_counts[a] = action_counts.get(a, 0) + 1
        if len(action_counts) <= 2 and len(decisions) >= 15:
            dominant = max(action_counts, key=action_counts.get)
            evidence.append(Evidence(
                key="planner.low_diversity",
                value=f"Monotonna aktywnosc: {dominant} stanowi "
                      f"{action_counts[dominant]}/{len(decisions)} decyzji.",
                source="planner_decisions.jsonl",
                confidence="medium",
                timestamp=decisions[-1].get("timestamp", 0),
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

    def _collect_knowledge_gaps(self) -> List[Evidence]:
        """Knowledge gaps from MemoryQuery and world model."""
        evidence = []

        # From MemoryQuery
        if self._memory_query:
            try:
                gaps = self._memory_query.get_knowledge_gaps()
                if gaps:
                    gap_topics = [g.get("topic", "?") for g in gaps[:5]]
                    evidence.append(Evidence(
                        key="learning.knowledge_gaps",
                        value=f"{len(gaps)} luk: {', '.join(gap_topics)}",
                        source="memory_query",
                        confidence="high", timestamp=time.time(),
                    ))
            except Exception:
                pass

        # From bulletin board (open needs)
        bulletin_path = self._meta / "cognitive_bulletin.jsonl"
        if bulletin_path.exists():
            try:
                open_needs = []
                with open(bulletin_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = __import__("json").loads(line)
                            if entry.get("status") == "open":
                                topic = entry.get("topic", "?")[:40]
                                open_needs.append(topic)
                        except Exception:
                            continue
                if open_needs:
                    evidence.append(Evidence(
                        key="learning.open_needs",
                        value=f"{len(open_needs)} otwartych potrzeb: {', '.join(open_needs[:3])}",
                        source="cognitive_bulletin.jsonl",
                        confidence="high", timestamp=time.time(),
                    ))
            except Exception:
                pass

        # From critique findings
        critique_path = self._meta / "critique_reports.jsonl"
        if critique_path.exists():
            try:
                last_line = ""
                with open(critique_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            last_line = line.strip()
                if last_line:
                    report = __import__("json").loads(last_line)
                    findings = report.get("findings", [])
                    if findings:
                        categories = [f.get("category", "?") for f in findings[:3]]
                        evidence.append(Evidence(
                            key="learning.critique_findings",
                            value=f"{len(findings)} problemow jakosci: {', '.join(categories)}",
                            source="critique_reports.jsonl",
                            confidence="high",
                            timestamp=report.get("timestamp", 0),
                        ))
            except Exception:
                pass

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
