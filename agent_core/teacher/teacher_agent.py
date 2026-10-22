"""
TeacherAgent - Autonomous learning agent for M.A.R.I.A.

Decision engine with 6 priorities (1-5 pure logic, 6 NIM).
Executes learning strategies via LLMRouter (NIM/Ollama).
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.llm.work_priority import WorkPurpose, work_purpose
from agent_core.teacher.teaching_strategy import (
    TeachingStrategy,
    SpacedRepetitionScheduler,
)

logger = logging.getLogger(__name__)

# Default paths
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_PLANS_PATH = _META_DIR / "teacher_plans.jsonl"
_DEFAULT_EXAM_COOLDOWN_PATH = _META_DIR / "teacher_exam_cooldown.json"

# BUG B fix (audit 2026-05-25): after a pipeline failure on a learned file,
# park it for this long before P2 tries to exam it again. Six hours = roughly
# one Maria active-window cycle, so the next learn-attempt picks the queue
# back up without re-burning NIM on the same broken file.
_EXAM_COOLDOWN_SEC = 6 * 3600


class TeacherAgent:
    """
    Autonomous teacher that decides what to learn, test, and review.

    Decision priorities (1-5 pure logic, 6 NIM):
    1. Continue partial learning (file in "learning" status)
    2. Examine ready files (status "learned")
    3. Start new file (highest priority)
    4. Spaced repetition review (completed files due)
    5. Retry hard topics (after enough successes)
    6. NIM gap analysis (max N calls/session)
    """

    # Cap on the per-session files_touched log. The planner runs
    # max_iterations=1, so this only bounds long REPL sessions -- the record
    # travels inside every planner decision and must not grow unbounded there.
    MAX_TOUCH_LOG = 10

    def __init__(
        self,
        router,
        knowledge_analyzer: KnowledgeAnalyzer,
        plans_path: Optional[Path] = None,
        max_nim_planning_calls: int = 5,
        exam_cooldown_path: Optional[Path] = None,
    ):
        """
        Args:
            router: LLMRouter instance (NIM + Ollama)
            knowledge_analyzer: KnowledgeAnalyzer for reading JSONL state
            plans_path: Where to log teaching plans (JSONL)
            max_nim_planning_calls: Max NIM calls for gap analysis per session
            exam_cooldown_path: Where to persist per-file exam cooldown (JSON)
        """
        self.router = router
        self.analyzer = knowledge_analyzer
        self.scheduler = SpacedRepetitionScheduler()
        self.plans_path = Path(plans_path or _DEFAULT_PLANS_PATH)
        self.exam_cooldown_path = Path(exam_cooldown_path or _DEFAULT_EXAM_COOLDOWN_PATH)
        self._exam_cooldown: Dict[str, float] = self._load_exam_cooldown()

        self._max_nim_planning = max_nim_planning_calls
        self._nim_planning_used = 0
        self._running = False
        self._iteration = 0
        self._filter_file_ids: Optional[set] = None

        # Session stats
        self._stats = {
            "chunks_learned": 0,
            "exams_run": 0,
            "exams_passed": 0,
            "exam_pipeline_failures": 0,
            "reviews_done": 0,
            "strategies_executed": 0,
            "nim_planning_calls": 0,
            "errors": 0,
            # Which material this session actually touched (2026-07-21).
            # The planner calls with filter_file_ids=None for the META mission,
            # so the file is chosen INSIDE this loop and left no trace anywhere:
            # planner_decisions.jsonl records THAT a learn ran under a goal,
            # never on what. That gap is why "is the META mission eating 2/3 of
            # the planner's decisions, or is it simply the throughput ceiling?"
            # cannot be answered from the logs -- nothing says whether a
            # parallel LEARNING goal would have claimed the same file. Capped
            # (MAX_TOUCH_LOG) because this rides along in every decision record.
            "files_touched": [],
        }

        # Callbacks
        self._learn_chunk_fn: Optional[Callable] = None
        self._run_exam_fn: Optional[Callable] = None
        self._milestone_fn: Optional[Callable] = None

        # Gap-driven learning (from Critic / Auditor)
        self._critic_agent = None
        self._bulletin_store = None

    # ──────────────────────────────────────────────
    # Setup: inject learning/exam functions
    # ──────────────────────────────────────────────

    def set_learn_fn(self, fn: Callable) -> None:
        """Set the function to learn a chunk: fn(file_id, use_simple) -> Dict or None."""
        self._learn_chunk_fn = fn

    def set_exam_fn(self, fn: Callable) -> None:
        """Set the function to run exam: fn(file_id) -> Dict or None."""
        self._run_exam_fn = fn

    def set_milestone_fn(self, fn: Callable) -> None:
        """Set the learning-milestone callback: fn(file_id, score) on exam PASS.

        Optional and advisory (proactive ping); a failure here must never break
        the exam path, so the caller swallows exceptions.
        """
        self._milestone_fn = fn

    def set_critic_agent(self, critic) -> None:
        """Set CriticAgent for quality-driven learning priorities."""
        self._critic_agent = critic

    def set_bulletin_store(self, store) -> None:
        """Set BulletinStore for gap-driven learning priorities."""
        self._bulletin_store = store

    # ──────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────

    @work_purpose(WorkPurpose.BACKGROUND)
    def run_session(
        self,
        max_iterations: int = 10,
        callback: Optional[Callable[[int, str, Dict], None]] = None,
        filter_file_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run autonomous learning session.

        Args:
            max_iterations: Max decision-execute cycles
            callback: Optional fn(iteration, strategy_type, result) called after each step
            filter_file_ids: Optional list of file IDs to restrict learning to.
                If provided, Teacher only considers files in this list.
                If filtering removes all candidates, returns IDLE with reason.

        Returns:
            Session stats dict
        """
        self._running = True
        self._iteration = 0
        self._filter_file_ids = set(filter_file_ids) if filter_file_ids else None

        # Reset stats for this session (prevent cross-session accumulation)
        self._stats = {
            "chunks_learned": 0,
            "exams_run": 0,
            "exams_passed": 0,
            "exam_pipeline_failures": 0,
            "reviews_done": 0,
            "strategies_executed": 0,
            "nim_planning_calls": 0,
            "errors": 0,
            # Which material this session actually touched (2026-07-21).
            # The planner calls with filter_file_ids=None for the META mission,
            # so the file is chosen INSIDE this loop and left no trace anywhere:
            # planner_decisions.jsonl records THAT a learn ran under a goal,
            # never on what. That gap is why "is the META mission eating 2/3 of
            # the planner's decisions, or is it simply the throughput ceiling?"
            # cannot be answered from the logs -- nothing says whether a
            # parallel LEARNING goal would have claimed the same file. Capped
            # (MAX_TOUCH_LOG) because this rides along in every decision record.
            "files_touched": [],
        }

        logger.info(f"[TEACHER] Starting session (max {max_iterations} iterations)")
        if self._filter_file_ids:
            logger.info(f"[TEACHER] Topic filter active: {len(self._filter_file_ids)} files")

        while self._running and self._iteration < max_iterations:
            self._iteration += 1

            # 1. Snapshot
            snapshot = self.analyzer.get_knowledge_snapshot()

            # 2. Decide
            strategy = self._decide_next_strategy(snapshot, self._iteration)
            if strategy is None:
                logger.info("[TEACHER] No more work to do - session complete")
                break

            logger.info(
                f"[TEACHER] Iter {self._iteration}: "
                f"{strategy.strategy_type} -> {strategy.target_file_id}"
            )

            # 3. Execute
            result = self._execute_strategy(strategy)

            # 3b. Record WHAT was touched, so a decision record can later be
            # attributed to actual material (see files_touched in _stats).
            touched = self._stats["files_touched"]
            if strategy.target_file_id and len(touched) < self.MAX_TOUCH_LOG:
                touched.append({
                    "file_id": strategy.target_file_id,
                    "strategy": strategy.strategy_type,
                    "ok": bool((result or {}).get("success")),
                })

            # 4. Log
            self._log_plan(strategy, result)

            # 5. Callback
            if callback:
                try:
                    callback(self._iteration, strategy.strategy_type, result)
                except Exception as e:
                    logger.warning(f"Callback error: {e}")

            self._stats["strategies_executed"] += 1

        self._running = False
        logger.info(
            f"[TEACHER] Session complete: {self._stats['strategies_executed']} strategies, "
            f"{self._stats['chunks_learned']} chunks, "
            f"{self._stats['exams_run']} exams"
        )
        return self.get_status()

    def stop(self) -> None:
        """Stop the running session after current iteration."""
        self._running = False

    # ──────────────────────────────────────────────
    # Decision engine (priorities 1-6)
    # ──────────────────────────────────────────────

    def _find_critic_gap(self, snapshot: Dict[str, Any]) -> Optional[tuple]:
        """
        Check Critic findings for topics that match available new files.

        Returns (file_id, topic) if a gap matches, else None.
        Zero LLM cost - reads last persisted Critic report.
        """
        gap_topics = []

        # Critic findings: LEARN_MORE, REFRESH, REVIEW actions
        if self._critic_agent is not None:
            try:
                report = self._critic_agent.get_last_report()
                if report and report.findings:
                    for f in report.findings:
                        if f.suggested_action in ("learn_more", "refresh", "review"):
                            gap_topics.append(f.topic_normalized)
            except Exception:
                pass

        # Bulletin NEED_MATERIAL entries
        if self._bulletin_store is not None:
            try:
                from agent_core.bulletin.bulletin_store import EntryType
                # Audyt 2026-06-12: get_entries_by_type + .get() na dataclass
                # to byly fantomy -- sciezka martwa od 04-13, wyjatek polykany
                # nizej. Realne API: get_by_type (tylko OPEN) + entry.topic.
                needs = self._bulletin_store.get_by_type(EntryType.NEED_MATERIAL)
                for entry in needs:
                    topic = entry.topic
                    if topic:
                        gap_topics.append(topic.lower().replace(" ", "_"))
            except Exception:
                pass

        if not gap_topics:
            return None

        # Match gap topics to available new files
        new_files = snapshot.get("new_files_available", [])
        for nf in new_files:
            file_id = nf.get("id", nf.get("file", ""))
            file_lower = file_id.lower().replace("-", "_").replace(" ", "_")
            for topic in gap_topics:
                if topic in file_lower or file_lower in topic:
                    return (file_id, topic)

        return None

    def _filter_records(self, records: List[Dict]) -> List[Dict]:
        """Filter file records by topic filter if active."""
        if self._filter_file_ids is None:
            return records
        return [
            r for r in records
            if r.get("id", r.get("file", "")) in self._filter_file_ids
        ]

    def _decide_next_strategy(
        self, snapshot: Dict[str, Any], iteration: int
    ) -> Optional[TeachingStrategy]:
        """
        Choose next teaching strategy based on priorities.

        Priority order:
        1. Continue learning in progress
        2. Examine ready files
        3. Start new file
        4. Spaced repetition review
        5. Retry hard topic
        6. NIM gap analysis

        If filter_file_ids is set, all candidate lists are filtered first.
        If filtering removes all candidates, returns None with IDLE logged.
        """
        by_status = snapshot.get("files_by_status", {})

        # P1: Continue partial learning
        in_progress = self._filter_records(by_status.get("learning", []))
        if in_progress:
            target = in_progress[0]
            file_id = target.get("id", target.get("file", ""))
            return TeachingStrategy(
                TeachingStrategy.LEARN_NEW,
                file_id,
                params={"reason": "continue_partial",
                        "chunks_done": target.get("chunks_learned", 0),
                        "chunks_total": target.get("total_chunks", 0)},
            )

        # P2: Examine ready files
        ready_for_exam = self._filter_records(by_status.get("learned", []))
        # BUG B fix (audit 2026-05-25): drop files whose exam pipeline failed
        # within _EXAM_COOLDOWN_SEC. Stops Maria re-burning NIM on a broken
        # learned file while the new-file queue starves.
        ready_for_exam = [
            r for r in ready_for_exam
            if not self._is_in_exam_cooldown(r.get("id", r.get("file", "")))
        ]
        if ready_for_exam:
            target = ready_for_exam[0]
            file_id = target.get("id", target.get("file", ""))
            return TeachingStrategy(
                TeachingStrategy.REVIEW,
                file_id,
                params={"reason": "exam_ready"},
            )

        # P2.4: Second chance for first-fail exams. exam_agent marks attempt 1
        # as exam_failed ("druga szansa") and only attempt 2+ as hard_topic;
        # the legacy REPL loop retried exam_failed (learning_agent candidates)
        # but this port only looked at hard_topic, so first-fail files sat
        # forever -- 216 files stuck at exam_attempts=1 by 2026-08-09.
        # FILL_GAP on such a file is a no-op re-learn that flips it to
        # "learned", so P2 re-examines it; attempt 2 always exits the bucket
        # (pass -> completed, fail -> hard_topic).
        second_chance = self._filter_records(by_status.get("exam_failed", []))
        if second_chance:
            target = second_chance[0]
            file_id = target.get("id", target.get("file", ""))
            return TeachingStrategy(
                TeachingStrategy.FILL_GAP,
                file_id,
                params={"reason": "exam_failed_second_chance",
                        "attempts": target.get("exam_attempts", 0)},
            )

        # P2.5: Retry hard topics before starting new content
        # (was P5 with completed_count >= 3 gate - too late)
        hard_topics = self._filter_records(by_status.get("hard_topic", []))
        if hard_topics:
            target = hard_topics[0]
            file_id = target.get("id", target.get("file", ""))
            return TeachingStrategy(
                TeachingStrategy.FILL_GAP,
                file_id,
                params={"reason": "weak_topic_priority",
                        "attempts": target.get("exam_attempts", 0)},
            )

        # P2.7: Gap-driven learning (Critic/Bulletin say what's missing)
        if self._filter_file_ids is None:
            gap_file = self._find_critic_gap(snapshot)
            if gap_file:
                return TeachingStrategy(
                    TeachingStrategy.LEARN_NEW,
                    gap_file[0],
                    params={"reason": "critic_gap", "topic": gap_file[1]},
                )

        # P3: Start new file
        new_files = self._filter_records(
            snapshot.get("new_files_available", [])
        )
        if new_files:
            target = new_files[0]  # Already sorted by priority (desc)
            file_id = target.get("id", target.get("file", ""))
            return TeachingStrategy(
                TeachingStrategy.LEARN_NEW,
                file_id,
                params={"reason": "new_file",
                        "priority": target.get("priority", 0)},
            )

        # P4: Spaced repetition
        due_reviews = self._filter_records(
            self.scheduler.get_due_reviews(snapshot)
        )
        if due_reviews:
            target = due_reviews[0]
            file_id = target.get("id", target.get("file", ""))
            scores = target.get("last_scores", [])
            return TeachingStrategy(
                TeachingStrategy.REVIEW,
                file_id,
                params={"reason": "spaced_repetition",
                        "last_score": scores[-1] if scores else 0},
            )

        # P5: (moved to P2.5 - hard topics now prioritized before new content)

        # P6: NIM gap analysis (skip if topic-filtered - NIM doesn't know about filter)
        if self._filter_file_ids is None and self._nim_planning_used < self._max_nim_planning:
            strategy = self._nim_analyze_gaps(snapshot)
            if strategy:
                return strategy

        # Nothing to do - log reason if filtered
        if self._filter_file_ids is not None:
            # Count how many total candidates were filtered out
            total_unfiltered = (
                len(by_status.get("learning", []))
                + len(by_status.get("learned", []))
                + len(snapshot.get("new_files_available", []))
                + len(by_status.get("exam_failed", []))
                + len(by_status.get("hard_topic", []))
            )
            if total_unfiltered > 0:
                logger.info(
                    f"[TEACHER] IDLE: filtered_out_all_candidates "
                    f"(removed {total_unfiltered} candidates, "
                    f"filter has {len(self._filter_file_ids)} file_ids)"
                )
                self._stats["idle_reason"] = "filtered_out_all_candidates"
                self._stats["filtered_out_count"] = total_unfiltered

        return None

    def _nim_analyze_gaps(
        self, snapshot: Dict[str, Any]
    ) -> Optional[TeachingStrategy]:
        """
        Use NIM for advanced gap analysis.

        Called only when basic logic finds nothing to do.
        Max calls per session limited by _max_nim_planning.

        Returns:
            TeachingStrategy or None
        """
        if not hasattr(self.router, "_ask_once"):
            return None

        gaps = self.analyzer.find_knowledge_gaps()
        if not gaps:
            return None

        compact = self.analyzer.get_compact_summary()
        gap_text = "\n".join(
            f"- {g['type']}: {g['file_id']} (priority: {g['priority']})"
            for g in gaps[:5]
        )

        prompt = (
            "Jestes nauczycielem AI. Oto stan wiedzy ucznia:\n"
            f"{compact}\n\n"
            f"Znalezione luki:\n{gap_text}\n\n"
            "Ktory temat powinien byc nastepny? "
            "Odpowiedz jednym slowem: ID pliku do nauki."
        )

        try:
            response = self.router._ask_once(prompt, temperature=0.3)
            self._nim_planning_used += 1
            self._stats["nim_planning_calls"] += 1

            # Reasoning journal: keep the teacher's prose, not just the
            # file_id extracted below.
            try:
                from agent_core.tracing.reasoning_journal import (
                    get_reasoning_journal,
                )
                get_reasoning_journal().record(
                    source="teacher.nim_gap",
                    reasoning=response,
                    prompt_hint=prompt,
                )
            except Exception:
                pass

            # Try to match response to a gap file_id
            response_lower = response.strip().lower()
            for gap in gaps:
                if gap["file_id"].lower() in response_lower:
                    strategy_type = (
                        TeachingStrategy.FILL_GAP
                        if gap["type"] in ("low_score", "exam_failed")
                        else TeachingStrategy.DEEPEN
                        if gap["type"] == "partial"
                        else TeachingStrategy.REVIEW
                    )
                    return TeachingStrategy(
                        strategy_type,
                        gap["file_id"],
                        params={"reason": "nim_gap_analysis",
                                "gap_type": gap["type"]},
                    )

            # Fallback: use first gap
            if gaps:
                return TeachingStrategy(
                    TeachingStrategy.FILL_GAP,
                    gaps[0]["file_id"],
                    params={"reason": "nim_gap_analysis_fallback",
                            "gap_type": gaps[0]["type"]},
                )

        except Exception as e:
            logger.warning(f"NIM gap analysis failed: {e}")
            self._stats["errors"] += 1

        return None

    # ──────────────────────────────────────────────
    # Strategy execution
    # ──────────────────────────────────────────────

    def _execute_strategy(self, strategy: TeachingStrategy) -> Dict[str, Any]:
        """Execute a teaching strategy, return result dict."""
        try:
            if strategy.strategy_type == TeachingStrategy.LEARN_NEW:
                return self._exec_learn(strategy)
            elif strategy.strategy_type == TeachingStrategy.REVIEW:
                return self._exec_review(strategy)
            elif strategy.strategy_type == TeachingStrategy.DEEPEN:
                return self._exec_learn(strategy)  # Same as learn but may use simple
            elif strategy.strategy_type == TeachingStrategy.FILL_GAP:
                return self._exec_fill_gap(strategy)
            else:
                return {"success": False, "error": f"Unknown strategy: {strategy.strategy_type}"}
        except Exception as e:
            logger.error(f"Strategy execution error: {e}")
            self._stats["errors"] += 1
            return {"success": False, "error": str(e)}

    def _exec_learn(self, strategy: TeachingStrategy) -> Dict[str, Any]:
        """Execute LEARN_NEW or DEEPEN strategy."""
        file_id = strategy.target_file_id

        if self._learn_chunk_fn is None:
            return {"success": False, "error": "No learn function configured"}

        use_simple = strategy.params.get("reason") == "retry_hard_topic"
        result = self._learn_chunk_fn(file_id, use_simple)

        # LABEL FIX, same shape as _exec_review's (2026-08-12): when the named
        # file is not learnable, selection falls back to priority and a DIFFERENT
        # file gets learned. Reporting strategy.target then credits progress to a
        # file nothing happened to.
        learned_id = (result or {}).get("file_id") or file_id

        if result and result.get("success", False):
            self._stats["chunks_learned"] += 1
            return {"success": True, "file_id": learned_id, "type": "learn",
                    "requested_file_id": file_id}

        # "Nothing to learn" is idle, not broken. It must carry the skip flag all
        # the way up: the self-repair failure-storm detector counts
        # `success is False and not skipped`, so labelling an idle tick a failure
        # would manufacture an incident out of a quiet queue.
        if result and result.get("skipped"):
            return {"success": False, "skipped": True, "file_id": learned_id,
                    "type": "learn", "reason": result.get("reason", ""),
                    "requested_file_id": file_id}

        return {"success": False, "file_id": learned_id, "type": "learn",
                "requested_file_id": file_id,
                "error": result.get("error", "learn failed") if result else "learn returned None"}

    def _exec_review(self, strategy: TeachingStrategy) -> Dict[str, Any]:
        """Execute REVIEW strategy (run exam)."""
        file_id = strategy.target_file_id

        if self._run_exam_fn is None:
            return {"success": False, "error": "No exam function configured"}

        result = self._run_exam_fn(file_id)

        # LABEL FIX (2026-08-12): the STAGED pipeline deliberately resumes an
        # in-flight exam FIRST, even when the strategy names a different file
        # (exam_agent.run_exam_if_ready). So the file that was actually examined
        # is the one the result reports -- never assume it is strategy.target.
        # Measured drift: 2026-08-12 13:24 the plan log credited score 1.0 to
        # efekt_cieplarniany while exam_results.jsonl (and the index) show the
        # 1.0 belonged to prawo_administracyjne. Cosmetic in the log, but the
        # failure branch below parks a file in exam cooldown -- with the wrong
        # id it benched a HEALTHY file and left the broken one eligible, which
        # is precisely the loop that cooldown (BUG B, 2026-05-25) exists to stop.
        examined_id = (result or {}).get("file_id") or file_id

        if result and result.get("skipped"):
            # Thermal start-gate (2026-08-10): cooling is active, so no exam
            # stage ran at all. NOT a pipeline failure -- no failure counter,
            # no exam cooldown; the file stays eligible and the next session
            # retries on a cooler CPU.
            logger.info(f"[EXAM] Deferred (thermal) for {file_id}")
            return {"success": False, "skipped": True, "file_id": file_id,
                    "type": "exam", "reason": result.get("reason", "deferred")}

        if result and result.get("staged"):
            # Staged pipeline (2026-08-10): one heavy stage ran and persisted
            # its state; the exam completes in a later session. Real work, but
            # exams_run counts COMPLETED exams only.
            self._stats["exam_stages_run"] = (
                self._stats.get("exam_stages_run", 0) + 1)
            logger.info(
                f"[EXAM] Stage '{result['staged']}' done for {examined_id}")
            return {"success": True, "file_id": examined_id,
                    "type": "exam_stage", "stage": result["staged"]}

        if result and result.get("success", False):
            self._stats["exams_run"] += 1
            if result.get("passed", False):
                self._stats["exams_passed"] += 1
                # Learning milestone: Maria passed -> proactively tell the operator.
                # Advisory only; never let a notify hiccup break the exam path.
                if self._milestone_fn is not None:
                    try:
                        self._milestone_fn(examined_id, result.get("score", 0))
                    except Exception as e:
                        logger.debug(f"milestone_fn failed: {e}")
            self._stats["reviews_done"] += 1
            self._stats["last_exam_score"] = result.get("score", 0)
            self._stats["last_exam_file"] = examined_id
            return {"success": True, "file_id": examined_id, "type": "exam",
                    "score": result.get("score", 0),
                    "passed": result.get("passed", False)}
        else:
            # BUG A fix (audit 2026-05-25): track pipeline failures separately
            # so K9/K12 can see the true attempt count. exams_run stays as
            # "successful executions"; exam_pipeline_failures counts attempts
            # where run_exam_fn returned but executed=False (parser truncation,
            # LLM timeout, etc.). Without this, exams_run=0 hides the loop and
            # the planner happily retries 30+ times in a single window.
            self._stats["exam_pipeline_failures"] += 1
            err_msg = result.get("error", "exam failed") if result else "exam returned None"
            logger.warning(
                f"[EXAM] Pipeline failure for {examined_id}: {err_msg} "
                f"(session failures: {self._stats['exam_pipeline_failures']})"
            )
            # BUG B fix (audit 2026-05-25): park this file so P2 stops picking
            # it back up next iteration. Without cooldown the planner re-picks
            # the same learned-but-broken file every window and the new-file
            # queue starves. Park the file that ACTUALLY ran (see examined_id
            # above) -- parking strategy.target instead benched a healthy file
            # and let the broken one loop.
            self._mark_exam_cooldown(examined_id)
            return {"success": False, "file_id": examined_id, "type": "exam",
                    "error": err_msg}

    def _exec_fill_gap(self, strategy: TeachingStrategy) -> Dict[str, Any]:
        """Execute FILL_GAP strategy (re-learn with simple prompt)."""
        file_id = strategy.target_file_id

        if self._learn_chunk_fn is None:
            return {"success": False, "error": "No learn function configured"}

        # Fill gap = learn with simple prompt
        result = self._learn_chunk_fn(file_id, True)

        if result and result.get("success", False):
            self._stats["chunks_learned"] += 1
            return {"success": True, "file_id": file_id, "type": "fill_gap"}
        else:
            return {"success": False, "file_id": file_id, "type": "fill_gap",
                    "error": result.get("error", "fill_gap failed") if result else "fill_gap returned None"}

    # ──────────────────────────────────────────────
    # LLM helper (for strategies needing direct LLM)
    # ──────────────────────────────────────────────

    def _call_llm(self, prompt: str, temperature: float = 0.3) -> Optional[str]:
        """Central LLM call point via router."""
        try:
            return self.router._ask_once(prompt, temperature=temperature)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    # ──────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────

    def _load_exam_cooldown(self) -> Dict[str, float]:
        """Load persisted per-file exam cooldown timestamps."""
        try:
            if self.exam_cooldown_path.exists():
                with open(self.exam_cooldown_path, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {k: float(v) for k, v in data.items()}
        except (IOError, ValueError, TypeError) as e:
            logger.warning(f"Could not load exam cooldown: {e}")
        return {}

    def _save_exam_cooldown(self) -> None:
        """Persist current exam cooldown map."""
        try:
            self.exam_cooldown_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.exam_cooldown_path, "w", encoding="utf-8") as f:
                json.dump(self._exam_cooldown, f, indent=2)
        except IOError as e:
            logger.warning(f"Could not save exam cooldown: {e}")

    def _is_in_exam_cooldown(self, file_id: str) -> bool:
        """Return True if file_id had a pipeline failure within cooldown window."""
        ts = self._exam_cooldown.get(file_id)
        if ts is None:
            return False
        return (time.time() - ts) < _EXAM_COOLDOWN_SEC

    def _mark_exam_cooldown(self, file_id: str) -> None:
        """Record a pipeline-failure timestamp and persist."""
        self._exam_cooldown[file_id] = time.time()
        self._save_exam_cooldown()

    def _log_plan(self, strategy: TeachingStrategy, result: Dict[str, Any]) -> None:
        """Log strategy + result to JSONL."""
        try:
            self.plans_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": time.time(),
                "iteration": self._iteration,
                "strategy": strategy.to_dict(),
                "result": result,
            }
            with open(self.plans_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.warning(f"Could not log plan: {e}")

    # ──────────────────────────────────────────────
    # Status & preview
    # ──────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get current session status."""
        return {
            "running": self._running,
            "iteration": self._iteration,
            "nim_planning_used": self._nim_planning_used,
            "nim_planning_limit": self._max_nim_planning,
            "stats": dict(self._stats),
        }

    def get_next_plan_preview(self) -> Optional[Dict[str, Any]]:
        """Preview what the next strategy would be (without executing)."""
        snapshot = self.analyzer.get_knowledge_snapshot()
        strategy = self._decide_next_strategy(snapshot, self._iteration + 1)
        if strategy:
            return {
                "strategy_type": strategy.strategy_type,
                "target_file_id": strategy.target_file_id,
                "params": strategy.params,
            }
        return None

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Load recent plans from JSONL."""
        if not self.plans_path.exists():
            return []
        records = []
        try:
            with open(self.plans_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except IOError:
            return []
        return records[-limit:]
