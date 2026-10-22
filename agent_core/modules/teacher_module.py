"""Teacher REPL commands: /teacher, /teacher status, /teacher plan, /teacher history."""

import logging
import os
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Optional

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _make_local_examiner_fn(
    model: str,
    *,
    role: str,
    num_predict: int,
    scheduler=None,
    used_cell: Optional[dict] = None,
):
    """Examiner-side LLM (question AUTHOR or GRADER): local model, never NIM.

    Authoring and grading are both EXAMINER work -- neither may run on the
    student model, or the exam self-grades and the independence guarantee
    breaks. ``model`` is therefore always a DIFFERENT model than the student
    (qwen3 on the live box), hard-wired by the caller.

    History: 2026-06-06 moved the examiner to NIM-first (dracarys, off-CPU)
    to cure chronic local timeout storms. The 2026-07-28 forced swap to
    nemotron recalibrated the whole exam without a code change: same prompts,
    but questions 2.5x longer and an academically strict rubric -- fail rate
    16% -> 45-58% with the SAME student (matrix 2026-08-09: nemotron-authored
    questions graded by qwen3 pass 95%; graded by nemotron fail 64%). With
    NIM credits expiring 2026-08-18 anyway, the examiner is now pinned local
    (decision 2026-08-10). The old timeout storms are held off by what landed
    since June: EXAM_MAX_QUESTIONS 12->6, capped exam context, and the heavy
    mutex below. 56 fully-local-examiner exams completed fine in production.

    ``used_cell``: optional one-slot dict; on every call the closure records
    the backend that actually produced the output ("local:<model>" or
    "local:suppressed") under ``used_cell["backend"]`` for exam provenance.
    Returns a ``callable(prompt) -> str`` matching the call_ollama API.
    """
    from maria_core.learning.llm_utils import call_ollama

    def _run(prompt: str):
        from agent_core.llm.local_compute import get_local_compute_coordinator
        if not get_local_compute_coordinator().local_fallback_allowed():
            if used_cell is not None:
                used_cell["backend"] = "local:suppressed"
            logger.warning("[EXAM] Local %s suppressed by thermal cooling", role)
            return None
        # The examiner is a heavy model (qwen3) on the CPU -- serialize it on
        # the scheduler mutex so it never overlaps the student answer or K12.
        if used_cell is not None:
            used_cell["backend"] = f"local:{model}"
        guard = (scheduler.heavy_lease(f"exam_{role}_local")
                 if scheduler is not None else nullcontext())
        with guard:
            return call_ollama(prompt, model=model,
                               num_predict=num_predict, num_ctx=8192)

    return _run


def _make_exam_author_fn(examiner_model: str, scheduler=None, used_cell=None):
    """Exam-question AUTHOR: local examiner model (see _make_local_examiner_fn).

    num_predict=4096: a 6-question rubric with expected answers is the longest
    JSON in the exam; 2048 truncated mid-JSON (2026-05-25 BUG C).
    """
    return _make_local_examiner_fn(
        examiner_model, role="author", num_predict=4096,
        scheduler=scheduler, used_cell=used_cell,
    )


def _make_exam_grader_fn(examiner_model: str, scheduler=None, used_cell=None):
    """Exam GRADER: local examiner model (see _make_local_examiner_fn).

    num_predict=2048 is enough: qwen3 is not a reasoning model and graded a
    full rubric fine at 2048 (the old 6144 cap existed only for nemotron's
    thinking trace). Grading a 6-question rubric measured ~400s on the
    contended CPU (2026-06-05) -- the heavy mutex plus the 12->6 question cap
    keep that bounded; see _make_local_examiner_fn for the full history.
    """
    return _make_local_examiner_fn(
        examiner_model, role="grader", num_predict=2048,
        scheduler=scheduler, used_cell=used_cell,
    )


