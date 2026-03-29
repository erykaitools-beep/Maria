"""
Handler factories for CapabilityRouter.

Each factory captures subsystem references via closure and returns
a handler callable: (Plan) -> Dict[str, Any].

Logic is extracted 1:1 from ActionExecutor._exec_* methods.
"""

import logging
import re
import time as _time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def resolve_topics(plan, knowledge_analyzer) -> Optional[List[str]]:
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

    if "resolved_file_ids" in plan.action_params:
        return plan.action_params["resolved_file_ids"] or None

    if knowledge_analyzer is None:
        logger.warning("Topics specified but no KnowledgeAnalyzer available")
        plan.action_params["resolved_file_ids"] = []
        plan.action_params["resolution_report"] = {
            "error": "no_analyzer", "matches": 0,
        }
        return []

    scored_files = knowledge_analyzer.get_files_for_topics(topics)
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
        f"[CapabilityRouter] Resolved topics {topics} -> "
        f"{len(file_ids)} files"
    )
    return file_ids or None


def incremental_index(semantic_search) -> None:
    """Index new knowledge files into semantic memory."""
    try:
        from agent_core.semantic.indexer import index_new_files
        from maria_core.sys.config import BASE_DIR
        index_new_files(
            semantic_search,
            str(BASE_DIR / "memory" / "knowledge_index.jsonl"),
            str(BASE_DIR / "input"),
        )
    except Exception as e:
        logger.debug(f"Incremental indexing skipped: {e}")


def save_expert_response(topic: str, question: str, response: str) -> None:
    """Save expert response as learning material in input/."""
    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower().strip())[:60].strip('_')
    filename = f"expert_{slug}.txt"
    input_dir = Path(__file__).resolve().parents[2] / "input"
    filepath = input_dir / filename

    header = (
        f"# Zrodlo: ChatGPT (Codex CLI)\n"
        f"# Temat: {topic}\n"
        f"# Data: {_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"# Pytanie: {question[:200]}\n\n"
    )
    content = header + response + "\n"

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(content)


def _resolve_notifier(telegram_notifier):
    """Resolve telegram_notifier which may be a callable (late-binding)."""
    if callable(telegram_notifier) and not hasattr(telegram_notifier, 'notify'):
        return telegram_notifier()
    return telegram_notifier


def update_learning_goal(
    plan, result: dict, goal_store, knowledge_analyzer, telegram_notifier,
) -> None:
    """
    CDL feedback loop: update LEARNING goal progress and outcome.

    Called after successful LEARN or EXAM execution.
    telegram_notifier may be a callable (late-binding) or direct reference.
    """
    if not goal_store or not plan.goal_id:
        return

    notifier = _resolve_notifier(telegram_notifier)

    try:
        goal = goal_store.get(plan.goal_id)
        if not goal or goal.type.value != "learning":
            return

        progress = goal.progress
        topics = goal.metadata.get("topics", [])

        if knowledge_analyzer and topics:
            try:
                scored_files = knowledge_analyzer.get_files_for_topics(topics)
                file_ids = [fid for fid, _ in scored_files]
                if file_ids:
                    snapshot = knowledge_analyzer.get_knowledge_snapshot()
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

        if progress > goal.progress:
            goal_store.update_progress(plan.goal_id, progress)

        goal_refreshed = goal_store.get(plan.goal_id)
        if goal_refreshed and goal_refreshed.status.value == "achieved":
            import time
            outcome = {
                "chunks_learned": result.get("chunks_learned", 0),
                "exams_passed": result.get("exams_passed", 0),
                "final_score": result.get("score", 0.0),
                "completed_at": time.time(),
            }
            goal_store.set_outcome(plan.goal_id, outcome)
            goal_store.save()

            topic = goal.metadata.get("topic", goal.description)
            if notifier:
                try:
                    notifier.notify(
                        "learning_complete",
                        f"*Nauka zakonczona: {topic}*\n"
                        f"Wynik: {outcome.get('final_score', 0):.0%}"
                    )
                except Exception:
                    pass
            logger.info(f"[CDL] Learning goal achieved: {topic}")

        elif notifier and progress > goal.progress:
            topic = goal.metadata.get("topic", goal.description)
            try:
                notifier.notify(
                    "learning_progress",
                    f"*Nauka: {topic}*\nPostep: {progress:.0%}"
                )
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"Learning goal update skipped: {e}")


# ---------------------------------------------------------------------------
# Handler factories
# ---------------------------------------------------------------------------

