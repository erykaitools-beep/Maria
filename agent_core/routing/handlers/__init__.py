"""
Handler factories for CapabilityRouter.

Each factory captures subsystem references via closure and returns
a handler callable: (Plan) -> Dict[str, Any].

Logic is extracted 1:1 from ActionExecutor._exec_* methods.
"""

import logging
import os
import re
import time as _time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _is_outside_learning_window(plan) -> bool:
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
        return False


def resolve_topics(plan, knowledge_analyzer) -> Optional[List[str]]:
    """
    Resolve topics from plan.action_params to file_ids.

    If action_params has 'topics' but not 'resolved_file_ids',
    uses KnowledgeAnalyzer to resolve. Stores result back in action_params.

    Returns:
        List of file_ids (may be empty), or None if no topic filter.
    """
    if "resolved_file_ids" in plan.action_params:
        return plan.action_params["resolved_file_ids"] or None

    topics = plan.action_params.get("topics")
    if not topics:
        return None

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


def _path_attr(obj, attr: str) -> Optional[Path]:
    value = getattr(obj, attr, None)
    if isinstance(value, (str, os.PathLike)):
        return Path(value)
    return None


def _register_fetch_handoff_goal(
    plan,
    result: Dict[str, Any],
    knowledge_analyzer,
    goal_store,
    backfill: bool = False,
) -> List[str]:
    """Persist a scoped learning goal for files produced by a fetch session.

    backfill=True marks an obligation created by the P4 orphan sweep (files that
    reached the index with no handoff goal) rather than a live fetch action. It
    is a telemetry flag only -- the goal is otherwise identical, so it inherits
    the fetch_handoff selector priority and the 30d stale window (P3).
    """
    fetched_files = [
        str(name) for name in result.get("fetched_files", [])
        if isinstance(name, str) and name.strip()
    ]
    if not fetched_files:
        return []

    try:
        from maria_core.perception.perception import scan_input_directory
        from maria_core.sys.config import INPUT_DIR, KNOWLEDGE_INDEX

        input_dir = _path_attr(knowledge_analyzer, "input_dir") or INPUT_DIR
        index_path = _path_attr(knowledge_analyzer, "index_path") or KNOWLEDGE_INDEX
        scan_input_directory(input_dir, index_path)
    except Exception as e:
        logger.debug(f"Fetch-to-learn scan skipped: {e}")

    if goal_store is None:
        return fetched_files

    try:
        from agent_core.goals.goal_model import (
            AuditEntry,
            GoalStatus,
            GoalType,
            create_goal,
        )

        active_handoffs = [
            goal for goal in goal_store.get_active(GoalType.LEARNING)
            if goal.metadata.get("source") == "fetch_handoff"
        ]
        if active_handoffs:
            goal = active_handoffs[0]
            existing = list(goal.metadata.get("file_ids", []))
            merged = list(dict.fromkeys(existing + fetched_files))
            if merged != existing:
                now = _time.time()
                goal.metadata["file_ids"] = merged
                goal.metadata["fetched_file_ids"] = merged
                goal.metadata["updated_by_fetch_at"] = now
                goal.updated_at = now
                goal.audit_trail.append(AuditEntry(
                    timestamp=now,
                    old_status=goal.status.value,
                    new_status=goal.status.value,
                    reason="merged backfilled files" if backfill
                    else "merged fetched files",
                    actor="planner",
                ))
                if hasattr(goal_store, "_mark_dirty"):
                    goal_store._mark_dirty(goal.id)
                goal_store.save()
            return fetched_files

        preview = ", ".join(fetched_files[:3])
        if len(fetched_files) > 3:
            preview += f" (+{len(fetched_files) - 3})"
        goal = create_goal(
            goal_type=GoalType.LEARNING,
            description=f"Naucz sie pobranych materialow: {preview}",
            priority=1.0,
            status=GoalStatus.PENDING,
            created_by="system",
            metadata={
                "source": "fetch_handoff",
                "file_ids": fetched_files,
                "fetched_file_ids": fetched_files,
                "trigger_goal_id": getattr(plan, "goal_id", None),
                "created_by_action": "fetch_backfill" if backfill else "fetch",
                "backfill": backfill,
                "risk_level": "low",
            },
        )
        goal_store.create(goal)
        goal_store.save()
    except Exception as e:
        logger.debug(f"Fetch-to-learn goal registration skipped: {e}")

    return fetched_files


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


