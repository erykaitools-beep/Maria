"""
ActionExecutor - Delegates plan execution to Teacher/Sandbox.

Planner decides WHAT, Executor does HOW.
Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import logging
import time
from typing import Any, Dict, Optional

from agent_core.planner.planner_model import ActionType, Plan
from agent_core.planner.decision_filters import creative_cooldown_skip

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
        self._effector_coordinator = None
        self._self_analysis = None
        self._creative_module = None
        self._play_module = None
        self._telegram_notifier = None
        self._cross_validator = None
        self._critic_agent = None
        self._world_model = None
        self._llm_router = None
        self._semantic_search = None
        self._capability_router = None
        self._bulletin_store = None
        self._expert_bridge = None

    def set_expert_bridge(self, bridge) -> None:
        """Set ExpertBridge for audit-aware expert queries."""
        self._expert_bridge = bridge

    def set_effector_coordinator(self, coordinator) -> None:
        """Set EffectorCoordinator for orchestrated OpenClaw invocations."""
        self._effector_coordinator = coordinator

    def set_bulletin_store(self, store) -> None:
        """Set BulletinStore for resolving cognitive needs after actions."""
        self._bulletin_store = store

    def set_capability_router(self, router) -> None:
        """Set CapabilityRouter for registry-based dispatch."""
        self._capability_router = router

    def set_telegram_notifier(self, notifier) -> None:
        """Set Telegram notifier for operator alerts."""
        self._telegram_notifier = notifier

    def set_llm_router(self, router) -> None:
        """Set LLM router for ASK_EXPERT actions (encyclopedia)."""
        self._llm_router = router

    def set_semantic_search(self, semantic_memory) -> None:
        """Set SemanticMemory for semantic-aware fetch sessions."""
        self._semantic_search = semantic_memory

    def _is_outside_learning_window(self, plan: "Plan") -> bool:
        """Check if autonomous learning should be suppressed (outside window).

        User-requested goals always pass; so do actions the planner already
        approved off-window against the daily rhythm/budget (8b,
        metadata["off_window_approved"]). Returns True if blocked."""
        try:
            meta = getattr(plan, "metadata", {}) or {}
            if meta.get("goal_type") == "USER":
                return False
            if meta.get("off_window_approved"):
                return False
            from agent_core.environment.environment_model import is_learning_window
            return not is_learning_window()
        except Exception:
            return False  # Allow if import fails

    def _incremental_index(self) -> None:
        """Index new knowledge files into semantic memory."""
        try:
            from agent_core.semantic.indexer import index_new_files
            from maria_core.sys.config import BASE_DIR
            index_new_files(
                self._semantic_search,
                str(BASE_DIR / "memory" / "knowledge_index.jsonl"),
                str(BASE_DIR / "input"),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"Incremental indexing skipped: {e}")

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

    def set_play_module(self, play_module) -> None:
        """Set Play module for self-time (ungraded free musing)."""
        self._play_module = play_module

    def set_cross_validator(self, validator) -> None:
        """Set CrossValidator for multi-source learning (Faza F)."""
        self._cross_validator = validator

    def set_critic_agent(self, critic) -> None:
        """Set CriticAgent for knowledge quality gate (Faza G)."""
        self._critic_agent = critic

    def set_world_model(self, world_model) -> None:
        """Set WorldModel for belief confidence updates (Faza F)."""
        self._world_model = world_model

    def set_incident_memory(self, incident_memory) -> None:
        """Set IncidentMemory for recording action failures (Faza 7)."""
        self._incident_memory = incident_memory

    # Action -> method name mapping (replaces Phase B if/elif chain)
    _ACTION_MAP = {
        ActionType.LEARN: "_exec_learn",
        ActionType.EXAM: "_exec_exam",
        ActionType.REVIEW: "_exec_review",
        ActionType.EVALUATE: "_exec_evaluate",
        ActionType.MAINTENANCE: "_exec_maintenance",
        ActionType.FETCH: "_exec_fetch",
        ActionType.EXPERIMENT: "_exec_experiment",
        ActionType.EFFECTOR: "_exec_effector",
        ActionType.FS_WRITE: "_exec_fs_write",
        ActionType.SELF_ANALYZE: "_exec_self_analyze",
        ActionType.CREATIVE: "_exec_creative",
        ActionType.ASK_EXPERT: "_exec_ask_expert",
        ActionType.VALIDATE: "_exec_validate",
        ActionType.CRITIQUE: "_exec_critique",
        ActionType.PLAY: "_exec_play",
    }

    def execute(self, plan: Plan) -> Dict[str, Any]:
        """
        Execute a plan. Returns result dict.

        Primary path: CapabilityRouter (registry-based dispatch).
        Fallback: internal _exec_* methods (for tests / no router).
        """
        if self._capability_router is not None:
            return self._capability_router.dispatch(plan)

        action = plan.action_type
        start = time.time()

        try:
            if action == ActionType.NOOP:
                result = {"success": True, "action": "noop"}
            else:
                method_name = self._ACTION_MAP.get(action)
                if method_name is None:
                    result = {"success": False, "error": f"Unknown action: {action}"}
                else:
                    result = getattr(self, method_name)(plan)
        except Exception as e:
            logger.warning(f"ActionExecutor error: {e}")
            result = {"success": False, "error": str(e)}

        result["duration_ms"] = (time.time() - start) * 1000

        # Faza 7: Record failed actions as incidents
        if not result.get("success", True) and hasattr(self, '_incident_memory') and self._incident_memory:
            try:
                self._incident_memory.record_incident(
                    action_type=action.value if hasattr(action, 'value') else str(action),
                    error_type="execution_failure",
                    description=str(result.get("error", ""))[:200],
                    goal_id=getattr(plan, 'goal_id', "") or "",
                )
            except Exception as exc:
                logger.warning(
                    "ActionExecutor: failed to record incident for action %s: %s",
                    getattr(plan, "plan_id", "?"),
                    exc,
                )

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

    def _exec_fs_write(self, plan: Plan) -> Dict[str, Any]:
        """B2: first real effector primitive -- write one small file into the
        dedicated sandbox. Params: {filename, content, [sandbox_root]}.

        Sandboxed + size-capped (the write itself lives in
        agent_core/hands/sandbox_writer so the router handler and this fallback
        share one SSoT). K10 then re-stats the file as an external check.
        """
        from agent_core.hands.sandbox_writer import (
            sandbox_write,
            default_sandbox_root,
        )
        params = plan.action_params or {}
        filename = params.get("filename") or params.get("path") or "maria_action"
        content = params.get("content", "")
        sandbox_root = params.get("sandbox_root")
        if not sandbox_root:
            try:
                from maria_core.sys.config import BASE_DIR
                sandbox_root = default_sandbox_root(BASE_DIR)
            except Exception:
                sandbox_root = default_sandbox_root(".")
        return sandbox_write(filename, content, sandbox_root=sandbox_root)

    def _exec_learn(self, plan: Plan) -> Dict[str, Any]:
        """Delegate learning to TeacherAgent (single iteration)."""
        if self._teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        # Gate: respect learning windows for autonomous learning
        if self._is_outside_learning_window(plan):
            return {"success": False, "skipped": True,
                    "reason": "outside_learning_window"}

        filter_ids = self._resolve_topics(plan)
        # Project sub-goal whose topic matches NO file -> no_files skip so the
        # B2 FETCH pump arms; mirrors handlers.make_learn_handler (SSoT).
        if (not filter_ids and plan.action_params.get("topics")
                and (getattr(plan, "metadata", None) or {}).get("project_child")):
            return {"success": False, "skipped": True, "reason": "no_files",
                    "chunks_learned": 0}
        status = self._teacher_agent.run_session(
            max_iterations=1, filter_file_ids=filter_ids,
        )
        stats = status.get("stats", {})
        # Strict: success requires new chunks. Matches handlers.make_learn_handler
        # (single source of truth in production via CapabilityRouter).
        learned = stats.get("chunks_learned", 0)
        result = {
            "success": learned > 0,
            "chunks_learned": learned,
            "exams_run": stats.get("exams_run", 0),
            "exams_passed": stats.get("exams_passed", 0),
            "strategies_executed": stats.get("strategies_executed", 0),
        }
        if stats.get("idle_reason"):
            result["idle_reason"] = stats["idle_reason"]
            result["filtered_out_count"] = stats.get("filtered_out_count", 0)
            # "idle != failed": a learn that produced 0 chunks because there was
            # no fresh material (every candidate already completed/filtered) was
            # declined before any real work -- mark it skipped so planner *rest*
            # does not tank learn-confidence (the K9 needs_human signal) the way a
            # genuine failure should. A 0-chunk learn WITHOUT an idle_reason (a
            # real teacher error) stays a failure. Mirrors exam's window skip.
            if learned == 0:
                result["skipped"] = True

        # Re-index after learning (update vector embedding with new status)
        if result["success"] and self._semantic_search:
            self._incremental_index()

        # CDL feedback: update learning goal progress
        if result["success"]:
            self._update_learning_goal(plan, result)
            self._resolve_bulletin_entries(plan.goal_id, "learned_material")

        return result

    def _exec_exam(self, plan: Plan) -> Dict[str, Any]:
        """Delegate exam to TeacherAgent (single iteration)."""
        if self._teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        if self._is_outside_learning_window(plan):
            return {"success": False, "skipped": True,
                    "reason": "outside_learning_window"}

        filter_ids = self._resolve_topics(plan)
        # Project sub-goal whose topic matches NO file -> no_files skip so the
        # B2 FETCH pump arms; mirrors handlers.make_exam_handler (SSoT).
        if (not filter_ids and plan.action_params.get("topics")
                and (getattr(plan, "metadata", None) or {}).get("project_child")):
            return {"success": False, "skipped": True, "reason": "no_files",
                    "exams_run": 0}
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

        # CDL feedback: update learning goal progress
        if result["success"]:
            self._update_learning_goal(plan, result)

        return result

    def _exec_review(self, plan: Plan) -> Dict[str, Any]:
        """Delegate review/spaced repetition to TeacherAgent."""
        if self._teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        if self._is_outside_learning_window(plan):
            return {"success": False, "skipped": True,
                    "reason": "outside_learning_window"}

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

        # Gate: respect learning windows (fetch feeds learning pipeline)
        if self._is_outside_learning_window(plan):
            return {"success": False, "skipped": True,
                    "reason": "outside_learning_window"}

        try:
            from agent_core.web_source import (
                run_fetch_session, resolve_feed_profile,
            )

            max_articles = plan.action_params.get("max_articles", 3)
            # Pass user-requested topics from conversation goals
            override_topics = plan.action_params.get("topics")
            # B1 parity: mirror the CapabilityRouter path so a market goal never
            # silently drifts onto the science feeds when the router is absent
            # (tests / future). Single source of truth = resolve_feed_profile.
            feed_profile = resolve_feed_profile(
                self._goal_store, getattr(plan, "goal_id", None)
            )
            result = run_fetch_session(
                knowledge_analyzer=self._knowledge_analyzer,
                max_articles=max_articles,
                semantic_memory=self._semantic_search,
                override_topics=override_topics,
                feed_profile=feed_profile,
            )
            errors = result.get("errors", 0)

            # Incremental indexing: embed newly fetched files
            if self._semantic_search and result.get("articles_fetched", 0) > 0:
                self._incremental_index()

            fetched = result.get("articles_fetched", 0)
            if fetched > 0:
                # Material arrived -> update bulletin: NEED_MATERIAL -> READY_TO_LEARN
                self._transition_bulletin_to_ready(plan.goal_id)

            # P2: bind the same durable learn-handoff the CapabilityRouter path
            # binds, delegating to the single source of truth in routing.handlers
            # so this no-router fallback can never drift (cf. _update_learning_goal
            # above). Without this, a fetch here wrote bytes that no goal ever
            # obligated learning -- a silent orphan leak. Same fetched_files
            # trigger as P1 (bind on any written file, not only error-free).
            handoff_files = []
            if result.get("fetched_files"):
                from agent_core.routing.handlers import (
                    _register_fetch_handoff_goal,
                )
                handoff_files = _register_fetch_handoff_goal(
                    plan, result, self._knowledge_analyzer, self._goal_store,
                )

            return {
                # Yield-aware: a fetch that wrote 0 articles is NOT a win. 0 articles
                # + no error = nothing NEW to fetch this session (corpus frontier dry)
                # -> idle rest, marked skipped so the saturation fetch pump stops being
                # falsely reinforced AND fetch-confidence isn't tanked (same idle!=failed
                # contract as the learn fix). 0 articles WITH errors stays a failure.
                "success": fetched > 0 and errors == 0,
                "skipped": fetched == 0 and errors == 0,
                "articles_fetched": fetched,
                "fetched_files": result.get("fetched_files", []),
                "learn_handoff_files": handoff_files,
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
        """Execute OpenClaw tool via effector coordinator (preferred) or client."""
        tool_name = plan.action_params.get("tool_name")
        tool_args = plan.action_params.get("tool_args", {})

        if not tool_name:
            return {"success": False, "error": "No tool_name in action_params"}

        # Preferred path: coordinator handles preflight, pre-warm, retry, diagnose
        if self._effector_coordinator is not None:
            from agent_core.effector.coordinator import EffectorTask
            task = EffectorTask(
                tool_name=tool_name,
                tool_args=tool_args,
                plan_id=getattr(plan, "plan_id", None),
                goal_id=getattr(plan, "goal_id", None),
                source="planner",
            )
            outcome = self._effector_coordinator.execute_task(task)
            return {
                "success": outcome.ok,
                "tool_name": tool_name,
                "tool_result": outcome.result.get("result") if outcome.result else None,
                "task_id": outcome.task_id,
                "attempts": len(outcome.attempts),
                "status": outcome.status.value,
                "duration_s": round(outcome.total_duration_s, 2),
            }

        # Legacy path: direct client invocation (used in tests / partial setup)
        if self._openclaw_client is None:
            return {"success": False, "error": "No OpenClaw client configured"}
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
                    # Clean (summary, recs) instead of dumping raw_response (raw
                    # JSON / prose) and str(dataclass) reprs into Telegram
                    # (operator-facing junk, audyt 2026-06-15). Shared formatter
                    # so the two call sites cannot drift.
                    from agent_core.self_analysis.recommendation_model import (
                        format_report_for_telegram,
                    )
                    summary, recs = format_report_for_telegram(report)
                    self._telegram_notifier.notify_self_analysis(summary, recs)
                except Exception:
                    pass

            result = {
                "success": True,
                "report_id": report.report_id,
                "recommendations": len(report.recommendations),
                "goals_created": report.goals_created,
                "duration_ms": report.duration_ms,
            }

            # Complete the goal - self-analysis is a one-shot action
            self._complete_oneshot_goal(plan, result)

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _exec_creative(self, plan: Plan) -> Dict[str, Any]:
        """Run K13 Creative reflection cycle."""
        if self._creative_module is None:
            return {"success": False, "error": "No creative module configured"}

        try:
            # Cooldown guard (2026-07-06): ask-first before the NIM-heavy
            # reflect(); shape and rationale live in the shared helper.
            skip = creative_cooldown_skip(self._creative_module)
            if skip is not None:
                return skip

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

            # Complete the goal - creative reflection is a one-shot action
            if result.get("success"):
                self._complete_oneshot_goal(plan, result)

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _exec_play(self, plan: Plan) -> Dict[str, Any]:
        """Run one self-time play cycle (ungraded). No goal completion -- PLAY
        is goalless leisure, not work."""
        if self._play_module is None:
            return {"success": False, "error": "No play module configured"}
        try:
            trigger = plan.action_params.get("trigger", "planner_idle")
            return self._play_module.play(trigger=trigger)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _exec_ask_expert(self, plan: Plan) -> Dict[str, Any]:
        """Ask expert LLM for knowledge, using ExpertBridge if available."""
        topic = plan.action_params.get("topic", "")
        goal_desc = plan.goal_description or ""
        context_prompt = plan.action_params.get("context_prompt", "")

        # Phase 4: ExpertBridge path (audit-aware, targeted prompts)
        if self._expert_bridge is not None and topic:
            try:
                if context_prompt:
                    resp = self._expert_bridge.ask_with_context(topic, context_prompt)
                else:
                    resp = self._expert_bridge.ask_about_topic(topic, goal_desc)

                if not resp.success:
                    # Logical skips (dedup, already covered) are not failures
                    skip_reasons = {
                        "expert_material_already_exists",
                        "topic_well_covered",
                    }
                    is_skip = resp.reason in skip_reasons
                    return {
                        "success": is_skip, "skipped": is_skip,
                        "reason": resp.reason,
                        "topic": topic, "gap_action": resp.gap_action,
                    }

                saved = False
                try:
                    self._save_expert_response(topic, resp.context_prompt, resp.response)
                    saved = True
                except Exception:
                    pass

                # Phase 5: resolve bulletin NEED_MATERIAL entries
                if self._bulletin_store is not None and saved:
                    self._resolve_bulletin_need(topic)

                return {
                    "success": True, "topic": topic,
                    "response": resp.response[:500],
                    "response_length": len(resp.response),
                    "gap_action": resp.gap_action,
                    "saved_to_input": saved,
                }
            except Exception as e:
                logger.debug(f"[ASK_EXPERT] ExpertBridge error: {e}")

        # Legacy fallback: generic prompt via ask_encyclopedia
        if self._llm_router is None or not hasattr(self._llm_router, 'ask_encyclopedia'):
            return {"success": False, "error": "No LLM router with encyclopedia"}

        try:
            question = plan.action_params.get("question", "")
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

            result = {
                "success": True,
                "question": question[:200],
                "response": response[:500],
                "response_length": len(response),
                "topic": topic,
            }

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

        # Skip if file already has substantial content (dedup)
        if filepath.exists():
            try:
                size = filepath.stat().st_size
                if size > 5000:
                    logger.info(
                        f"[ASK_EXPERT] Skip save: {filename} already has "
                        f"{size} bytes of content"
                    )
                    return
            except OSError:
                pass

        header = (
            f"# Zrodlo: ChatGPT (Codex CLI)\n"
            f"# Temat: {topic}\n"
            f"# Data: {_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"# Pytanie: {question[:200]}\n\n"
        )
        content = header + response + "\n"

        # Write (not append) - one good response is enough
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def _resolve_bulletin_need(self, topic: str) -> None:
        """Mark NEED_MATERIAL bulletin entries as resolved after expert response."""
        try:
            from agent_core.bulletin.bulletin_model import EntryType, EntryStatus
            entries = self._bulletin_store.find_open(
                topic=topic, entry_type=EntryType.NEED_MATERIAL,
            )
            for entry in entries:
                self._bulletin_store.update_status(
                    entry.entry_id, EntryStatus.RESOLVED,
                )
        except Exception as e:
            logger.debug(f"[ASK_EXPERT] Bulletin update failed: {e}")

    def _exec_validate(self, plan: Plan) -> Dict[str, Any]:
        """Cross-validate learned knowledge using a secondary LLM (Faza F)."""
        if self._cross_validator is None:
            return {"success": False, "error": "No CrossValidator configured"}

        file_id = plan.action_params.get("file_id", "")
        if not file_id:
            # Pick a recently completed file for validation
            file_id = self._pick_validation_candidate()
            if not file_id:
                return {"success": False, "error": "No files ready for validation"}

        try:
            # Load memory records for this file
            from maria_core.sys.config import LONGTERM_MEMORY, INPUT_DIR
            from maria_core.memory_engine.memory_store import load_index
            import json

            memories = []
            if LONGTERM_MEMORY.exists():
                with open(LONGTERM_MEMORY, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            if rec.get("source_file") == file_id:
                                memories.append(rec)
                        except json.JSONDecodeError:
                            continue

            if not memories:
                return {"success": False, "error": f"No memories for {file_id}"}

            # Load original chunk texts from input file
            chunk_texts = {}
            input_path = INPUT_DIR / file_id
            if input_path.exists():
                from maria_core.learning.chunking import intelligent_chunk_text
                full_text = input_path.read_text(encoding="utf-8", errors="replace")
                chunks = intelligent_chunk_text(full_text)
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{file_id}#chunk_{i}"
                    chunk_texts[chunk_id] = chunk
            else:
                return {"success": False, "error": f"Input file not found: {file_id}"}

            # Run cross-validation
            result = self._cross_validator.validate_file(
                file_id=file_id,
                chunk_texts=chunk_texts,
                memory_records=memories,
                max_chunks=5,  # limit per session
            )

            # Update belief confidence based on validation results
            beliefs_updated = self._update_beliefs_from_validation(
                file_id, result.get("avg_confidence", 0.5),
            )

            return {
                "success": result["chunks_validated"] > 0,
                "file_id": file_id,
                "chunks_validated": result["chunks_validated"],
                "chunks_agreed": result["chunks_agreed"],
                "chunks_disputed": result["chunks_disputed"],
                "avg_confidence": result["avg_confidence"],
                "beliefs_updated": beliefs_updated,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _pick_validation_candidate(self) -> str:
        """Pick a completed file that hasn't been validated recently."""
        if not self._knowledge_analyzer:
            return ""
        try:
            snapshot = self._knowledge_analyzer.get_knowledge_snapshot()
            completed = snapshot.get("files_by_status", {}).get("completed", [])
            if completed:
                # Pick first completed file (simplest strategy)
                return completed[0]
        except Exception:
            pass
        return ""

    def _update_beliefs_from_validation(
        self, file_id: str, avg_confidence: float,
    ) -> int:
        """
        Update belief confidence for beliefs related to a validated file.

        High cross-validation confidence (>0.7) promotes OBSERVATION -> FACT.
        Low confidence (<0.3) demotes to HYPOTHESIS.

        Returns number of beliefs updated.
        """
        if not self._world_model:
            return 0

        try:
            from agent_core.world_model.belief_model import BeliefType

            store = self._world_model.store
            # Find beliefs linked to this file
            beliefs = [
                b for b in store.get_current()
                if b.source_id == file_id
            ]

            updated = 0
            for belief in beliefs:
                # Blend existing confidence with validation score
                new_conf = belief.confidence * 0.6 + avg_confidence * 0.4

                # Determine if belief type should change
                new_type = None
                if avg_confidence >= 0.7 and belief.belief_type == BeliefType.OBSERVATION:
                    new_type = BeliefType.FACT
                elif avg_confidence < 0.3 and belief.belief_type != BeliefType.HYPOTHESIS:
                    new_type = BeliefType.HYPOTHESIS

                # Only revise if confidence changed meaningfully
                if abs(new_conf - belief.confidence) > 0.05 or new_type:
                    store.revise(belief.belief_id, new_conf, new_type)
                    updated += 1

            if updated:
                # BeliefStore persists via save() (appends dirty records);
                # flush() never existed -- the AttributeError fell into the
                # except below, so revisions sat dirty-in-memory until some
                # unrelated later save() and this function reported 0
                # (wired-but-dead, found 2026-06-10, fixed 2026-06-11).
                store.save()
                logger.info(
                    f"[Faza F] Updated {updated} beliefs for {file_id} "
                    f"(avg_confidence={avg_confidence:.2f})"
                )
            return updated
        except Exception as e:
            logger.debug(f"Belief update skipped: {e}")
            return 0

    def _update_learning_goal(self, plan, result: dict) -> None:
        """CDL feedback loop: update LEARNING goal progress and outcome.

        Delegates to the single source of truth in routing.handlers so this
        no-router fallback path and the production CapabilityRouter path can
        never drift. They had: this copy ignored explicit file_ids, read only
        the "topics" key, and its topic match compared id-strings against
        record-dicts -- so it always scored 0 (Plank 2).
        """
        from agent_core.routing.handlers import update_learning_goal
        update_learning_goal(
            plan, result, self._goal_store,
            self._knowledge_analyzer, self._telegram_notifier,
        )

    # -- One-shot goal completion helper --------------------------------

    def _complete_oneshot_goal(self, plan: Plan, outcome: dict) -> None:
        """Mark a one-shot goal (critique, self_analyze, creative) as ACHIEVED.

        These actions complete in a single execution. Without this,
        the goal stays PENDING forever and GoalSelector keeps re-selecting it.
        """
        if not self._goal_store or not plan.goal_id:
            return
        try:
            from agent_core.goals.goal_model import GoalStatus
            goal = self._goal_store.get(plan.goal_id)
            # Option C: a heldout-mode goal closes ONLY on mechanical held-out
            # verdicts (verified/N) -- one-shot completion would ACHIEVE it with
            # zero evidence. Unconditional (unlike the gate check below): the
            # heldout contract must not depend on a mutable env flag.
            if goal and str(
                ((goal.metadata or {}).get("verification_mode")) or ""
            ).strip().lower() == "heldout":
                return
            # Kronika TIER 1: a market child must not be one-shot-completed --
            # that would ACHIEVE it bypassing the provenance gate. It closes only
            # via verified provenance under cutover; inert otherwise.
            if goal and (goal.metadata or {}).get("source_kind") == "market":
                from agent_core.routing.handlers import _provenance_gate_mode
                if _provenance_gate_mode() == "cutover":
                    return
            mutated = False
            if goal and goal.status.value in ("pending", "active"):
                self._goal_store.update_progress(plan.goal_id, 1.0)
                mutated = True
                # update_progress auto-transitions to ACHIEVED at >= 1.0
                # but only for ACTIVE goals, so also set status explicitly
                goal_refreshed = self._goal_store.get(plan.goal_id)
                if goal_refreshed and goal_refreshed.status.value != "achieved":
                    self._goal_store.update_status(
                        plan.goal_id, GoalStatus.ACHIEVED,
                        reason="one-shot action completed",
                        actor="action_executor",
                    )
                    mutated = True
                self._goal_store.set_outcome(plan.goal_id, outcome)
                mutated = True
            if mutated:
                self._goal_store.save()
        except Exception as e:
            logger.debug(f"One-shot goal completion failed: {e}")

    # -- Faza G: Knowledge critique ------------------------------------

    def _exec_critique(self, plan: Plan) -> Dict[str, Any]:
        """Knowledge quality critique (Faza G)."""
        if self._critic_agent is None:
            return {"success": False, "error": "No CriticAgent configured"}

        try:
            trigger = plan.action_params.get("trigger", "planner")
            report = self._critic_agent.run_critique(trigger=trigger)

            if report.error:
                return {
                    "success": False,
                    "error": report.error,
                    "report_id": report.report_id,
                }

            result = {
                "success": True,
                "report_id": report.report_id,
                "findings": len(report.findings),
                "goals_created": report.goals_created,
                "duration_ms": report.duration_ms,
            }

            # Complete the goal - critique is a one-shot action
            self._complete_oneshot_goal(plan, result)

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -- Bulletin Board helpers ---

    def _resolve_bulletin_entries(self, goal_id: Optional[str], reason: str) -> None:
        """Resolve NEED_MATERIAL/READY_TO_LEARN entries for a goal."""
        if self._bulletin_store is None or goal_id is None:
            return
        try:
            from agent_core.bulletin.bulletin_model import EntryType
            entries = self._bulletin_store.get_for_goal(goal_id)
            for entry in entries:
                if entry.entry_type in (EntryType.NEED_MATERIAL, EntryType.READY_TO_LEARN):
                    self._bulletin_store.resolve(entry.entry_id, reason)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BULLETIN] Resolve failed: {e}")

    def _transition_bulletin_to_ready(self, goal_id: Optional[str]) -> None:
        """After fetch: mark NEED_MATERIAL -> READY_TO_LEARN for this goal."""
        if self._bulletin_store is None or goal_id is None:
            return
        try:
            from agent_core.bulletin.bulletin_model import EntryType, EntryStatus
            entries = self._bulletin_store.get_for_goal(goal_id)
            for entry in entries:
                if (entry.entry_type == EntryType.NEED_MATERIAL
                        and entry.status != EntryStatus.RESOLVED):
                    self._bulletin_store.create_and_post(
                        entry_type=EntryType.READY_TO_LEARN,
                        topic=entry.topic,
                        reason_code="material_fetched",
                        summary=f"Material pobrany, gotowy do nauki: {entry.topic}",
                        requested_by="action_executor",
                        goal_id=goal_id,
                        priority=entry.priority,
                    )
                    self._bulletin_store.resolve(entry.entry_id, "material_fetched")
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BULLETIN] Transition failed: {e}")
