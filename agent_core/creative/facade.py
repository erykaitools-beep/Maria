"""Creative Module facade - public entry points.

Public methods:
    reflect()                  - Run full reflection cycle (detect -> insight -> propose)
    should_reflect()           - Check if conditions warrant reflection
    get_status()               - Module status summary

Integration:
    - Called by Planner via ActionType.CREATIVE
    - Phase 11 in tick loop (after planner, before sleep)
    - Outputs: GoalStore PROPOSED items, journal entries, strategic observations

Cooldowns:
    - Minimum 2h between reflections
    - Max 3 meta-goals per cycle
    - Category cooldown 12h (same tension type)
"""

import logging
import time
from typing import Any, Dict, Optional

from agent_core.creative.creative_model import MetaGoalStatus
from agent_core.creative.creative_store import CreativeStore
from agent_core.creative.strategic_context import StrategicContext
from agent_core.creative.tension_detector import TensionDetector
from agent_core.creative.reflection_workspace import ReflectionWorkspaceManager
from agent_core.creative.creative_journal import CreativeJournal
from agent_core.creative.novelty_filter import NoveltyFilter
from agent_core.creative.creative_evaluator import CreativeEvaluator, PROMOTION_THRESHOLD
from agent_core.creative.goal_adapter import GoalAdapter
from agent_core.creative import creative_events as events

logger = logging.getLogger(__name__)

# Cooldown: minimum time between reflection cycles
MIN_REFLECTION_INTERVAL_SEC = 7200  # 2h
# For debugging/testing, can be lowered
DEBUG_INTERVAL_SEC = 300  # 5min


class CreativeModule:
    """Facade for the Creative Module (K13)."""

    def __init__(self, data_dir: str = "meta_data", memory_dir: str = "memory",
                 goal_store=None):
        # Core components
        self._store = CreativeStore(data_dir)
        self._context_builder = StrategicContext(data_dir, memory_dir)
        self._tension_detector = TensionDetector()
        self._workspace_mgr = ReflectionWorkspaceManager()
        self._journal = CreativeJournal(self._store)
        self._novelty_filter = NoveltyFilter(self._store)
        self._evaluator = CreativeEvaluator()
        self._goal_adapter = GoalAdapter(goal_store)

        # State
        self._last_reflection_ts: float = 0.0
        self._total_reflections: int = 0
        self._total_meta_goals_proposed: int = 0
        self._total_tensions_detected: int = 0

    def set_goal_store(self, goal_store) -> None:
        """Wire GoalStore after initialization."""
        self._goal_adapter.set_goal_store(goal_store)

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
        Run a full reflection cycle.

        Steps:
        1. Build strategic context
        2. Detect tensions
        3. Create reflection session
        4. Form insights from tensions
        5. Generate candidate meta-goals
        6. Filter for novelty
        7. Evaluate candidates
        8. Promote to GoalStore
        9. Write journal entry
        10. Persist workspace summary

        Args:
            trigger: Why reflection was triggered (periodic/planner/operator/tension)

        Returns:
            Summary dict of the reflection cycle.
        """
        start = time.time()
        logger.info(f"[CREATIVE] Starting reflection cycle (trigger: {trigger})")

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

        # 5. Generate candidate meta-goals
        candidates = self._workspace_mgr.generate_candidates(session, context)

        # 6. Filter for novelty
        accepted, rejected = self._novelty_filter.filter(candidates)
        for r in rejected:
            self._store.save_meta_goal(r)
            self._store.log_event(events.GOAL_REJECTED_DUPLICATE, {
                "goal_id": r.goal_id,
                "title": r.title,
            })

        # 7. Evaluate accepted candidates
        promoted_goals = []
        if accepted:
            evaluations = self._evaluator.evaluate_batch(accepted, context)
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
                        # GoalStore full
                        self._store.save_meta_goal(
                            mg.with_status(MetaGoalStatus.REJECTED)
                        )
                else:
                    # Below threshold
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
        })

        # Update state
        self._last_reflection_ts = time.time()
        self._total_reflections += 1
        duration_ms = (time.time() - start) * 1000

        logger.info(
            f"[CREATIVE] Reflection complete: {len(tensions)} tensions, "
            f"{len(insights)} insights, {len(promoted_goals)} meta-goals promoted "
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
            "total_tensions_detected": self._total_tensions_detected,
            "last_reflection_ts": self._last_reflection_ts,
            "cooldown_remaining_sec": cooldown_remaining,
            "can_reflect": self.should_reflect(),
        }

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