# Garbage-response guard thresholds. Raised after 2026-04-21 discovery:
# input/expert_*.txt was accumulating LLM hallucinations ("yyyyy..." x200,
# "zzzz..." x200, placeholder stubs like "Expert answer") over ~a week.
# Maria was then trying to learn from these files — strategies ran but
# produced 0 chunks because content was effectively empty. See
# project_glm51_architecture_findings.md, Finding B.
MIN_EXPERT_RESPONSE_LEN = 200          # chars after strip
MAX_REPEATED_CHAR_RUN = 49             # flag runs of 50+ same char
MIN_CHAR_VARIETY = 5                   # unique chars in body
PLACEHOLDER_RESPONSES = {
    "",
    "expert answer",
    "legacy answer",
    "odpowiedz eksperta",
    "odpowiedź eksperta",
}


def _classify_expert_response(response: str) -> Optional[str]:
    """Detect garbage expert responses. Returns reject reason or None if OK."""
    body = (response or "").strip()
    if not body:
        return "empty"
    if body.lower() in PLACEHOLDER_RESPONSES:
        return f"placeholder: {body[:40]!r}"
    if len(body) < MIN_EXPERT_RESPONSE_LEN:
        return f"too_short: {len(body)} < {MIN_EXPERT_RESPONSE_LEN} chars"
    if re.search(rf"(.)\1{{{MAX_REPEATED_CHAR_RUN},}}", body):
        return f"repeated_char_run: >{MAX_REPEATED_CHAR_RUN} consecutive"
    if len(set(body.lower())) < MIN_CHAR_VARIETY:
        return f"low_variety: {len(set(body.lower()))} unique chars"
    return None


def save_expert_response(topic: str, question: str, response: str) -> None:
    """Save expert response as learning material in input/.

    Rejects garbage responses (placeholder strings, repeated-char runs,
    too-short bodies) with ValueError so callers can mark the save as
    failed without polluting the learning corpus.
    """
    reject_reason = _classify_expert_response(response)
    if reject_reason:
        logger.warning(
            f"[ASK_EXPERT] Refused to save garbage response for topic="
            f"{topic!r}: {reject_reason}"
        )
        raise ValueError(f"garbage_response: {reject_reason}")

    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower().strip())[:60].strip('_')
    filename = f"expert_{slug}.txt"
    input_dir = _project_root() / "input"
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


def _project_root() -> Path:
    """Return repository root from the routing handlers package."""
    path = Path(__file__).resolve()
    if path.parent.name == "handlers":
        return path.parents[3]
    return path.parents[2]


def _resolve_notifier(telegram_notifier):
    """Resolve telegram_notifier which may be a callable (late-binding)."""
    if callable(telegram_notifier) and not hasattr(telegram_notifier, 'notify'):
        return telegram_notifier()
    return telegram_notifier


def resolve_goal_files(goal, action_params=None, knowledge_analyzer=None) -> list:
    """Resolve the set of files a learning goal 'owns', in priority order:
      1) explicit file_ids persisted on the goal (e.g. fetch-handoff)
      2) files resolved for THIS action (the exact scope worked on)
      3) the goal's topic(s), re-matched via the analyzer
    Accepts both 'topics' (plural) and 'topic' (singular). Single source of
    truth for the goal<->knowledge mapping -- shared by progress credit
    (update_learning_goal) and the reconciliation sweep so they cannot drift.
    """
    files = list(
        goal.metadata.get("file_ids")
        or goal.metadata.get("fetched_file_ids")
        or (action_params or {}).get("resolved_file_ids")
        or []
    )
    if files:
        return files
    topics = list(goal.metadata.get("topics") or [])
    single = goal.metadata.get("topic")
    if single and single not in topics:
        topics.append(single)
    if knowledge_analyzer and topics:
        try:
            return [fid for fid, _ in knowledge_analyzer.get_files_for_topics(topics)]
        except Exception:
            return []
    return []


