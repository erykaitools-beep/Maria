"""Creative Module facade - public entry points.

Public methods:
    reflect()                  - Run full reflection cycle (detect -> insight -> propose)
    should_reflect()           - Check if conditions warrant reflection
    get_status()               - Module status summary
    set_llm_fn()               - Late-wire LLM function for Phase 2 engines

Integration:
    - Called by Planner via ActionType.CREATIVE
    - Phase 11 in tick loop (after planner, before sleep)
    - Outputs: GoalStore PROPOSED items, journal entries, reframes, explorations

Cooldowns:
    - Minimum 2h between reflections
    - Max 3 meta-goals per cycle
    - Category cooldown 12h (same tension type)

Phase 2: LLM-enhanced engines (NIM API) with rule-based fallback.
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from agent_core.creative.creative_model import MetaGoalStatus
from agent_core.creative.creative_store import CreativeStore
from agent_core.creative.strategic_context import StrategicContext
from agent_core.creative.tension_detector import TensionDetector
from agent_core.creative.reflection_workspace import ReflectionWorkspaceManager
from agent_core.creative.creative_journal import CreativeJournal
from agent_core.creative.novelty_filter import NoveltyFilter
from agent_core.creative.creative_evaluator import CreativeEvaluator
from agent_core.creative.goal_adapter import GoalAdapter
from agent_core.creative import creative_events as events

# Phase 2 imports
from agent_core.creative.identity_profile import IdentityProfile
from agent_core.creative.personality_policy import PersonalityPolicy
from agent_core.creative.memory_retriever import MemoryRetriever
from agent_core.creative.memory_summarizer import MemorySummarizer
from agent_core.creative.meta_goal_engine import MetaGoalEngine
from agent_core.creative.reframe_engine import ReframeEngine
from agent_core.creative.exploration_engine import ExplorationEngine
from agent_core.creative.loop_detector import LoopDetector  # D3

logger = logging.getLogger(__name__)

# Cooldown: minimum time between reflection cycles
MIN_REFLECTION_INTERVAL_SEC = 7200  # 2h
# For debugging/testing, can be lowered
DEBUG_INTERVAL_SEC = 300  # 5min


class CreativeModule:
    """Facade for the Creative Module (K13).

    Phase 1: Rule-based reflection (zero LLM, 42ms/cycle).
    Phase 2: LLM-enhanced engines with rule-based fallback.
    """

    def __init__(self, data_dir: str = "meta_data", memory_dir: str = "memory",
                 goal_store=None, llm_fn: Optional[Callable[[str], str]] = None):
        # Core components (Phase 1)
        self._store = CreativeStore(data_dir)
        self._context_builder = StrategicContext(data_dir, memory_dir)
        self._tension_detector = TensionDetector()
        self._workspace_mgr = ReflectionWorkspaceManager()
        self._journal = CreativeJournal(self._store)
        self._novelty_filter = NoveltyFilter(self._store)
        self._evaluator = CreativeEvaluator()
        self._goal_adapter = GoalAdapter(goal_store)

        # Phase 2 components
        self._identity_profile = IdentityProfile(data_dir, memory_dir)
        self._personality_policy = PersonalityPolicy()
        self._memory_retriever = MemoryRetriever(self._store)
        self._memory_summarizer = MemorySummarizer(llm_fn)
        self._meta_goal_engine = MetaGoalEngine(llm_fn)
        self._reframe_engine = ReframeEngine(llm_fn)
        self._exploration_engine = ExplorationEngine(llm_fn)

        # D3: LoopDetector — short-circuits abandoned-pattern regeneration.
        self._loop_detector = LoopDetector(goal_store=goal_store)
        self._bulletin_store = None

        # State
        self._last_reflection_ts: float = 0.0
        self._total_reflections: int = 0
        self._total_meta_goals_proposed: int = 0
        self._total_meta_goals_suppressed: int = 0  # D3
        self._total_tensions_detected: int = 0
        self._total_reframes: int = 0
        self._total_explorations: int = 0
        self._has_llm: bool = llm_fn is not None

    def set_goal_store(self, goal_store) -> None:
        """Wire GoalStore after initialization."""
        self._goal_adapter.set_goal_store(goal_store)
        self._loop_detector.set_goal_store(goal_store)

    def set_bulletin_store(self, store) -> None:
        """Wire BulletinStore: creative meta-goals post IMPROVEMENT advisories
        (R1) and suppressed loops are surfaced to operator (D3)."""
        self._bulletin_store = store
        self._goal_adapter.set_bulletin_store(store)
        # D3 now measures recurrence from creative advisories (post-R1), not the
        # dead GoalStore source -- without this it silently counts 0 and the same
        # ideas spam forever (diagnosed 2026-06-28).
        self._loop_detector.set_bulletin_store(store)

    def set_llm_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        """Wire LLM function for Phase 2 engines (late wiring)."""
        self._has_llm = fn is not None
        self._memory_summarizer.set_llm_fn(fn)
        self._meta_goal_engine.set_llm_fn(fn)
        self._reframe_engine.set_llm_fn(fn)
        self._exploration_engine.set_llm_fn(fn)

    def set_expert_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        """Wire expert LLM (ChatGPT) for richer creative exploration."""
        self._exploration_engine.set_expert_fn(fn)

    def should_reflect(self) -> bool:
        """Check if conditions warrant a reflection cycle.

        Returns True if:
        1. Cooldown has elapsed
        2. System is in a state that benefits from reflection
        """
        now = time.time()
        if now - self._last_reflection_ts < MIN_REFLECTION_INTERVAL_SEC:
            return False
        return True

    def reflect(self, trigger: str = "periodic") -> Dict[str, Any]:
        """
        Run a full reflection cycle (Phase 2 enhanced).

        Steps:
        1. Build strategic context
        2. Detect tensions
        3. Create reflection session
        4. Form insights from tensions
        4.5 Retrieve relevant memories (Phase 2)
        4.6 Build memory summary (Phase 2)
        4.7 Build cognitive profile (Phase 2)
        5. Generate candidate meta-goals (LLM-enhanced)
        5.5 Generate reframes (Phase 2)
        5.6 Generate explorations (Phase 2)
        6. Filter for novelty
        7. Evaluate candidates
        7.5 Personality check (Phase 2)
        8. Promote to GoalStore
        9. Write journal entry
        10. Persist workspace summary

        Args:
            trigger: Why reflection was triggered

        Returns:
            Summary dict of the reflection cycle.
        """
        start = time.time()
        logger.info(f"[CREATIVE] Starting reflection cycle (trigger: {trigger})")

        # Cooldown clock starts at ATTEMPT, not at success (2026-07-06): a
        # cycle that dies mid-way (NIM timeout mid-generation) must still
        # consume its 2h slot, otherwise a nightly outage turns the ~60s
        # planner cadence into an unbounded retry storm of context builds
        # and partial LLM calls.
        self._last_reflection_ts = start

        # 1. Build context
        context = self._context_builder.build(period_hours=24.0)

        # 2. Detect tensions
        tensions = self._tension_detector.detect(context)
        self._total_tensions_detected += len(tensions)

        # Log tension events
        for t in tensions:
            self._store.log_event(events.TENSION_DETECTED, {
                "tension_id": t.tension_id,
                "category": t.category.value,
                "severity": t.severity,
            })

        # Record tension categories for streak tracking
        tension_cats = [t.category.value for t in tensions]
        self._store.record_tensions(tension_cats)

        if not tensions:
            logger.info("[CREATIVE] No tensions detected, skipping reflection")
            self._last_reflection_ts = time.time()
            self._total_reflections += 1
            return {
                "success": True,
                "tensions": 0,
                "insights": 0,
                "meta_goals_proposed": 0,
                "meta_goals_promoted": 0,
                "reframes": 0,
                "explorations": 0,
                "duration_ms": (time.time() - start) * 1000,
                "trigger": trigger,
            }

        # 3. Create reflection session
        session = self._workspace_mgr.create_session(
            trigger=trigger,
            problem_statement=self._build_problem_statement(tensions, context),
        )
        for t in tensions:
            session.add_tension(t)

        # 4. Form insights
        insights = self._workspace_mgr.form_insights(session)
        for i in insights:
            self._store.log_event(events.INSIGHT_FORMED, {
                "insight_id": i.insight_id,
                "confidence": i.confidence,
                "meta_goal_candidate": i.meta_goal_candidate,
            })

        # 4.5 Retrieve relevant memories (Phase 2)
        retrieved_memories = self._memory_retriever.retrieve_for_session(
            tensions, context
        )

        # 4.6 Build memory summary (Phase 2)
        memories_summary = self._memory_summarizer.summarize(retrieved_memories)

        # 4.7 Build cognitive profile (Phase 2)
        profile = self._identity_profile.build()

        # 5. Generate candidate meta-goals (LLM-enhanced)
        candidates = self._workspace_mgr.generate_candidates(
            session, context, meta_goal_engine=self._meta_goal_engine,
            memories_summary=memories_summary,
            tension_streak_fn=self._store.get_tension_streak,
        )

        # 5.5 Generate reframes (Phase 2)
        reframes = self._reframe_engine.generate_reframes(
            tensions, context, memories_summary
        )
        for rf in reframes:
            session.candidate_reframes.append(rf)
        self._total_reframes += len(reframes)

        # 5.6 Generate explorations (Phase 2)
        explorations = self._exploration_engine.generate_programs(
            tensions, context, profile
        )
        self._total_explorations += len(explorations)

        # Log Phase 2 artifacts
        for rf in reframes:
            self._store.log_event(events.REFRAME_GENERATED, {
                "reframe_id": rf.reframe_id,
                "original_ref": rf.original_ref,
            })
        for ep in explorations:
            self._store.log_event(events.EXPLORATION_PROPOSED, {
                "program_id": ep.program_id,
                "title": ep.title,
            })

        # 5.7 LoopDetector — drop candidates whose meta_goal_type has been
        # repeatedly abandoned in the recent window (D3, 2026-04-26).
        candidates, suppressed_candidates = self._loop_detector.filter_candidates(
            candidates,
        )
        if suppressed_candidates:
            self._handle_suppressed_loop(suppressed_candidates)

        # 6. Filter for novelty
        accepted, rejected = self._novelty_filter.filter(candidates)
        for r in rejected:
            self._store.save_meta_goal(r)
            self._store.log_event(events.GOAL_REJECTED_DUPLICATE, {
                "goal_id": r.goal_id,
                "title": r.title,
            })

        # 7. Evaluate candidates
        # 7.5 Personality check (Phase 2) - adjust evaluation weights
        personality_signals = self._personality_policy.evaluate(profile, tensions)
        adjusted_weights = self._personality_policy.adjust_evaluation_weights(
            signals=personality_signals,
        )
        for sig in personality_signals:
            self._store.log_event(events.PERSONALITY_SIGNAL, {
                "signal_id": sig.signal_id,
                "dimension": sig.dimension.value,
                "direction": sig.direction,
                "magnitude": sig.magnitude,
            })

        promoted_goals = []
        if accepted:
            evaluations = self._evaluator.evaluate_batch(
                accepted, context, weights=adjusted_weights,
            )
            for eval_result in evaluations:
                goal_id = eval_result["goal_id"]
                mg = next((g for g in accepted if g.goal_id == goal_id), None)
                if not mg:
                    continue

                if eval_result["promoted"]:
                    # 8. Promote to GoalStore
                    proposed_mg = mg.with_status(MetaGoalStatus.PROPOSED)
                    self._store.save_meta_goal(proposed_mg)

                    result = self._goal_adapter.adapt_and_propose(proposed_mg)
                    if result:
                        accepted_mg = proposed_mg.with_status(MetaGoalStatus.ACCEPTED)
                        self._store.save_meta_goal(accepted_mg)
                        promoted_goals.append(accepted_mg)
                        self._store.log_event(events.GOAL_PROMOTED, {
                            "goal_id": mg.goal_id,
                            "title": mg.title,
                            "score": eval_result["final_score"],
                        })
                    else:
                        self._store.save_meta_goal(
                            mg.with_status(MetaGoalStatus.REJECTED)
                        )
                else:
                    self._store.save_meta_goal(
                        mg.with_status(MetaGoalStatus.REJECTED)
                    )

        self._total_meta_goals_proposed += len(promoted_goals)

        # 9. Close session and write journal
        session.close()
        journal_entry = self._journal.create_entry_from_session(session)
        self._store.log_event(events.JOURNAL_ENTRY_WRITTEN, {
            "entry_id": journal_entry.entry_id,
        })

        # 10. Persist workspace summary
        self._store.save_workspace_session(session)
        self._store.log_event(events.REFLECTION_SESSION_COMPLETE, {
            "session_id": session.session_id,
            "tensions": len(tensions),
            "insights": len(insights),
            "candidates": len(candidates),
            "promoted": len(promoted_goals),
            "reframes": len(reframes),
            "explorations": len(explorations),
        })

        # Update state
        self._last_reflection_ts = time.time()
        self._total_reflections += 1
        duration_ms = (time.time() - start) * 1000

        logger.info(
            f"[CREATIVE] Reflection complete: {len(tensions)} tensions, "
            f"{len(insights)} insights, {len(promoted_goals)} meta-goals, "
            f"{len(reframes)} reframes, {len(explorations)} explorations "
            f"({duration_ms:.0f}ms)"
        )

        return {
            "success": True,
            "tensions": len(tensions),
            "insights": len(insights),
            "meta_goals_proposed": len(candidates),
            "meta_goals_promoted": len(promoted_goals),
            "promoted_titles": [mg.title for mg in promoted_goals],
            "tension_categories": [t.category.value for t in tensions],
            "reframes": len(reframes),
            "explorations": len(explorations),
            "llm_enhanced": self._has_llm,
            "duration_ms": duration_ms,
            "trigger": trigger,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get module status summary."""
        now = time.time()
        cooldown_remaining = max(
            0, MIN_REFLECTION_INTERVAL_SEC - (now - self._last_reflection_ts)
        )
        return {
            "total_reflections": self._total_reflections,
            "total_meta_goals_proposed": self._total_meta_goals_proposed,
            "total_meta_goals_suppressed": self._total_meta_goals_suppressed,
            "total_tensions_detected": self._total_tensions_detected,
            "total_reframes": self._total_reframes,
            "total_explorations": self._total_explorations,
            "last_reflection_ts": self._last_reflection_ts,
            "cooldown_remaining_sec": cooldown_remaining,
            "can_reflect": self.should_reflect(),
            "llm_enhanced": self._has_llm,
        }

    # --- D3: loop suppression ---------------------------------

    def _handle_suppressed_loop(self, suppressed_candidates: List[Any]) -> None:
        """Persist + log + bulletin-post when LoopDetector kills candidates.

        Each suppressed meta-goal candidate is saved to the creative store as
        ``REJECTED`` (so it appears in the journal), one creative event is
        emitted per candidate, and one bulletin ``IMPROVEMENT`` entry is
        posted per distinct meta-goal type — operator visibility without
        spamming the bulletin with one entry per candidate.
        """
        if not suppressed_candidates:
            return

        try:
            report = self._loop_detector.detect()
        except Exception as e:
            logger.debug(f"[CREATIVE] loop detector report failed: {e}")
            report = None

        seen_types: set = set()
        for mg in suppressed_candidates:
            try:
                gtype = mg.goal_type.value
            except AttributeError:
                gtype = "unknown"

            try:
                rejected_mg = mg.with_status(MetaGoalStatus.REJECTED)
                self._store.save_meta_goal(rejected_mg)
            except Exception as e:
                logger.debug(f"[CREATIVE] could not persist suppressed mg: {e}")

            try:
                self._store.log_event(events.GOAL_SUPPRESSED_LOOP, {
                    "goal_id": getattr(mg, "goal_id", "?"),
                    "title": getattr(mg, "title", ""),
                    "meta_goal_type": gtype,
                })
            except Exception:
                pass

            if gtype in seen_types:
                continue
            seen_types.add(gtype)

            count = report.counts.get(gtype, 0) if report else 0
            window_days = report.window_days if report else 7
            self._post_loop_bulletin(gtype, count, window_days, mg)

        self._total_meta_goals_suppressed += len(suppressed_candidates)
        logger.info(
            "[CREATIVE] LoopDetector suppressed %d candidate(s) across %d type(s): %s",
            len(suppressed_candidates),
            len(seen_types),
            sorted(seen_types),
        )

    def _post_loop_bulletin(
        self,
        meta_goal_type: str,
        count: int,
        window_days: int,
        sample_mg: Any,
    ) -> None:
        """Post one IMPROVEMENT bulletin entry per suppressed type per cycle."""
        if self._bulletin_store is None:
            return
        try:
            from agent_core.bulletin.bulletin_model import EntryType
        except Exception:
            return

        topic = f"creative_loop:{meta_goal_type}"
        summary = (
            f"LoopDetector: pattern '{meta_goal_type}' recurred {count} time(s) "
            f"in {window_days}d without being actioned. Suppressing regeneration "
            f"until the streak ages out. Latest example: "
            f"{getattr(sample_mg, 'title', '')[:80]}"
        )
        try:
            self._bulletin_store.create_and_post(
                entry_type=EntryType.IMPROVEMENT,
                topic=topic,
                reason_code="creative_loop_suppression",
                summary=summary,
                requested_by="creative",
                priority=0.8,
                metadata={
                    "meta_goal_type": meta_goal_type,
                    "abandon_count": count,
                    "window_days": window_days,
                    "sample_goal_id": getattr(sample_mg, "goal_id", None),
                },
            )
        except Exception as e:
            logger.debug(f"[CREATIVE] bulletin post failed: {e}")

    def _build_problem_statement(self, tensions, context) -> str:
        """Build problem statement from top tensions."""
        parts = [f"System ma {len(tensions)} napiec rozwojowych:"]
        for t in tensions[:3]:
            parts.append(f"- {t.category.value}: {t.description[:100]}")

        action_pattern = context.get("action_pattern", {})
        noop_ratio = action_pattern.get("noop_ratio", 0)
        if noop_ratio > 0.5:
            parts.append(f"Planner NOOP ratio: {noop_ratio:.0%}")

        return " ".join(parts)
