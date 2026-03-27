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
        self._experiment_system = None
        self._openclaw_client = None
        self._self_analysis = None
        self._creative_module = None
        self._telegram_notifier = None
        self._llm_router = None
        self._semantic_search = None

    def set_telegram_notifier(self, notifier) -> None:
        """Set Telegram notifier for operator alerts."""
        self._telegram_notifier = notifier

    def set_llm_router(self, router) -> None:
        """Set LLM router for ASK_EXPERT actions (encyclopedia)."""
        self._llm_router = router

    def set_semantic_search(self, semantic_memory) -> None:
        """Set SemanticMemory for semantic-aware fetch sessions."""
        self._semantic_search = semantic_memory

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

    def set_experiment_system(self, system) -> None:
        """Set experiment system for K11 experiment actions."""
        self._experiment_system = system

    def set_openclaw_client(self, client) -> None:
        """Set OpenClaw client for EFFECTOR actions (ADR-016)."""
        self._openclaw_client = client

    def set_self_analysis(self, sa) -> None:
        """Set SelfAnalysis for K12 cognitive loop."""
        self._self_analysis = sa

    def set_creative_module(self, creative) -> None:
        """Set Creative module for K13 reflection cycle."""
        self._creative_module = creative

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
            elif action == ActionType.FETCH:
                result = self._exec_fetch(plan)
            elif action == ActionType.EXPERIMENT:
                result = self._exec_experiment(plan)
            elif action == ActionType.EFFECTOR:
                result = self._exec_effector(plan)
            elif action == ActionType.SELF_ANALYZE:
                result = self._exec_self_analyze(plan)
            elif action == ActionType.CREATIVE:
                result = self._exec_creative(plan)
            elif action == ActionType.ASK_EXPERT:
                result = self._exec_ask_expert(plan)
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
            "score": stats.get("last_exam_score", 0.0),
            "file": stats.get("last_exam_file", ""),
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

    def _exec_fetch(self, plan: Plan) -> Dict[str, Any]:
        """Fetch web content via web_source module."""
        if self._knowledge_analyzer is None:
            return {"success": False, "error": "No knowledge analyzer configured"}

        try:
            from agent_core.web_source import run_fetch_session

            max_articles = plan.action_params.get("max_articles", 3)
            result = run_fetch_session(
                knowledge_analyzer=self._knowledge_analyzer,
                max_articles=max_articles,
                semantic_memory=self._semantic_search,
            )
            errors = result.get("errors", 0)
            return {
                "success": errors == 0,
                "articles_fetched": result.get("articles_fetched", 0),
                "topics_searched": result.get("topics_searched", 0),
                "errors": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _exec_experiment(self, plan: Plan) -> Dict[str, Any]:
        """Run K11 experiment via ExperimentSystem."""
        if self._experiment_system is None:
            return {"success": False, "error": "No experiment system configured"}

        proposal_id = plan.action_params.get("proposal_id")
        if not proposal_id:
            return {"success": False, "error": "No proposal_id in action_params"}

        try:
            report = self._experiment_system.run_experiment(proposal_id)
            if report is None:
                return {"success": False, "error": "Experiment did not produce report"}
            return {
                "success": True,
                "report_id": report.report_id,
                "recommendation": report.recommendation,
                "confidence": report.confidence,
                "conclusion": report.conclusion,
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

    def _exec_effector(self, plan: Plan) -> Dict[str, Any]:
        """Execute OpenClaw tool via effector client (ADR-016)."""
        if self._openclaw_client is None:
            return {"success": False, "error": "No OpenClaw client configured"}

        tool_name = plan.action_params.get("tool_name")
        tool_args = plan.action_params.get("tool_args", {})

        if not tool_name:
            return {"success": False, "error": "No tool_name in action_params"}

        try:
            response = self._openclaw_client.invoke_tool(
                tool_name=tool_name,
                args=tool_args,
            )
            return {
                "success": response.get("ok", False),
                "tool_name": tool_name,
                "tool_result": response.get("result"),
            }
        except Exception as e:
            return {
                "success": False,
                "tool_name": tool_name,
                "error": str(e),
            }

    def _exec_self_analyze(self, plan: Plan) -> Dict[str, Any]:
        """Run K12 self-analysis cycle."""
        if self._self_analysis is None:
            return {"success": False, "error": "No self_analysis configured"}

        try:
            period = plan.action_params.get("period_days", 7)
            report = self._self_analysis.run_analysis(period_days=period)

            if report.error:
                return {
                    "success": False,
                    "error": report.error,
                    "report_id": report.report_id,
                }

            # Notify operator about analysis results
            if self._telegram_notifier and report.recommendations:
                try:
                    summary = report.analysis_text[:300] if report.analysis_text else ""
                    recs = [r if isinstance(r, str) else str(r) for r in report.recommendations]
                    self._telegram_notifier.notify_self_analysis(summary, recs)
                except Exception:
                    pass

            return {
                "success": True,
                "report_id": report.report_id,
                "recommendations": len(report.recommendations),
                "goals_created": report.goals_created,
                "duration_ms": report.duration_ms,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _exec_creative(self, plan: Plan) -> Dict[str, Any]:
        """Run K13 Creative reflection cycle."""
        if self._creative_module is None:
            return {"success": False, "error": "No creative module configured"}

        try:
            trigger = plan.action_params.get("trigger", "planner")
            result = self._creative_module.reflect(trigger=trigger)

            # Notify operator about tensions and meta-goals
            if self._telegram_notifier and result.get("success"):
                try:
                    tensions = result.get("tensions", [])
                    if tensions:
                        self._telegram_notifier.notify_creative_tensions(tensions)
                    meta_goals = result.get("meta_goals_created", [])
                    if meta_goals:
                        self._telegram_notifier.notify_creative_meta_goals(meta_goals)
                except Exception:
                    pass

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _exec_ask_expert(self, plan: Plan) -> Dict[str, Any]:
        """Ask ChatGPT/Codex for knowledge via LLMRouter encyclopedia."""
        if self._llm_router is None or not hasattr(self._llm_router, 'ask_encyclopedia'):
            return {"success": False, "error": "No LLM router with encyclopedia"}

        try:
            question = plan.action_params.get("question", "")
            topic = plan.action_params.get("topic", "")
            source = plan.action_params.get("source", "planner")

            if not question and topic:
                question = (
                    f"Wyjasni w 3-5 zdaniach po polsku: {topic}. "
                    f"Podaj kluczowe fakty i kontekst."
                )
            elif not question:
                return {"success": False, "error": "No question or topic provided"}

            response = self._llm_router.ask_encyclopedia(
                prompt=question,
                source=source,
                context={
                    "goal_id": plan.goal_id or "",
                    "topic": topic,
                },
            )

            if not response or not response.strip():
                return {"success": False, "error": "Empty response from encyclopedia"}

            # Store response as learning material for future use
            result = {
                "success": True,
                "question": question[:200],
                "response": response[:500],
                "response_length": len(response),
                "topic": topic,
            }

            # Save to input/ as learning material (if topic provided)
            if topic:
                try:
                    self._save_expert_response(topic, question, response)
                    result["saved_to_input"] = True
                except Exception:
                    result["saved_to_input"] = False

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _save_expert_response(
        self, topic: str, question: str, response: str
    ) -> None:
        """Save expert response as learning material in input/."""
        from pathlib import Path
        import re
        import time as _time

        # Slugify topic
        slug = re.sub(r'[^a-z0-9]+', '_', topic.lower().strip())[:60].strip('_')
        filename = f"expert_{slug}.txt"
        input_dir = Path(__file__).resolve().parents[2] / "input"
        filepath = input_dir / filename

        # Don't overwrite - append if exists
        header = (
            f"# Zrodlo: ChatGPT (Codex CLI)\n"
            f"# Temat: {topic}\n"
            f"# Data: {_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"# Pytanie: {question[:200]}\n\n"
        )
        content = header + response + "\n"

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(content)
