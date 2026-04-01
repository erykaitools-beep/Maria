"""
ActionExecutor - Delegates plan execution to Teacher/Sandbox.

Planner decides WHAT, Executor does HOW.
Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import logging
import time
from typing import Any, Dict, Optional

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

    def set_cross_validator(self, validator) -> None:
        """Set CrossValidator for multi-source learning (Faza F)."""
        self._cross_validator = validator

    def set_critic_agent(self, critic) -> None:
        """Set CriticAgent for knowledge quality gate (Faza G)."""
        self._critic_agent = critic

    def set_world_model(self, world_model) -> None:
        """Set WorldModel for belief confidence updates (Faza F)."""
        self._world_model = world_model

    def execute(self, plan: Plan) -> Dict[str, Any]:
        """
        Execute a plan. Returns result dict.

        Args:
            plan: The Plan to execute

        Returns:
            Dict with at least {"success": bool, ...}
        """
        # Registry-based dispatch (Phase B: dual-path)
        if self._capability_router is not None:
            return self._capability_router.dispatch(plan)

        # Legacy dispatch (backward compat, removed in Phase C)
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
            elif action == ActionType.VALIDATE:
                result = self._exec_validate(plan)
            elif action == ActionType.CRITIQUE:
                result = self._exec_critique(plan)
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

        # CDL feedback: update learning goal progress
        if result["success"]:
            self._update_learning_goal(plan, result)

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
            # Pass user-requested topics from conversation goals
            override_topics = plan.action_params.get("topics")
            result = run_fetch_session(
                knowledge_analyzer=self._knowledge_analyzer,
                max_articles=max_articles,
                semantic_memory=self._semantic_search,
                override_topics=override_topics,
            )
            errors = result.get("errors", 0)

            # Incremental indexing: embed newly fetched files
            if self._semantic_search and result.get("articles_fetched", 0) > 0:
                self._incremental_index()

            fetched = result.get("articles_fetched", 0)
            if fetched > 0:
                # Material arrived -> update bulletin: NEED_MATERIAL -> READY_TO_LEARN
                self._transition_bulletin_to_ready(plan.goal_id)

            return {
                "success": errors == 0,
                "articles_fetched": fetched,
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
                    return {
                        "success": False, "error": resp.reason,
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
                store.flush()
                logger.info(
                    f"[Faza F] Updated {updated} beliefs for {file_id} "
                    f"(avg_confidence={avg_confidence:.2f})"
                )
            return updated
        except Exception as e:
            logger.debug(f"Belief update skipped: {e}")
            return 0

    def _update_learning_goal(self, plan, result: dict) -> None:
        """
        CDL feedback loop: update LEARNING goal progress and outcome.

        Called after successful LEARN or EXAM execution.
        Computes progress from knowledge snapshot if available,
        sends Telegram notification, sets outcome on completion.
        """
        if not self._goal_store or not plan.goal_id:
            return

        try:
            goal = self._goal_store.get(plan.goal_id)
            if not goal or goal.type.value != "learning":
                return

            # Compute progress from knowledge state
            progress = goal.progress
            topics = goal.metadata.get("topics", [])

            if self._knowledge_analyzer and topics:
                try:
                    scored_files = self._knowledge_analyzer.get_files_for_topics(topics)
                    file_ids = [fid for fid, _ in scored_files]
                    if file_ids:
                        snapshot = self._knowledge_analyzer.get_knowledge_snapshot()
                        completed = snapshot.get("files_by_status", {}).get("completed", [])
                        done = sum(1 for f in file_ids if f in completed)
                        progress = done / len(file_ids) if file_ids else 0.0
                except Exception:
                    pass

            # Fallback: increment progress
            if progress <= goal.progress:
                chunks = result.get("chunks_learned", 0)
                exams_passed = result.get("exams_passed", 0)
                if chunks > 0:
                    progress = min(0.9, goal.progress + 0.1)
                if exams_passed > 0:
                    progress = min(1.0, goal.progress + 0.2)

            # Update goal progress
            if progress > goal.progress:
                self._goal_store.update_progress(plan.goal_id, progress)

            # Check if goal just completed (progress >= 1.0)
            goal_refreshed = self._goal_store.get(plan.goal_id)
            if goal_refreshed and goal_refreshed.status.value == "achieved":
                outcome = {
                    "chunks_learned": result.get("chunks_learned", 0),
                    "exams_passed": result.get("exams_passed", 0),
                    "final_score": result.get("score", 0.0),
                    "completed_at": time.time(),
                }
                self._goal_store.set_outcome(plan.goal_id, outcome)
                self._goal_store.save()

                # Notify operator
                topic = goal.metadata.get("topic", goal.description)
                if self._telegram_notifier:
                    try:
                        self._telegram_notifier.notify(
                            "learning_complete",
                            f"*Nauka zakonczona: {topic}*\n"
                            f"Wynik: {outcome.get('final_score', 0):.0%}"
                        )
                    except Exception:
                        pass
                logger.info(f"[CDL] Learning goal achieved: {topic}")

            elif self._telegram_notifier and progress > goal.progress:
                # Progress update (with cooldown in notifier)
                topic = goal.metadata.get("topic", goal.description)
                try:
                    self._telegram_notifier.notify(
                        "learning_progress",
                        f"*Nauka: {topic}*\nPostep: {progress:.0%}"
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Learning goal update skipped: {e}")

    # -- Faza G: Knowledge critique (deprecated legacy path) ---------

    def _exec_critique(self, plan: Plan) -> Dict[str, Any]:
        """Knowledge quality critique (Faza G). Legacy fallback."""
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

            return {
                "success": True,
                "report_id": report.report_id,
                "findings": len(report.findings),
                "goals_created": report.goals_created,
                "duration_ms": report.duration_ms,
            }
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
