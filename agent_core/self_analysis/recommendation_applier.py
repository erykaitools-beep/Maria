"""
K12 Self-Analysis: RecommendationApplier.

Converts analysis recommendations into concrete actions:
- PROPOSED LEARNING goals (human gate via K3)
- Topic hints for WebSource fetcher
- Beliefs in K6 World Model

All goals are PROPOSED (not ACTIVE) - operator approves.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from .recommendation_model import (
    AnalysisRecommendation,
    AnalysisReport,
    MAX_PROPOSED_GOALS_FROM_ANALYSIS,
)

logger = logging.getLogger(__name__)

# Topic hints file (read by TopicSuggester in Phase 2)
_DEFAULT_HINTS_PATH = "meta_data/topic_hints.jsonl"


class RecommendationApplier:
    """Convert recommendations into goals, topic hints, and beliefs."""

    def __init__(
        self,
        goal_store=None,
        world_model=None,
        project_root: str = ".",
    ):
        """
        Args:
            goal_store: K3 GoalStore instance (optional, for goal creation)
            world_model: K6 WorldModel instance (optional, for belief updates)
            project_root: Project root for topic_hints.jsonl path
        """
        self._goal_store = goal_store
        self._world_model = world_model
        self._root = Path(project_root)
        self._hints_path = self._root / _DEFAULT_HINTS_PATH

    def set_goal_store(self, store):
        """Dependency injection from homeostasis wiring."""
        self._goal_store = store

    def set_world_model(self, wm):
        """Dependency injection from homeostasis wiring."""
        self._world_model = wm

    def apply(self, report: AnalysisReport) -> Dict[str, Any]:
        """
        Apply recommendations from analysis report.

        Returns summary of actions taken:
            {"goals_created": [...], "hints_written": N, "beliefs_updated": N}
        """
        result = {
            "goals_created": [],
            "hints_written": 0,
            "beliefs_updated": 0,
            "errors": [],
        }

        if not report.recommendations:
            logger.info("[K12] No recommendations to apply")
            return result

        # Sort by priority (highest first)
        sorted_recs = sorted(
            report.recommendations,
            key=lambda r: r.priority,
            reverse=True,
        )

        goals_created = 0

        for rec in sorted_recs:
            try:
                # 1. Create PROPOSED goal (up to limit)
                if goals_created < MAX_PROPOSED_GOALS_FROM_ANALYSIS:
                    goal_id = self._create_proposed_goal(rec, report.report_id)
                    if goal_id:
                        result["goals_created"].append(goal_id)
                        goals_created += 1

                # 2. Write topic hint for WebSource
                if rec.suggested_action in ("fetch", "learn"):
                    self._write_topic_hint(rec, report.report_id)
                    result["hints_written"] += 1

                # 3. Update K6 belief (if world_model available)
                if self._world_model:
                    self._update_belief(rec)
                    result["beliefs_updated"] += 1

            except Exception as e:
                logger.warning(f"[K12] Error applying rec {rec.rec_id}: {e}")
                result["errors"].append(f"{rec.rec_id}: {str(e)[:100]}")

        # Update report with created goals
        report.goals_created = result["goals_created"]
        report.beliefs_updated = result["beliefs_updated"]

        # Persist goals to JSONL (propose() only marks dirty, save() flushes)
        if goals_created > 0 and self._goal_store is not None:
            try:
                self._goal_store.save()
            except Exception as e:
                logger.warning(f"[K12] Failed to persist goals: {e}")

        logger.info(
            f"[K12] Applied {len(sorted_recs)} recommendations: "
            f"{goals_created} goals, {result['hints_written']} hints, "
            f"{result['beliefs_updated']} beliefs"
        )

        return result

    def _create_proposed_goal(
        self, rec: AnalysisRecommendation, report_id: str
    ) -> Optional[str]:
        """Create a PROPOSED LEARNING goal from recommendation."""
        if self._goal_store is None:
            logger.debug("[K12] No goal_store, skipping goal creation")
            return None

        try:
            # Map recommendation to goal description
            action_map = {
                "fetch": f"Pobierz i naucz sie: {rec.topic}",
                "learn": f"Naucz sie: {rec.topic}",
                "review": f"Powtorz material: {rec.topic}",
                "experiment": f"Eksperyment: {rec.topic}",
            }
            description = action_map.get(
                rec.suggested_action,
                f"Naucz sie: {rec.topic}",
            )

            # Use GoalStore API to create PROPOSED goal
            from agent_core.goals.goal_model import (
                Goal, GoalType, GoalStatus, AuditEntry,
            )
            import uuid

            goal_id_str = f"goal-k12-{uuid.uuid4().hex[:8]}"
            now = time.time()

            goal = Goal(
                id=goal_id_str,
                type=GoalType.LEARNING,
                description=description,
                priority=rec.priority,
                status=GoalStatus.PROPOSED,
                progress=0.0,
                parent_goal_id=None,
                created_by="self_analysis",
                created_at=now,
                updated_at=now,
                audit_trail=[
                    AuditEntry(
                        timestamp=now,
                        old_status=None,
                        new_status="proposed",
                        reason=f"K12: {rec.category} - {rec.topic}",
                        actor="self_analysis",
                    )
                ],
                metadata={
                    "source": "self_analysis",
                    "report_id": report_id,
                    "rec_id": rec.rec_id,
                    "category": rec.category,
                    "topic": rec.topic,
                    "suggested_action": rec.suggested_action,
                },
            )

            goal_id = None
            if hasattr(self._goal_store, "propose"):
                goal_id = self._goal_store.propose(goal)
            elif hasattr(self._goal_store, "create"):
                self._goal_store.create(goal)
                goal_id = goal.id

            if goal_id:
                logger.info(f"[K12] Created PROPOSED goal: {goal_id} ({rec.topic})")

            return goal_id

        except Exception as e:
            logger.warning(f"[K12] Goal creation failed: {e}")
            return None

    def _write_topic_hint(self, rec: AnalysisRecommendation, report_id: str):
        """Write topic hint to JSONL for TopicSuggester (Phase 2 integration)."""
        hint = {
            "topic": rec.topic,
            "source": "self_analysis",
            "report_id": report_id,
            "priority": rec.priority,
            "timestamp": time.time(),
            "consumed": False,
        }

        try:
            self._hints_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._hints_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(hint, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.warning(f"[K12] Could not write topic hint: {e}")

    def _update_belief(self, rec: AnalysisRecommendation):
        """Add external observation as K6 belief."""
        if not self._world_model:
            return

        try:
            if hasattr(self._world_model, "add_belief"):
                self._world_model.add_belief(
                    entity=rec.topic,
                    entity_type="topic",
                    belief_type="observation",
                    content=f"External analysis: {rec.description[:200]}",
                    confidence=0.7,  # External observation, not yet verified
                    source="self_analysis",
                    tags=[rec.topic, "self_analysis", rec.category],
                )
        except Exception as e:
            logger.debug(f"[K12] Belief update failed: {e}")