def make_learn_handler(
    teacher_agent,
    knowledge_analyzer=None,
    semantic_search=None,
    goal_store=None,
    telegram_notifier=None,
) -> Callable:
    """Create handler for ActionType.LEARN."""

    def handler(plan) -> Dict[str, Any]:
        if teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        filter_ids = resolve_topics(plan, knowledge_analyzer)
        status = teacher_agent.run_session(
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

        if result["success"] and semantic_search:
            incremental_index(semantic_search)

        if result["success"]:
            update_learning_goal(
                plan, result, goal_store, knowledge_analyzer, telegram_notifier,
            )

        return result

    return handler


def make_exam_handler(
    teacher_agent,
    knowledge_analyzer=None,
    goal_store=None,
    telegram_notifier=None,
) -> Callable:
    """Create handler for ActionType.EXAM."""

    def handler(plan) -> Dict[str, Any]:
        if teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        filter_ids = resolve_topics(plan, knowledge_analyzer)
        status = teacher_agent.run_session(
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

        if result["success"]:
            update_learning_goal(
                plan, result, goal_store, knowledge_analyzer, telegram_notifier,
            )

        return result

    return handler


def make_review_handler(
    teacher_agent,
    knowledge_analyzer=None,
) -> Callable:
    """Create handler for ActionType.REVIEW."""

    def handler(plan) -> Dict[str, Any]:
        if teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        filter_ids = resolve_topics(plan, knowledge_analyzer)
        status = teacher_agent.run_session(
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

    return handler


def make_evaluate_handler(evaluation_observer) -> Callable:
    """Create handler for ActionType.EVALUATE."""

    def handler(plan) -> Dict[str, Any]:
        if evaluation_observer is None:
            return {"success": False, "error": "No evaluation observer configured"}

        try:
            period = plan.action_params.get("period_hours", 1.0)
            report = evaluation_observer.generate_report(period_hours=period)
            return {
                "success": True,
                "report_id": report.report_id,
                "metrics": report.metrics,
                "recommendations": report.recommendations,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return handler


def make_maintenance_handler(homeostasis_core, goal_store=None) -> Callable:
    """Create handler for ActionType.MAINTENANCE."""

    def handler(plan) -> Dict[str, Any]:
        if homeostasis_core is None:
            return {"success": True, "action": "maintenance_noop"}

        state = homeostasis_core.get_state()
        health = state.health_score
        interp = state.interpreted_state or {}

        if goal_store and plan.goal_id:
            goal = goal_store.get(plan.goal_id)
            if goal:
                metric = goal.metadata.get("metric", "")
                threshold = goal.metadata.get("threshold", 0)
                progress = 0.0

                if metric == "health_score" and threshold > 0:
                    progress = min(health / threshold, 1.0)
                elif metric == "cpu_load" and threshold > 0:
                    cpu = interp.get("cpu_load", 0)
                    progress = 1.0 if cpu < threshold else max(
                        0.0, 1.0 - (cpu - threshold) / threshold,
                    )
                elif metric == "ram_available_pct" and threshold > 0:
                    ram = interp.get("ram_available_pct", 0)
                    progress = min(ram / threshold, 1.0)

                goal_store.update_progress(plan.goal_id, progress)
                goal_store.save()

        return {
            "success": True,
            "health_score": health,
            "mode": state.mode.value,
        }

    return handler


def make_fetch_handler(
    knowledge_analyzer,
    semantic_search=None,
) -> Callable:
    """Create handler for ActionType.FETCH."""

    def handler(plan) -> Dict[str, Any]:
        if knowledge_analyzer is None:
            return {"success": False, "error": "No knowledge analyzer configured"}

        try:
            from agent_core.web_source import run_fetch_session

            max_articles = plan.action_params.get("max_articles", 3)
            result = run_fetch_session(
                knowledge_analyzer=knowledge_analyzer,
                max_articles=max_articles,
                semantic_memory=semantic_search,
            )
            errors = result.get("errors", 0)

            if semantic_search and result.get("articles_fetched", 0) > 0:
                incremental_index(semantic_search)

            return {
                "success": errors == 0,
                "articles_fetched": result.get("articles_fetched", 0),
                "topics_searched": result.get("topics_searched", 0),
                "errors": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return handler


def make_experiment_handler(experiment_system) -> Callable:
    """Create handler for ActionType.EXPERIMENT."""

    def handler(plan) -> Dict[str, Any]:
        if experiment_system is None:
            return {"success": False, "error": "No experiment system configured"}

        proposal_id = plan.action_params.get("proposal_id")
        if not proposal_id:
            return {"success": False, "error": "No proposal_id in action_params"}

        try:
            report = experiment_system.run_experiment(proposal_id)
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

    return handler


def make_effector_handler(openclaw_client) -> Callable:
    """Create handler for ActionType.EFFECTOR."""

    def handler(plan) -> Dict[str, Any]:
        if openclaw_client is None:
            return {"success": False, "error": "No OpenClaw client configured"}

        tool_name = plan.action_params.get("tool_name")
        tool_args = plan.action_params.get("tool_args", {})

        if not tool_name:
            return {"success": False, "error": "No tool_name in action_params"}

        try:
            response = openclaw_client.invoke_tool(
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

    return handler


def make_self_analyze_handler(
    self_analysis,
    telegram_notifier=None,
) -> Callable:
    """Create handler for ActionType.SELF_ANALYZE."""

    def handler(plan) -> Dict[str, Any]:
        if self_analysis is None:
            return {"success": False, "error": "No self_analysis configured"}

        try:
            period = plan.action_params.get("period_days", 7)
            report = self_analysis.run_analysis(period_days=period)

            if report.error:
                return {
                    "success": False,
                    "error": report.error,
                    "report_id": report.report_id,
                }

            notifier = _resolve_notifier(telegram_notifier)
            if notifier and report.recommendations:
                try:
                    summary = report.analysis_text[:300] if report.analysis_text else ""
                    recs = [
                        r if isinstance(r, str) else str(r)
                        for r in report.recommendations
                    ]
                    notifier.notify_self_analysis(summary, recs)
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

    return handler


def make_creative_handler(
    creative_module,
    telegram_notifier=None,
) -> Callable:
    """Create handler for ActionType.CREATIVE."""

    def handler(plan) -> Dict[str, Any]:
        if creative_module is None:
            return {"success": False, "error": "No creative module configured"}

        try:
            trigger = plan.action_params.get("trigger", "planner")
            result = creative_module.reflect(trigger=trigger)

            notifier = _resolve_notifier(telegram_notifier)
            if notifier and result.get("success"):
                try:
                    tensions = result.get("tensions", [])
                    if tensions:
                        notifier.notify_creative_tensions(tensions)
                    meta_goals = result.get("meta_goals_created", [])
                    if meta_goals:
                        notifier.notify_creative_meta_goals(meta_goals)
                except Exception:
                    pass

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    return handler


def make_ask_expert_handler(llm_router) -> Callable:
    """Create handler for ActionType.ASK_EXPERT."""

    def handler(plan) -> Dict[str, Any]:
        if llm_router is None or not hasattr(llm_router, 'ask_encyclopedia'):
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

            response = llm_router.ask_encyclopedia(
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
                    save_expert_response(topic, question, response)
                    result["saved_to_input"] = True
                except Exception:
                    result["saved_to_input"] = False

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    return handler


def make_validate_handler(
    cross_validator,
    world_model=None,
    knowledge_analyzer=None,
) -> Callable:
    """Create handler for ActionType.VALIDATE."""

    def _pick_validation_candidate() -> str:
        """Pick a completed file that hasn't been validated recently."""
        if not knowledge_analyzer:
            return ""
        try:
            snapshot = knowledge_analyzer.get_knowledge_snapshot()
            completed = snapshot.get("files_by_status", {}).get("completed", [])
            if completed:
                return completed[0]
        except Exception:
            pass
        return ""

    def _update_beliefs_from_validation(file_id: str, avg_confidence: float) -> int:
        """Update belief confidence for beliefs related to a validated file."""
        if not world_model:
            return 0

        try:
            from agent_core.world_model.belief_model import BeliefType

            store = world_model.store
            beliefs = [
                b for b in store.get_current()
                if b.source_id == file_id
            ]

            updated = 0
            for belief in beliefs:
                new_conf = belief.confidence * 0.6 + avg_confidence * 0.4

                new_type = None
                if avg_confidence >= 0.7 and belief.belief_type == BeliefType.OBSERVATION:
                    new_type = BeliefType.FACT
                elif avg_confidence < 0.3 and belief.belief_type != BeliefType.HYPOTHESIS:
                    new_type = BeliefType.HYPOTHESIS

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

    def handler(plan) -> Dict[str, Any]:
        if cross_validator is None:
            return {"success": False, "error": "No CrossValidator configured"}

        file_id = plan.action_params.get("file_id", "")
        if not file_id:
            file_id = _pick_validation_candidate()
            if not file_id:
                return {"success": False, "error": "No files ready for validation"}

        try:
            from maria_core.sys.config import LONGTERM_MEMORY, INPUT_DIR
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

            result = cross_validator.validate_file(
                file_id=file_id,
                chunk_texts=chunk_texts,
                memory_records=memories,
                max_chunks=5,
            )

            beliefs_updated = _update_beliefs_from_validation(
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

    return handler


def make_noop_handler() -> Callable:
    """Create handler for ActionType.NOOP."""

    def handler(plan) -> Dict[str, Any]:
        return {"success": True, "action": "noop"}

    return handler