def completed_file_ids(knowledge_snapshot) -> set:
    """Set of file ids whose knowledge_index status is 'completed'.

    NOTE: 'completed' is set by ANY exam scoring >= the pass bar, INCLUDING a
    self-graded one -- it is NOT proof of an independent pass. For the
    trusted-DONE subset (files an INDEPENDENT examiner verified) use
    :func:`independently_verified_completed_ids`; that, not this, is what may
    force-close a learning goal. This set is the broader "studied + scored"
    view. files_by_status holds record dicts, so match on each record's id
    -- not the dict itself (the historical bug that froze topic goals at 0).

    P5 (#4): a content-duplicate (status='duplicate') is never learned on its
    own, so it counts as completed IFF its canonical original is completed --
    otherwise a handoff goal holding both a file and its dedup'd twin could
    never reach 1.0.
    """
    by_status = (knowledge_snapshot or {}).get("files_by_status", {})
    completed = {
        (rec.get("id") or rec.get("file"))
        for rec in by_status.get("completed", [])
    }
    for rec in by_status.get("duplicate", []):
        if rec.get("duplicate_of") in completed:
            completed.add(rec.get("id") or rec.get("file"))
    return completed


def independently_verified_completed_ids(knowledge_snapshot, *, verified_ids=None) -> set:
    """The trusted-DONE subset of completed_file_ids: files an INDEPENDENT
    examiner verified (grader_independent==True, score >= pass), NOT self-graded.

    This is the ONLY set allowed to force-close a learning goal (audit
    2026-06-01: closing on the self-graded 'completed' status made the
    'closes on independently-verified knowledge' claim false on the path that
    runs). A duplicate inherits its canonical's verification, mirroring the P5
    dup rule in completed_file_ids -- but only when the canonical is genuinely
    independently verified.

    ``verified_ids`` lets a caller read exam_results once and reuse the set
    across many goals (and lets tests inject); when None it is resolved via
    success_criteria.independently_verified_file_ids().
    """
    if verified_ids is None:
        from agent_core.goals.success_criteria import independently_verified_file_ids
        verified_ids = independently_verified_file_ids()
    by_status = (knowledge_snapshot or {}).get("files_by_status", {})
    verified = {
        fid for rec in by_status.get("completed", [])
        for fid in ((rec.get("id") or rec.get("file")),)
        if fid in verified_ids
    }
    for rec in by_status.get("duplicate", []):
        if rec.get("duplicate_of") in verified:
            verified.add(rec.get("id") or rec.get("file"))
    return verified


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
        scoped_file_ids = resolve_goal_files(
            goal, plan.action_params, knowledge_analyzer,
        )

        # Progress = fraction of owned files INDEPENDENTLY exam-verified (a
        # different model graded the recall, not the student self-grading its
        # own 'completed' flag). progress >= 1.0 auto-ACHIEVES the goal, so this
        # gate is what makes "learning goal closed == independently verified"
        # true on the path that runs (audit 2026-06-01). "read"/"self-graded"
        # != "verified".
        file_based = False
        if knowledge_analyzer and scoped_file_ids:
            try:
                verified_ids = independently_verified_completed_ids(
                    knowledge_analyzer.get_knowledge_snapshot()
                )
                done = sum(1 for fid in scoped_file_ids if fid in verified_ids)
                progress = done / len(scoped_file_ids)
                file_based = True
            except Exception:
                pass

        # Fallback only when no files could be resolved: nudge progress so a
        # genuinely-working goal still shows movement. A goal with a resolvable
        # file set is judged solely on exam-verified completion above.
        if not file_based and progress <= goal.progress:
            if result.get("exams_passed", 0) > 0:
                progress = min(1.0, goal.progress + 0.2)
            elif result.get("chunks_learned", 0) > 0:
                progress = min(0.9, goal.progress + 0.1)

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