class TeacherModule(MariaModule):
    """Autonomous teacher agent - decides what to learn, test, and review."""

    name = "teacher"
    description = "Autonomous learning agent with decision engine"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        self._agent = None
        self._session_thread = None
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/teacher", self._cmd_teacher,
                "  /teacher [N]           - uruchom sesje nauki (domyslnie 5 iteracji)\n"
                "  /teacher status        - status agenta (budzet NIM, iteracje)\n"
                "  /teacher plan          - podglad nastepnego kroku\n"
                "  /teacher history [N]   - historia planow (domyslnie 10)",
                "[TEACHER] AGENT NAUCZYCIEL",
            ),
        ]

    # ── Lazy init ────────────────────────────────────

    def _get_agent(self):
        """Lazy init TeacherAgent with router + analyzer."""
        if self._agent is not None:
            return self._agent

        router = self._get_router()
        if router is None:
            print("[Teacher] Brak routera LLM (ctx.brain)")
            return None

        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        from agent_core.teacher.teacher_agent import TeacherAgent

        analyzer = KnowledgeAnalyzer()
        agent = TeacherAgent(router=router, knowledge_analyzer=analyzer)

        # Wire up learning functions
        agent.set_learn_fn(self._learn_chunk_wrapped)
        agent.set_exam_fn(self._run_exam_wrapped)
        # Learning milestone -> proactive ping ("Maria mowi gdy zda egzamin").
        agent.set_milestone_fn(self._on_learning_milestone)

        self._agent = agent
        return agent

    def _on_learning_milestone(self, file_id: str, score) -> None:
        """Forward a passed-exam milestone to the proactive scheduler.

        Late-bound lookup of ctx.proactive_scheduler: the teacher agent is
        lazy-inited on the first learning session, by which point homeostasis
        has wired proactive -- but resolving it at call time keeps this robust
        to init ordering and to proactive being absent in REPL-only contexts.
        """
        sched = getattr(self.ctx, "proactive_scheduler", None)
        if sched is not None and hasattr(sched, "note_learning_milestone"):
            sched.note_learning_milestone(file_id, score)
        self._maybe_seed_learning_note(file_id, score)

    def _maybe_seed_learning_note(self, file_id: str, score) -> None:
        """Etap 2 (RED zone, flag-gated OFF): on a passed exam, seed a goal whose
        success_criterion is that a short self-authored "I learned X" note exists
        in the sandbox -- giving the autonomous FS_WRITE hand a real, recurring
        REASON to act (the gap: nothing else creates file_exists goals on its
        own).

        DOUBLE-GATED so it is inert + litter-free by default:
          - LEARNING_NOTES_ENABLED must be on (the behaviour itself), AND
          - the planner's FS_WRITE loop must be armed -- else the goal could
            never be fulfilled and would sit ACTIVE forever (goal litter).
        Deduped per file; the write stays jailed (<=1 KiB, sandbox, sanitized).
        """
        if not _env_flag("LEARNING_NOTES_ENABLED"):
            return
        planner = getattr(self.ctx, "planner_core", None)
        store = getattr(self.ctx, "goal_store", None)
        if planner is None or store is None:
            return
        # Only create a write-goal the hand can actually fulfil (no litter).
        if not getattr(planner, "_fs_write_enabled", False):
            return
        try:
            import time
            import uuid
            from pathlib import Path
            from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
            from agent_core.hands.sandbox_writer import default_sandbox_root

            # Dedup: at most one open note-goal per learned file.
            for g in store.get_active():
                meta = getattr(g, "metadata", None) or {}
                if meta.get("learning_note_file") == file_id:
                    return

            root = getattr(planner, "_fs_sandbox_root", None)
            if not root:
                try:
                    from maria_core.sys.config import BASE_DIR
                    root = default_sandbox_root(BASE_DIR)
                except Exception:
                    root = default_sandbox_root(".")

            topic = (
                Path(str(file_id)).stem.replace("_", " ").replace("-", " ").strip()
                or str(file_id)
            )
            # Filename uses ONLY safe chars (alnum + "_" + ".txt") + a uuid, so it
            # is a fixed point of sandbox_write's _sanitize_filename. If we derived
            # it from file_id, special chars (e.g. "report(final).txt" -> "__")
            # would be collapsed by the sanitizer at write time -> the written
            # path would diverge from the criterion path -> the goal could never
            # close (goal litter). The topic stays readable in the note CONTENT.
            fname = f"maria_note_{int(time.time())}_{uuid.uuid4().hex[:6]}.txt"
            try:
                s = float(score)
                pct = round(s * 100) if s <= 1.0 else round(s)
            except (TypeError, ValueError):
                pct = None
            score_line = f"Egzamin zdany: {pct}%\n" if pct else ""
            content = f"Nauczylam sie: {topic}\n{score_line}(autonomiczna notatka Marii)\n"
            target = str(Path(root) / fname)

            goal = create_goal(
                goal_type=GoalType.USER,
                description=f"Zapisz notatke z nauki: {topic}",
                priority=0.7,
                status=GoalStatus.ACTIVE,
                created_by="maria",
                success_criteria=[{"type": "file_exists", "path": target}],
                metadata={
                    "learning_note_file": file_id,
                    "fs_write_content": content,
                    "b2_learning_note": True,
                },
            )
            store.create(goal)
            store.save()
            logger.info("[Etap2] seeded learning-note goal %s -> %s", goal.id, fname)
        except Exception as e:
            logger.debug(f"learning-note seed failed: {e}")

    def _get_router(self):
        """Get LLMRouter from ctx.brain."""
        brain = self.ctx.brain
        if brain is None:
            return None
        if hasattr(brain, "_ask_once"):
            return brain
        return None

    # ── Wrappers for learning_agent / exam_agent ─────

    def _learn_chunk_wrapped(self, file_id: str, use_simple: bool = False):
        """Wrap learn_next_chunk to work with TeacherAgent."""
        try:
            from maria_core.learning.learning_agent import learn_next_chunk
            from maria_core.perception.perception import scan_input_directory
            from maria_core.sys.config import INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY

            # Index new files from input/ before learning
            # (unindexed files are invisible to learn_next_chunk)
            scan_input_directory(INPUT_DIR, KNOWLEDGE_INDEX)

            router = self._get_router()
            llm_fn = None
            if router and hasattr(router, "_ask_once"):
                # BUG C fix (audit 2026-05-25): learn output is a structured
                # JSON with summary + key-points + chunks, often 3-4K tokens.
                # Default 2048 truncated mid-JSON and triggered fallback loops.
                llm_fn = lambda prompt: router._ask_once(
                    prompt, temperature=0.3, force_json=True, max_tokens=4096,
                )

            result = learn_next_chunk(
                base_dir=INPUT_DIR,
                index_path=KNOWLEDGE_INDEX,
                memory_path=LONGTERM_MEMORY,
                llm_fn=llm_fn,
                target_file_id=file_id if file_id else None,
                # This parameter used to be accepted here and dropped: the
                # teacher's retry_hard_topic request never reached the prompt
                # selector, so a "explain it more simply" strategy ran the
                # normal prompt -- on a different file, since hard_topic was
                # not selectable either.
                use_simple=True if use_simple else None,
            )
            # LearnResult is truthy only when a chunk was really learned. The
            # skip flag has to travel with it: an idle tick reported as a plain
            # failure would feed the self-repair failure-storm detector, which
            # counts `success is False and not skipped`.
            return {
                "success": bool(result),
                "skipped": getattr(result, "skipped", False),
                "reason": getattr(result, "reason", ""),
                # The file actually processed, which is not always the one asked
                # for. Mirrors the exam path's LABEL FIX (2026-08-12).
                "file_id": getattr(result, "file_id", "") or file_id,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_exam_wrapped(self, file_id: str, use_heldout: bool = False):
        """Wrap run_exam_if_ready to work with TeacherAgent.

        ``use_heldout`` is an EXPLICIT opt-in from the caller (the EXAM handler
        passes it only for plans whose action_params carry grader='heldout' --
        i.e. B4 drills on heldout-mode goals). It is deliberately NOT read from
        the HELDOUT_GRADER_ENABLED env flag anymore: the global read flipped
        grading for EVERY exam once bank rows existed for a file, which would
        have routed live Kronika reviews through the uncalibrated mechanical
        grader and demoted verified files latest-wins (red-team 2026-07-11,
        CRITICAL #2). The env flag now arms ONLY the planner's B4 emission.

        Thermal start-gate (2026-08-10): during active cooling no exam stage
        starts at all -- ``{"skipped": True}`` tells _exec_review to defer
        WITHOUT counting a pipeline failure or parking the file in cooldown.
        The regular pipeline also runs STAGED (stage_path): one heavy
        generation per session, state persisted between sessions, because
        three back-to-back generations overheat past the 80C latch and used
        to discard the whole exam mid-flight (3/3 on 2026-08-10).
        """
        try:
            from agent_core.llm.local_compute import get_local_compute_coordinator
            if not get_local_compute_coordinator().local_fallback_allowed():
                logger.info(
                    "[EXAM] Thermal cooling active; deferring exam stage for %s",
                    file_id,
                )
                return {"success": False, "skipped": True,
                        "reason": "thermal_deferred", "file_id": file_id}

            from maria_core.learning.exam_agent import run_exam_if_ready
            from maria_core.sys.config import (
                KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS, EXAM_STAGE_FILE,
            )

            from maria_core.learning.llm_utils import call_ollama
            from maria_core.sys.config import (
                OLLAMA_MODEL, EXAM_ANSWER_TIMEOUT_SEC, EXAM_ANSWER_HTTP_TIMEOUT_SEC,
            )
            from agent_core.llm.execution_budget import call_with_timeout

            # KEYSTONE (2026-05-30): split the formerly self-graded exam into a
            # local STUDENT and an INDEPENDENT EXAMINER (a DIFFERENT model). The
            # student is Maria's deployed model (OLLAMA_MODEL, llama3.1); the
            # examiner authors the questions+rubric AND grades, while the student
            # answers blind (answer_exam never shows the expected answers). So the
            # score measures real capability instead of the model agreeing with
            # its own expected answers.
            #
            # EXAMINER LOCAL AGAIN (2026-08-10): author + grader are pinned to
            # the local qwen3 examiner (see _make_local_examiner_fn for the
            # NIM era and why it ended: nemotron recalibrated the whole exam
            # without a code change, and NIM credits die 2026-08-18).
            #
            # num_predict/num_ctx raised (2026-05-25 BUG C): the exam calls over
            # ~12 questions overflow the 2048 default and truncate mid-JSON, which
            # looped the pipeline forever.
            student_model = OLLAMA_MODEL
            examiner_model = "qwen3:8b" if student_model != "qwen3:8b" else "llama3.1:8b"
            # Both exam paths answer CONCISE (held-out always did; the regular
            # path switched 2026-06-06 -- see _execute_exam), so a short
            # fact/number reply fits well under 2048 tokens.
            student_num_predict = 2048
            # All three exam steps (author, answer, grade) now run on the local
            # CPU, serialized on the heavy mutex -- an exam is minutes, not
            # seconds, and that is accepted (2026-08-10). Per-call bounds keep
            # any single step from hanging the pipeline: prompt-eval is ~17
            # tok/s, so an answer over a capped ~2k-token context runs ~207s.
            # call_ollama gets EXAM_ANSWER_HTTP_TIMEOUT (290s) so a legal answer
            # passes in ONE try (not retry -> 841s zombie), and
            # call_with_timeout(EXAM_ANSWER_TIMEOUT_SEC=300) is the hard upper
            # bound: a wedged llama fails on one deadline -> answer_exam pads
            # empties (score 0) -> a clean, bounded fail instead of a hang.
            # Reach the heavy-mutex scheduler via the router so the (heavy, local)
            # student answer and the qwen3 examiner fallback serialize on the same
            # lock as ask_as_role/K12 instead of bypassing it -- the connect that
            # cures the exam-answer || planner contention storm. Defensive: any gap
            # in wiring -> None -> heavy_lease() degrades to a no-op (today's path).
            _exam_scheduler = None
            try:
                _exam_router = self._get_router()
                if _exam_router is not None and hasattr(_exam_router, "get_model_scheduler"):
                    _exam_scheduler = _exam_router.get_model_scheduler()
            except Exception:
                _exam_scheduler = None

            _student_call = lambda prompt: call_ollama(
                prompt, model=student_model,
                num_predict=student_num_predict, num_ctx=8192,
                timeout=EXAM_ANSWER_HTTP_TIMEOUT_SEC)

            def llm_fn(prompt):
                # Hold the heavy mutex for the student answer's full duration so
                # it never overlaps a heavy local on the CPU. No-op until the flag.
                guard = (_exam_scheduler.heavy_lease("exam_answer")
                         if _exam_scheduler is not None else nullcontext())
                with guard:
                    return call_with_timeout(
                        lambda: _student_call(prompt),
                        timeout_sec=EXAM_ANSWER_TIMEOUT_SEC, label="exam_answer")
            # One-slot cells: each closure records the backend that ACTUALLY ran
            # ("local:<model>" / "local:suppressed"); run_exam_if_ready copies
            # them into the exam record AFTER grading. Separate cells so an
            # author outcome can never masquerade as the grader in provenance.
            author_cell = {"backend": None}
            grader_cell = {"backend": None}
            grader_llm_fn = _make_exam_grader_fn(
                examiner_model, scheduler=_exam_scheduler, used_cell=grader_cell)
            generator_llm_fn = _make_exam_author_fn(
                examiner_model, scheduler=_exam_scheduler, used_cell=author_cell)
            grader_meta = {
                # Independence = the examiner is never the STUDENT (different
                # weights; qwen3 is also a genuinely different family than the
                # llama3.1 student).
                "independent": examiner_model != student_model,
                "grader": f"local|{examiner_model}",
                "student": student_model,
                "grader_cell": grader_cell,
                "author_cell": author_cell,
            }

            # Context policy (C5, 2026-07-12): held-out exams answer OPEN-BOOK
            # in production (semantic_memory=None) -- the independence of Option
            # C comes from the frozen answer key + mechanical grading, not from
            # recall-from-retrieval. Closed-book stays a drill mode (the offline
            # rebaseline/subscore scripts pass semantic_memory themselves);
            # summaries are indexed only at boot, so a fresh pantry file would
            # retrieve NOTHING and fail blind. Regular exams never read
            # semantic memory (the kwarg is consumed only by the held-out
            # branch), but keep the old wiring for them unchanged.
            if use_heldout:
                sem_mem = None
            else:
                _ctx = getattr(self, "ctx", None)
                sem_mem = (
                    getattr(_ctx, "semantic_search", None)
                    or getattr(_ctx, "semantic_memory", None)
                )
            result = run_exam_if_ready(
                index_path=KNOWLEDGE_INDEX,
                memory_path=LONGTERM_MEMORY,
                exam_path=EXAM_RESULTS,
                llm_fn=llm_fn,
                target_file_id=file_id,
                grader_llm_fn=grader_llm_fn,
                generator_llm_fn=generator_llm_fn,
                grader_meta=grader_meta,
                use_heldout=use_heldout,
                semantic_memory=sem_mem,
                stage_path=EXAM_STAGE_FILE,
            )
            out = {
                "success": result["executed"],
                "passed": result["passed"],
                "score": result["score"],
                "file_id": result["file_id"],
                "heldout_fallback": result.get("heldout_fallback", False),
            }
            if result.get("staged"):
                # Non-final stage ran and persisted: session did real work,
                # but no exam completed yet.
                out["success"] = True
                out["staged"] = result["staged"]
            return out
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Command handler ──────────────────────────────

    def _cmd_teacher(self, args):
        """Main /teacher command with subcommands."""
        if not args:
            return self._run_session(5)

        sub = args[0].lower()
        if sub == "status":
            return self._show_status()
        elif sub == "plan":
            return self._show_plan()
        elif sub == "history":
            limit = 10
            if len(args) > 1:
                try:
                    limit = int(args[1])
                except ValueError:
                    pass
            return self._show_history(limit)
        else:
            try:
                iterations = int(sub)
                return self._run_session(max(1, iterations))
            except ValueError:
                print(f"[Teacher] Nieznana komenda: {sub}")
                print("  /teacher [N] | status | plan | history")

    # ── Session ──────────────────────────────────────

    def _run_session(self, iterations: int):
        """Run teacher session with progress output."""
        agent = self._get_agent()
        if agent is None:
            return

        print(f"\n[Teacher] Sesja nauki: {iterations} iteracji")
        print("-" * 50)

        def on_step(iteration, strategy_type, result):
            status_mark = "[OK]" if result.get("success") else "[!!]"
            file_id = result.get("file_id", "?")
            extra = ""
            if result.get("score") is not None:
                extra = f" ({result['score']:.0%})"
            print(f"  {status_mark} Iter {iteration}: {strategy_type} -> {file_id}{extra}")

        status = agent.run_session(
            max_iterations=iterations,
            callback=on_step,
        )

        stats = status["stats"]
        print("-" * 50)
        print(f"  Strategie:  {stats['strategies_executed']}")
        print(f"  Chunki:     {stats['chunks_learned']}")
        print(f"  Egzaminy:   {stats['exams_run']} (zdane: {stats['exams_passed']})")
        print(f"  NIM plany:  {stats['nim_planning_calls']}/{agent._max_nim_planning}")
        if stats["errors"] > 0:
            print(f"  Bledy:      {stats['errors']}")
        print()

    # ── Status ───────────────────────────────────────

    def _show_status(self):
        """Show teacher agent status."""
        agent = self._get_agent()
        if agent is None:
            return

        status = agent.get_status()
        stats = status["stats"]

        print("\n[Teacher] Status agenta")
        print("-" * 40)
        print(f"  Aktywny:     {'TAK' if status['running'] else 'NIE'}")
        print(f"  Iteracja:    {status['iteration']}")
        print(f"  NIM plany:   {status['nim_planning_used']}/{status['nim_planning_limit']}")
        print(f"  Chunki:      {stats['chunks_learned']}")
        print(f"  Egzaminy:    {stats['exams_run']} (zdane: {stats['exams_passed']})")
        print(f"  Bledy:       {stats['errors']}")

        # Knowledge summary
        snapshot = agent.analyzer.get_knowledge_snapshot()
        by_status = snapshot["files_by_status"]
        print(f"\n  Pliki:")
        print(f"    Ukonczone:  {len(by_status.get('completed', []))}")
        print(f"    W nauce:    {len(by_status.get('learning', []))}")
        print(f"    Nowe:       {len(by_status.get('new', []))}")
        print(f"    Trudne:     {len(by_status.get('hard_topic', []))}")
        print(f"    Sr. wynik:  {snapshot['average_exam_score']:.0%}")
        print()

    # ── Plan ─────────────────────────────────────────

    def _show_plan(self):
        """Show what teacher would do next."""
        agent = self._get_agent()
        if agent is None:
            return

        preview = agent.get_next_plan_preview()
        if preview is None:
            print("\n[Teacher] Brak pracy - wszystko ukonczone lub brak plikow")
            return

        print("\n[Teacher] Nastepny krok")
        print("-" * 40)

        type_names = {
            "learn_new": "Nauka nowego",
            "review": "Powtorka/Egzamin",
            "deepen": "Poglebienie",
            "fill_gap": "Wypelnienie luki",
        }
        print(f"  Strategia: {type_names.get(preview['strategy_type'], preview['strategy_type'])}")
        print(f"  Plik:      {preview['target_file_id']}")
        if preview.get("params"):
            reason = preview["params"].get("reason", "")
            if reason:
                print(f"  Powod:     {reason}")
        print()

    # ── History ──────────────────────────────────────

    def _show_history(self, limit: int = 10):
        """Show recent teaching plans."""
        agent = self._get_agent()
        if agent is None:
            return

        history = agent.get_history(limit=limit)
        if not history:
            print("\n[Teacher] Brak historii planow")
            return

        from datetime import datetime

        print(f"\n[Teacher] Ostatnie {len(history)} planow")
        print("-" * 60)

        for entry in history:
            ts = entry.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
            strategy = entry.get("strategy", {})
            result = entry.get("result", {})
            s_type = strategy.get("strategy_type", "?")
            file_id = strategy.get("target_file_id", "?")
            success = result.get("success", False)
            mark = "[OK]" if success else "[!!]"

            extra = ""
            if result.get("score") is not None:
                extra = f" {result['score']:.0%}"

            print(f"  {dt} {mark} {s_type:12s} {file_id}{extra}")

        print()
