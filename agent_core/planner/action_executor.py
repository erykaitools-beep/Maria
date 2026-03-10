"""
ActionExecutor - Delegates plan execution to Teacher/Sandbox.

Planner decides WHAT, Executor does HOW.
Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import logging
import time
from typing import Any, Dict

from agent_core.planner.planner_model import ActionType, Plan

logger = logging.getLogger(__name__)


class ActionExecutor:
    """
    Executes a Plan by delegating to the appropriate subsystem.

    - LEARN/EXAM/REVIEW -> TeacherAgent.run_session(max_iterations=1)
    - EVALUATE -> EvaluationObserver.generate_report()
    - MAINTENANCE -> update goal progress from system metrics
    - NOOP -> do nothing

    Topic-aware: if plan.action_params has "topics", resolves them to
    file_ids via KnowledgeAnalyzer and passes filter to Teacher.
    """

    def __init__(self):
        self._teacher_agent = None
        self._evaluation_observer = None
        self._homeostasis_core = None
        self._goal_store = None
        self._knowledge_analyzer = None

    def set_teacher_agent(self, agent) -> None:
        """Set teacher agent for learning/exam/review actions."""
        self._teacher_agent = agent

    def set_evaluation_observer(self, observer) -> None:
        """Set evaluation observer for EVALUATE actions."""
        self._evaluation_observer = observer

    def set_homeostasis_core(self, core) -> None:
        """Set homeostasis core for maintenance metrics."""
        self._homeostasis_core = core

    def set_goal_store(self, store) -> None:
        """Set goal store for progress updates."""
        self._goal_store = store

    def set_knowledge_analyzer(self, analyzer) -> None:
        """Set knowledge analyzer for topic->file resolution."""
        self._knowledge_analyzer = analyzer

    def execute(self, plan: Plan) -> Dict[str, Any]:
        """
        Execute a plan. Returns result dict.

        Args:
            plan: The Plan to execute

        Returns:
            Dict with at least {"success": bool, ...}
        """
        action = plan.action_type
        start = time.time()

        try:
            if action == ActionType.LEARN:
                result = self._exec_learn(plan)
            elif action == ActionType.EXAM:
                result = self._exec_exam(plan)
            elif action == ActionType.REVIEW:
                result = self._exec_review(plan)
            elif action == ActionType.EVALUATE:
                result = self._exec_evaluate(plan)
            elif action == ActionType.MAINTENANCE:
                result = self._exec_maintenance(plan)
            elif action == ActionType.NOOP:
                result = {"success": True, "action": "noop"}
            else:
                result = {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.warning(f"ActionExecutor error: {e}")
            result = {"success": False, "error": str(e)}

        result["duration_ms"] = (time.time() - start) * 1000
        return result

    def _resolve_topics(self, plan: Plan) -> list:
        """
        Resolve topics from plan.action_params to file_ids.

        If action_params has 'topics' but not 'resolved_file_ids',
        uses KnowledgeAnalyzer to resolve. Stores result back in action_params.

        Returns:
            List of file_ids (may be empty), or None if no topic filter.
        """
        topics = plan.action_params.get("topics")
        if not topics:
            return None

        # Already resolved?
        if "resolved_file_ids" in plan.action_params:
            return plan.action_params["resolved_file_ids"] or None

        if self._knowledge_analyzer is None:
            logger.warning("Topics specified but no KnowledgeAnalyzer available")
            plan.action_params["resolved_file_ids"] = []
            plan.action_params["resolution_report"] = {
                "error": "no_analyzer", "matches": 0,
            }
            return []

        scored_files = self._knowledge_analyzer.get_files_for_topics(topics)
        file_ids = [fid for fid, _score in scored_files]

        plan.action_params["resolved_file_ids"] = file_ids
        plan.action_params["resolution_report"] = {
            "topics": topics,
            "matches": len(file_ids),
            "top_scores": [
                {"file": fid, "score": score}
                for fid, score in scored_files[:5]
            ],
        }

        logger.info(
            f"[ActionExecutor] Resolved topics {topics} -> "
            f"{len(file_ids)} files"
        )
        return file_ids or None

    def _exec_learn(self, plan: Plan) -> Dict[str, Any]:
        """Delegate learning to TeacherAgent (single iteration)."""
        if self._teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        filter_ids = self._resolve_topics(plan)
        status = self._teacher_agent.run_session(
            max_iterations=1, filter_file_ids=filter_ids,
        )
        stats = status.get("stats", {})
        result = {
            "success": stats.get("chunks_learned", 0) > 0,
            "chunks_learned": stats.get("chunks_learned", 0),
            "strategies_executed": stats.get("strategies_executed", 0),
        }
        if stats.get("idle_reason"):
            result["idle_reason"] = stats["idle_reason"]
            result["filtered_out_count"] = stats.get("filtered_out_count", 0)
        return result

    def _exec_exam(self, plan: Plan) -> Dict[str, Any]:
        """Delegate exam to TeacherAgent (single iteration)."""
        if self._teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        filter_ids = self._resolve_topics(plan)
        status = self._teacher_agent.run_session(
            max_iterations=1, filter_file_ids=filter_ids,
        )
        stats = status.get("stats", {})
        result = {
            "success": stats.get("exams_run", 0) > 0,
            "exams_run": stats.get("exams_run", 0),
            "exams_passed": stats.get("exams_passed", 0),
        }
        if stats.get("idle_reason"):
            result["idle_reason"] = stats["idle_reason"]
        return result

    def _exec_review(self, plan: Plan) -> Dict[str, Any]:
        """Delegate review/spaced repetition to TeacherAgent."""
        if self._teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        filter_ids = self._resolve_topics(plan)
        status = self._teacher_agent.run_session(
            max_iterations=1, filter_file_ids=filter_ids,
        )
        stats = status.get("stats", {})
        result = {
            "success": stats.get("strategies_executed", 0) > 0,
            "strategies_executed": stats.get("strategies_executed", 0),
        }
        if stats.get("idle_reason"):
            result["idle_reason"] = stats["idle_reason"]
        return result

    def _exec_evaluate(self, plan: Plan) -> Dict[str, Any]:
        """Trigger evaluation report generation."""
        if self._evaluation_observer is None:
            return {"success": False, "error": "No evaluation observer configured"}

        try:
            period = plan.action_params.get("period_hours", 1.0)
            report = self._evaluation_observer.generate_report(
                period_hours=period
            )
            return {
                "success": True,
                "report_id": report.report_id,
                "metrics": report.metrics,
                "recommendations": report.recommendations,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _exec_maintenance(self, plan: Plan) -> Dict[str, Any]:
        """Check and update maintenance goal metrics."""
        if self._homeostasis_core is None:
            return {"success": True, "action": "maintenance_noop"}

        state = self._homeostasis_core.get_state()
        health = state.health_score
        interp = state.interpreted_state or {}

        # Update the maintenance goal's progress if goal_store available
        if self._goal_store and plan.goal_id:
            goal = self._goal_store.get(plan.goal_id)
            if goal:
                metric = goal.metadata.get("metric", "")
                threshold = goal.metadata.get("threshold", 0)
                progress = 0.0

                if metric == "health_score" and threshold > 0:
                    progress = min(health / threshold, 1.0)
                elif metric == "cpu_load" and threshold > 0:
                    # CPU: lower is better, progress=1.0 when cpu < threshold
                    cpu = interp.get("cpu_load", 0)
                    progress = 1.0 if cpu < threshold else max(0.0, 1.0 - (cpu - threshold) / threshold)
                elif metric == "ram_available_pct" and threshold > 0:
                    # RAM: higher is better, progress=1.0 when ram > threshold
                    ram = interp.get("ram_available_pct", 0)
                    progress = min(ram / threshold, 1.0)

                self._goal_store.update_progress(plan.goal_id, progress)
                self._goal_store.save()

        return {
            "success": True,
            "health_score": health,
            "mode": state.mode.value,
        }