def close_goal_on_criteria(
    plan, result: dict, goal_store, *, sandbox_root=None, telegram_notifier=None,
) -> None:
    """Close a goal when ALL its machine-checkable success_criteria are met (B2).

    The criteria-based sibling of update_learning_goal: for goals whose closure
    is an externally-checkable fact (a file exists, a marker is in a log).
    Re-evaluates the goal's success_criteria against reality and, only on a full
    pass, sets progress=1.0 (-> auto-ACHIEVED) + records the evidence. Never
    closes on a self-reported flag -- the evidence is re-checked here.
    """
    if not goal_store or not getattr(plan, "goal_id", None):
        return
    try:
        goal = goal_store.get(plan.goal_id)
        if not goal or not getattr(goal, "success_criteria", None):
            return
        from agent_core.goals.success_criteria import evaluate_criteria
        passed, evidence = evaluate_criteria(
            goal.success_criteria, sandbox_root=sandbox_root,
        )
        if not passed:
            return
        goal_store.update_progress(plan.goal_id, 1.0)
        refreshed = goal_store.get(plan.goal_id)
        if refreshed and refreshed.status.value == "achieved":
            import time
            goal_store.set_outcome(plan.goal_id, {
                "closed_by": "success_criteria",
                "evidence": evidence,
                "completed_at": time.time(),
            })
            goal_store.save()
            logger.info(
                "[criteria] Goal achieved via success_criteria: %s", plan.goal_id
            )
            notifier = _resolve_notifier(telegram_notifier)
            if notifier:
                try:
                    notifier.notify(
                        "goal_complete",
                        f"*Cel domkniety (dowod zewnetrzny):*\n{goal.description}",
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Criteria goal close skipped: {e}")


def seed_first_action_goal(
    goal_store, base_dir=None, filename: str = "maria_first_action.txt",
) -> Optional[str]:
    """Create the demonstration goal for the first real effector action (B2).

    An ACTIVE goal whose only success_criterion is that a file exists in the
    sandbox. With FS_WRITE_ENABLED on, the planner writes that file and the goal
    closes on external evidence. Returns the goal id (or None).
    """
    if goal_store is None:
        return None
    from pathlib import Path
    from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
    from agent_core.hands.sandbox_writer import default_sandbox_root
    if base_dir is None:
        try:
            from maria_core.sys.config import BASE_DIR
            base_dir = BASE_DIR
        except Exception:
            base_dir = "."
    target = str(Path(default_sandbox_root(base_dir)) / filename)
    goal = create_goal(
        goal_type=GoalType.USER,
        description="B2: write the first real file to the world (sandbox)",
        priority=0.95,
        status=GoalStatus.ACTIVE,
        created_by="operator",
        success_criteria=[{"type": "file_exists", "path": target}],
        metadata={"b2_demo": True},
    )
    goal_store.create(goal)
    goal_store.save()
    logger.info("[B2] seeded first-action goal %s -> %s", goal.id, target)
    return goal.id


def seed_heldout_exam_goal(
    goal_store, file_id: str = "web_wiki_chemia.txt", min_score: float = 0.6,
) -> Optional[str]:
    """Create the demonstration goal for the first independent-exam closure (B4).

    An ACTIVE goal whose only success_criterion is that ``file_id`` clears an
    INDEPENDENT held-out exam (a grader_independent record in exam_results.jsonl
    at/above min_score). With the heldout flag on, the planner re-examines the
    file and the goal closes on that recorded verdict -- the learning sibling of
    seed_first_action_goal (B2). Returns the goal id (or None).
    """
    if goal_store is None:
        return None
    from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
    goal = create_goal(
        goal_type=GoalType.USER,
        description=f"B4: prove '{file_id}' by an independent held-out exam",
        priority=0.95,
        status=GoalStatus.ACTIVE,
        created_by="operator",
        success_criteria=[{
            "type": "exam_independent", "file": file_id, "min_score": min_score,
        }],
        metadata={"b4_demo": True, "topic": file_id},
    )
    goal_store.create(goal)
    goal_store.save()
    logger.info("[B4] seeded held-out exam goal %s -> %s", goal.id, file_id)
    return goal.id


# ---------------------------------------------------------------------------
# Handler factories
# ---------------------------------------------------------------------------

def make_fs_write_handler(
    goal_store=None, base_dir=None, telegram_notifier=None,
) -> Callable:
    """Create handler for ActionType.FS_WRITE (B2).

    Writes one small file into the dedicated sandbox (shared SSoT
    agent_core/hands/sandbox_writer.sandbox_write) and, on success, closes the
    plan's goal if its success_criteria are now met (external evidence).
    """

    def handler(plan) -> Dict[str, Any]:
        from agent_core.hands.sandbox_writer import (
            sandbox_write, default_sandbox_root,
        )
        params = getattr(plan, "action_params", None) or {}
        sandbox_root = params.get("sandbox_root")
        if not sandbox_root:
            root_base = base_dir
            if root_base is None:
                try:
                    from maria_core.sys.config import BASE_DIR
                    root_base = BASE_DIR
                except Exception:
                    root_base = "."
            sandbox_root = default_sandbox_root(root_base)
        filename = params.get("filename") or params.get("path") or "maria_action"
        content = params.get("content", "")
        result = sandbox_write(filename, content, sandbox_root=sandbox_root)
        if result.get("success"):
            close_goal_on_criteria(
                plan, result, goal_store,
                sandbox_root=sandbox_root, telegram_notifier=telegram_notifier,
            )
        return result

    return handler

def make_learn_handler(
    teacher_agent,
    knowledge_analyzer=None,
    semantic_search=None,
    goal_store=None,
    telegram_notifier=None,
    consciousness=None,
) -> Callable:
    """Create handler for ActionType.LEARN."""

    def handler(plan) -> Dict[str, Any]:
        if teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        if _is_outside_learning_window(plan):
            return {"success": False, "skipped": True,
                    "reason": "outside_learning_window"}

        filter_ids = resolve_topics(plan, knowledge_analyzer)
        status = teacher_agent.run_session(
            max_iterations=1, filter_file_ids=filter_ids,
        )
        stats = status.get("stats", {})
        chunks = stats.get("chunks_learned", 0)
        strategies_executed = stats.get("strategies_executed", 0)
        idle_reason = stats.get("idle_reason")
        result = {
            "success": chunks > 0,
            "chunks_learned": chunks,
            "strategies_executed": strategies_executed,
        }
        if idle_reason:
            result["idle_reason"] = idle_reason
            result["filtered_out_count"] = stats.get("filtered_out_count", 0)
        # B3 fix (audit 2026-05-17): teacher_agent may pick a non-chunking
        # strategy (REVIEW/exam) when no fresh files are available. That is
        # not a learn failure — mark as skipped so K7 backoff and K9
        # negative-outcome reflection do not kick in. Distinguishes
        # "nothing to learn right now" from "tried to chunk and failed".
        if chunks == 0 and (idle_reason or strategies_executed > 0):
            result["skipped"] = True
            result["reason"] = idle_reason or "non_chunking_strategy"

        if result["success"] and semantic_search:
            incremental_index(semantic_search)

        if result["success"]:
            update_learning_goal(
                plan, result, goal_store, knowledge_analyzer, telegram_notifier,
            )
            # Personality signals (C6 fix). Both events feed `ciekawska`,
            # learning_completed also feeds `systematyczna`.
            from agent_core.consciousness import record_experience
            topics = plan.action_params.get("topics") or []
            record_experience(
                consciousness,
                "learning_completed",
                {"chunks": chunks, "topics": topics[:5]},
            )
            if topics:
                record_experience(
                    consciousness,
                    "unknown_terms_found",
                    {"topics": topics[:5]},
                )

        return result

    return handler


def make_exam_handler(
    teacher_agent,
    knowledge_analyzer=None,
    goal_store=None,
    telegram_notifier=None,
    consciousness=None,
) -> Callable:
    """Create handler for ActionType.EXAM."""

    def handler(plan) -> Dict[str, Any]:
        if teacher_agent is None:
            return {"success": False, "error": "No teacher agent configured"}

        params = getattr(plan, "action_params", None) or {}
        target_file_id = params.get("target_file_id")

        if target_file_id:
            # B4 drill: examine ONE specific file directly (spaced-repetition
            # path), bypassing run_session's own action choice -- so a goal
            # behind an exam_independent criterion is actually re-examined even
            # if its file is already 'completed'. Held-out grading is gated by
            # HELDOUT_GRADER_ENABLED, which the exam pipeline (_run_exam_fn)
            # reads; here we just drive the file through it.
            exam_fn = getattr(teacher_agent, "_run_exam_fn", None)
            if exam_fn is None:
                return {"success": False, "error": "teacher_agent has no exam fn"}
            try:
                r = exam_fn(target_file_id) or {}
            except Exception as e:
                return {"success": False, "error": f"exam failed: {e}"}
            result = {
                "success": bool(r.get("success")),
                "exams_run": 1 if r.get("success") else 0,
                "exams_passed": 1 if r.get("passed") else 0,
                "score": r.get("score", 0.0),
                "file": r.get("file_id", target_file_id),
                "source": params.get("source", "heldout_drill"),
            }
        else:
            if _is_outside_learning_window(plan):
                return {"success": False, "skipped": True,
                        "reason": "outside_learning_window"}

            filter_ids = resolve_topics(plan, knowledge_analyzer)
            status = teacher_agent.run_session(
                max_iterations=1, filter_file_ids=filter_ids,
            )
            stats = status.get("stats", {})
            exams_run = stats.get("exams_run", 0)
            pipeline_failures = stats.get("exam_pipeline_failures", 0)
            strategies_executed = stats.get("strategies_executed", 0)
            result = {
                "success": exams_run > 0,
                "exams_run": exams_run,
                "exams_passed": stats.get("exams_passed", 0),
                "score": stats.get("last_exam_score", 0.0),
                "file": stats.get("last_exam_file", ""),
            }
            idle_reason = stats.get("idle_reason")
            if idle_reason:
                result["idle_reason"] = idle_reason
            # C fix (2026-06-05): run_session(1) picks its OWN strategy. When it
            # legitimately does non-exam work (learn/fill_gap) or is idle (all
            # files completed / parked in the 6h exam cooldown), exams_run==0 --
            # but that is NOT an exam failure. Reporting success=False here
            # inflated the action_failure_storm: idle/redirect cycles counted as
            # failed exams (23/40 of the 06-01..06-05 storm were ~0.1s no-op
            # "fails"). A GENUINE failed exam attempt raises exam_pipeline_failures
            # (per-call stats are reset at run_session start), which we still
            # surface as success=False below.
            if exams_run == 0 and pipeline_failures == 0 and (
                idle_reason or strategies_executed > 0
            ):
                result["success"] = True
                result["skipped"] = True

        # Exam-specific side effects only on a REAL exam (exams_run>0): a skipped
        # no-op must not record an "exam_failed" experience or touch the goal.
        if result["success"] and result.get("exams_run", 0) > 0:
            update_learning_goal(
                plan, result, goal_store, knowledge_analyzer, telegram_notifier,
            )
            # B4: close the goal if its exam_independent criterion now holds --
            # re-checked against the just-written exam_results entry (the closer
            # trusts only grader_independent==True records, not a status flag).
            close_goal_on_criteria(
                plan, result, goal_store, telegram_notifier=telegram_notifier,
            )
            # Personality signals (C6 fix). Pass/fail feeds `systematyczna`
            # in opposite directions per trait_catalog.
            from agent_core.consciousness import record_experience
            event = "exam_passed" if result["exams_passed"] > 0 else "exam_failed"
            record_experience(
                consciousness,
                event,
                {
                    "score": result["score"],
                    "file": result["file"],
                    "exams_run": result["exams_run"],
                    "exams_passed": result["exams_passed"],
                },
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

        if _is_outside_learning_window(plan):
            return {"success": False, "skipped": True,
                    "reason": "outside_learning_window"}

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
    goal_store=None,
) -> Callable:
    """Create handler for ActionType.FETCH."""

    def handler(plan) -> Dict[str, Any]:
        from agent_core.web_source.decision_log import log_fetch_decision
        started = _time.time()

        if knowledge_analyzer is None:
            log_fetch_decision(
                plan,
                outcome="error",
                duration_ms=(_time.time() - started) * 1000,
                error="No knowledge analyzer configured",
            )
            return {"success": False, "error": "No knowledge analyzer configured"}

        if _is_outside_learning_window(plan):
            log_fetch_decision(
                plan,
                outcome="skipped",
                duration_ms=(_time.time() - started) * 1000,
                skipped_reason="outside_learning_window",
            )
            return {"success": False, "skipped": True,
                    "reason": "outside_learning_window"}

        try:
            from agent_core.web_source import run_fetch_session

            max_articles = plan.action_params.get("max_articles", 3)
            # Pass user-requested topics from conversation goals
            override_topics = plan.action_params.get("topics")
            result = run_fetch_session(
                knowledge_analyzer=knowledge_analyzer,
                max_articles=max_articles,
                semantic_memory=semantic_search,
                override_topics=override_topics,
            )
            errors = result.get("errors", 0)
            articles = result.get("articles_fetched", 0)

            if semantic_search and articles > 0:
                incremental_index(semantic_search)

            handoff_files = []
            # P1: bind a learn-obligation whenever a fetch actually WROTE files,
            # even if the session also hit errors on other topics. content_writer
            # persists each file individually (and registers it) before any
            # aggregate error check, so the old `errors == 0` gate orphaned real
            # bytes on disk whenever one topic failed after another succeeded --
            # the live web_rss_* leak. fetched_files moves in lockstep with
            # articles_fetched, so this still covers the plain articles>0 case.
            if result.get("fetched_files"):
                handoff_files = _register_fetch_handoff_goal(
                    plan, result, knowledge_analyzer, goal_store,
                )

            if errors > 0:
                outcome = "error"
            elif articles == 0:
                outcome = "no_articles"
            elif articles < max_articles:
                outcome = "partial"
            else:
                outcome = "success"

            log_fetch_decision(
                plan,
                outcome=outcome,
                duration_ms=(_time.time() - started) * 1000,
                result=result,
            )

            return {
                "success": errors == 0,
                "articles_fetched": articles,
                "fetched_files": result.get("fetched_files", []),
                "learn_handoff_files": handoff_files,
                "topics_searched": result.get("topics_searched", 0),
                "errors": errors,
            }
        except Exception as e:
            log_fetch_decision(
                plan,
                outcome="error",
                duration_ms=(_time.time() - started) * 1000,
                error=str(e),
            )
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


def make_effector_handler(openclaw_client, effector_coordinator=None) -> Callable:
    """Create handler for ActionType.EFFECTOR.

    If `effector_coordinator` is provided, delegates to it (preflight,
    pre-warm, retry, self-diagnose). Otherwise falls back to direct
    openclaw_client invocation (legacy path for tests / partial setup).
    """

    def handler(plan) -> Dict[str, Any]:
        tool_name = plan.action_params.get("tool_name")
        tool_args = plan.action_params.get("tool_args", {})

        if not tool_name:
            return {"success": False, "error": "No tool_name in action_params"}

        # Preferred: coordinator
        if effector_coordinator is not None:
            from agent_core.effector.coordinator import EffectorTask
            task = EffectorTask(
                tool_name=tool_name,
                tool_args=tool_args,
                plan_id=getattr(plan, "plan_id", None),
                goal_id=getattr(plan, "goal_id", None),
                source="planner",
            )
            outcome = effector_coordinator.execute_task(task)
            return {
                "success": outcome.ok,
                "tool_name": tool_name,
                "tool_result": outcome.result.get("result") if outcome.result else None,
                "task_id": outcome.task_id,
                "attempts": len(outcome.attempts),
                "status": outcome.status.value,
                "duration_s": round(outcome.total_duration_s, 2),
            }

        # Legacy path
        if openclaw_client is None:
            return {"success": False, "error": "No OpenClaw client configured"}

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
                    # AnalysisReport has no analysis_text field; the analyzer's text
                    # output lives in raw_response. The old phantom read fell into the
                    # bare except below -> self-analysis Telegram summary was always
                    # silently dropped (audyt 2026-06-13).
                    summary = report.raw_response[:300] if report.raw_response else ""
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


def make_ask_expert_handler(
    llm_router,
    expert_bridge=None,
    bulletin_store=None,
) -> Callable:
    """Create handler for ActionType.ASK_EXPERT.

    When expert_bridge is available: uses audit-aware targeted prompts.
    Otherwise: falls back to generic "explain in 3-5 sentences" prompt.
    """

    def handler(plan) -> Dict[str, Any]:
        topic = plan.action_params.get("topic", "")
        goal_desc = plan.goal_description or ""
        context_prompt = plan.action_params.get("context_prompt", "")

        # Phase 4: ExpertBridge path (audit-aware, targeted prompts)
        if expert_bridge is not None and topic:
            try:
                if context_prompt:
                    resp = expert_bridge.ask_with_context(topic, context_prompt)
                else:
                    resp = expert_bridge.ask_about_topic(topic, goal_desc)

                if not resp.success:
                    # Logical skips (dedup, already covered) are not failures
                    skip_reasons = {
                        "expert_material_already_exists",
                        "topic_well_covered",
                    }
                    is_skip = resp.reason in skip_reasons
                    return {
                        "success": is_skip,
                        "skipped": is_skip,
                        "error": resp.reason if not is_skip else None,
                        "reason": resp.reason,
                        "topic": topic,
                        "gap_action": resp.gap_action,
                    }

                # Save to input/ as learning material
                saved = False
                try:
                    save_expert_response(
                        topic, resp.context_prompt, resp.response,
                    )
                    saved = True
                except Exception:
                    pass

                # Phase 5: resolve bulletin NEED_MATERIAL entries
                if bulletin_store is not None and saved:
                    _resolve_bulletin_need(bulletin_store, topic)

                return {
                    "success": True,
                    "topic": topic,
                    "response": resp.response[:500],
                    "response_length": len(resp.response),
                    "context_prompt": resp.context_prompt[:200],
                    "gap_action": resp.gap_action,
                    "reason": resp.reason,
                    "duration_ms": resp.duration_ms,
                    "saved_to_input": saved,
                    "audit_info": resp.metadata,
                }
            except Exception as e:
                logger.debug(f"[ASK_EXPERT] ExpertBridge error: {e}")
                # Fall through to legacy path

        # Legacy path: generic prompt via ask_encyclopedia
        if llm_router is None or not hasattr(llm_router, 'ask_encyclopedia'):
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


def _resolve_bulletin_need(bulletin_store, topic: str) -> None:
    """Mark NEED_MATERIAL bulletin entries as resolved after expert response."""
    try:
        from agent_core.bulletin.bulletin_model import EntryType, EntryStatus
        entries = bulletin_store.find_open(
            topic=topic, entry_type=EntryType.NEED_MATERIAL,
        )
        for entry in entries:
            bulletin_store.update_status(
                entry.entry_id, EntryStatus.RESOLVED,
            )
    except Exception as e:
        logger.debug(f"[ASK_EXPERT] Bulletin update failed: {e}")


def _normalize_file_id(value) -> str:
    """Return canonical file_id string.

    Accepts the dict shape produced by the conductor (knowledge-index
    record with 'id'/'file' keys) or a bare string. Raises ValueError
    on unknown shape so the handler can return a meaningful error.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("id", "file"):
            v = value.get(key)
            if isinstance(v, str) and v:
                return v
        raise ValueError(
            f"file_id dict missing 'id' and 'file' string keys: {value!r}"
        )
    raise ValueError(
        f"file_id has unsupported type {type(value).__name__}: {value!r}"
    )


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

    def handler(plan) -> Dict[str, Any]:
        if cross_validator is None:
            return {"success": False, "error": "No CrossValidator configured"}

        file_id = plan.action_params.get("file_id", "")
        try:
            file_id = _normalize_file_id(file_id)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

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


def make_critique_handler(
    critic_agent,
    telegram_notifier=None,
) -> Callable:
    """Create handler for ActionType.CRITIQUE (Faza G)."""

    def handler(plan) -> Dict[str, Any]:
        if critic_agent is None:
            return {"success": False, "error": "No critic_agent configured"}

        try:
            trigger = plan.action_params.get("trigger", "planner")
            report = critic_agent.run_critique(trigger=trigger)

            if report.error:
                return {
                    "success": False,
                    "error": report.error,
                    "report_id": report.report_id,
                }

            # Telegram: notify only CRITICAL findings
            notifier = _resolve_notifier(telegram_notifier)
            if notifier and report.findings:
                try:
                    critical = [
                        f for f in report.findings
                        if f.severity == "critical"
                    ]
                    if critical and hasattr(notifier, "notify_critique"):
                        notifier.notify_critique(
                            [f.to_dict() for f in critical]
                        )
                except Exception:
                    pass

            return {
                "success": True,
                "report_id": report.report_id,
                "findings": len(report.findings),
                "findings_total": report.findings_total,
                "goals_created": report.goals_created,
                "duration_ms": report.duration_ms,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return handler


def make_noop_handler() -> Callable:
    """Create handler for ActionType.NOOP."""

    def handler(plan) -> Dict[str, Any]:
        return {"success": True, "action": "noop"}

    return handler


from agent_core.routing.handlers.memory import match_memory
from agent_core.routing.handlers.self_model import match_self_model
from agent_core.routing.handlers.time import match_time
from agent_core.routing.handlers.weather import match_weather
