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


def _make_nim_first_examiner_fn(
    fallback_model: str,
    *,
    role: str,
    temperature: float,
    max_tokens: int,
    nim_timeout: int,
    fallback_num_predict: int,
    scheduler=None,
    used_cell: Optional[dict] = None,
):
    """Examiner-side LLM (question AUTHOR or GRADER): NIM first, honest local fallback.

    Authoring and grading are both EXAMINER work -- neither may run on the
    student model, or the exam self-grades and the independence guarantee breaks.
    Both are also heavy generations that chronically timed out on the contended
    local CPU (incident 2026-06-04 author: 20/20 failed; 2026-06-05 grade: the
    regular exam's answer+grade overran OLLAMA_TIMEOUT x retries -> 841s storms).
    Running them on NIM (nemotron, off-CPU) with ``force_json`` removes them from
    the CPU path entirely, leaving only the student's answer local.

    On ANY NIM failure (timeout, empty content, exception) it falls back to the
    local ``fallback_model`` (e.g. qwen3 -- a DIFFERENT family than the student),
    NEVER the student, so the run stays honestly independent whichever model ran.
    This explicit fallback is the fix for the old hidden self-grade: a naive NIM
    grader timed out and the ROUTER silently fell back to the student; here the
    fallback is hard-wired to ``fallback_model``, never the student.

    Params differ between author (creative temp, 120s ok) and grader
    (deterministic temp, needs ~240s for a full 6-question rubric: NIM measured
    ~85s/3q). Returns a ``callable(prompt) -> str`` matching the call_ollama API.

    ``used_cell``: optional one-slot dict; on every call the closure records the
    backend that actually produced the output ("nim:<model>" / "local:<model>")
    under ``used_cell["backend"]``. Before this, exam records carried a constant
    planned label ("nim-first|qwen3:8b"), so the NIM-vs-fallback split -- and
    thus the real grader lineage -- was invisible in the trust data.
    """
    from maria_core.learning.llm_utils import call_ollama

    nim = None
    try:
        from maria_core.sys.config import (
            NVIDIA_NIM_API_KEY, NVIDIA_NIM_MODEL, NVIDIA_NIM_BASE_URL,
        )
        if NVIDIA_NIM_API_KEY:
            from agent_core.llm.nim_client import NIMClient
            nim = NIMClient(
                api_key=NVIDIA_NIM_API_KEY,
                model=NVIDIA_NIM_MODEL,
                base_url=NVIDIA_NIM_BASE_URL or None,
                # Generous timeout: the old 45s default cut NIM off mid-call.
                # Author (force_json, no reasoning preamble) lands in ~30s; the
                # grader needs more (~170s for a 6-question rubric) -> 240s.
                timeout=nim_timeout,
                system_prompt=(
                    "Jestes precyzyjnym egzaminatorem. "
                    "Zwracasz WYLACZNIE poprawny JSON, bez komentarzy."
                ),
            )
    except Exception as exc:  # pragma: no cover - construction guard
        logger.warning("[EXAM] NIM %s unavailable (%s); using local %s",
                        role, exc, fallback_model)
        nim = None

    def _run(prompt: str):
        if nim is not None:
            try:
                resp = nim._ask_once(
                    prompt, temperature=temperature,
                    max_tokens=max_tokens, force_json=True,
                )
                if resp and resp.strip():
                    if used_cell is not None:
                        used_cell["backend"] = f"nim:{nim.model}"
                    return resp
                logger.warning("[EXAM] NIM %s returned empty; "
                               "falling back to local %s", role, fallback_model)
            except Exception as exc:
                logger.warning("[EXAM] NIM %s failed (%s); "
                               "falling back to local %s", role, exc, fallback_model)
        # Local examiner fallback is a heavy model (qwen3) on the CPU -- serialize
        # it on the scheduler mutex so it never overlaps the student answer or K12.
        if used_cell is not None:
            used_cell["backend"] = f"local:{fallback_model}"
        guard = (scheduler.heavy_lease(f"exam_{role}_local")
                 if scheduler is not None else nullcontext())
        with guard:
            return call_ollama(prompt, model=fallback_model,
                               num_predict=fallback_num_predict, num_ctx=8192)

    return _run


def _make_exam_author_fn(fallback_model: str, scheduler=None, used_cell=None):
    """Exam-question AUTHOR: NIM first (fast, off-CPU), honest local fallback.

    Authoring a multi-question rubric is a heavy generation that chronically
    timed out on the contended local CPU (incident 2026-06-04: 20/20 exams
    failed). See ``_make_nim_first_examiner_fn`` for the shared contract. Author
    uses a creative temperature and the 120s NIM timeout (authoring lands ~30s).
    """
    return _make_nim_first_examiner_fn(
        fallback_model, role="author", temperature=0.3,
        max_tokens=4096, nim_timeout=120, fallback_num_predict=4096,
        scheduler=scheduler, used_cell=used_cell,
    )


def _make_exam_grader_fn(fallback_model: str, scheduler=None, used_cell=None):
    """Exam GRADER: NIM first (off-CPU), local independent fallback.

    Grading was the last heavy CPU step in the regular exam: qwen3 graded a
    6-question rubric in ~400s on CPU and overran OLLAMA_TIMEOUT on retry -> the
    chronic 841s timeout storm (root-caused 2026-06-05; the EXAM_MAX_QUESTIONS
    12->6 patch halved it but did not remove it). Moving grade to NIM takes it
    off the contended CPU, leaving only the student's answer local.

    Differs from the author: low temperature for consistent scoring, and a 240s
    NIM timeout because a full 6-question rubric measured ~85s/3q (~170s/6q) --
    the author's 120s would cut it off mid-grade (the exact pitfall that kept
    grading local until now). On any NIM failure -> qwen3 local (independent:
    != student), so independence holds and we never self-grade.

    max_tokens=6144 (NOT 2048): nemotron is a REASONING model that emits a long
    thinking trace before the JSON, so a 2048 cap truncated mid-grade
    (finish_reason=length, verify 2026-06-06) and silently dropped every grade to
    the qwen3 fallback -- defeating the off-CPU cure. 6144 clears the trace + a
    6-question grade JSON with margin. The qwen3 FALLBACK stays at 2048 (qwen3 is
    not a reasoning model -- it graded a 4-question rubric fine at 2048).
    """
    return _make_nim_first_examiner_fn(
        fallback_model, role="grader", temperature=0.1,
        max_tokens=6144, nim_timeout=240, fallback_num_predict=2048,
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

            success = learn_next_chunk(
                base_dir=INPUT_DIR,
                index_path=KNOWLEDGE_INDEX,
                memory_path=LONGTERM_MEMORY,
                llm_fn=llm_fn,
                target_file_id=file_id if file_id else None,
            )
            return {"success": success}
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
        """
        try:
            from maria_core.learning.exam_agent import run_exam_if_ready
            from maria_core.sys.config import KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS

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
            # GRADER ON NIM (2026-06-06): the examiner (author + grader) now runs
            # NIM-first off-CPU with an honest qwen3-local fallback (see
            # _make_exam_grader_fn). This is the long-planned upgrade over the
            # local-only qwen3 grader, which stayed local only because a NAIVE NIM
            # grader timed out at 45s and the ROUTER silently fell back to the
            # student = hidden self-grade. The fix: a 240s NIM timeout (clears the
            # ~170s 6-question rubric) + an EXPLICIT fallback wired to qwen3, never
            # the student -- so independence holds whichever model graded, and the
            # heavy grade leaves the contended CPU (the 841s-storm cure).
            #
            # num_predict/num_ctx raised (2026-05-25 BUG C): the exam calls over
            # ~12 questions overflow the 2048 default and truncate mid-JSON, which
            # looped the pipeline forever.
            student_model = OLLAMA_MODEL
            examiner_model = "qwen3:8b" if student_model != "qwen3:8b" else "llama3.1:8b"
            # Both exam paths now answer CONCISE (held-out always did; the regular
            # path switched 2026-06-06 -- see _execute_exam), so a short fact/number
            # reply fits well under 2048 tokens. 4096 is no longer needed: generate
            # and grade moved off-CPU to NIM, leaving the student answer as the only
            # local call, and a concise answer never approaches 2048.
            student_num_predict = 2048
            # The student's answer is the ONLY exam step still on the local CPU
            # (generate + grade run off-CPU on NIM, 2026-06-06). On this GPU-less
            # CPU prompt-eval is ~17 tok/s, so even a concise answer over a capped
            # ~2k-token context runs ~207s. call_ollama gets EXAM_ANSWER_HTTP_TIMEOUT
            # (290s) so a legal answer passes in ONE try (not retry -> 841s zombie),
            # and call_with_timeout(EXAM_ANSWER_TIMEOUT_SEC=300) is the hard upper
            # bound: a wedged llama fails on one deadline -> answer_exam pads empties
            # (score 0) -> a clean, bounded fail instead of an open-ended hang.
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
                # Student answer is the ONLY heavy step still local (author + grade
                # run off-CPU on NIM). Hold the heavy mutex for its full duration so
                # it never overlaps a heavy local on the CPU. No-op until the flag.
                guard = (_exam_scheduler.heavy_lease("exam_answer")
                         if _exam_scheduler is not None else nullcontext())
                with guard:
                    return call_with_timeout(
                        lambda: _student_call(prompt),
                        timeout_sec=EXAM_ANSWER_TIMEOUT_SEC, label="exam_answer")
            # GRADE now runs on NIM (off-CPU) -- the last heavy step taken off the
            # contended CPU, and the actual cure for the chronic 841s storm (the
            # EXAM_MAX_QUESTIONS 12->6 patch only halved it). On any NIM failure it
            # falls back to qwen3 local (independent, NEVER the student), so the
            # score stays honestly independent whichever model graded. (The old
            # local-only grader stayed because a NAIVE NIM grader timed out at 45s
            # and the ROUTER silently fell back to the student = hidden self-grade;
            # _make_exam_grader_fn fixes both: 240s timeout + explicit qwen3 fallback.)
            # One-slot cells: each closure records the backend that ACTUALLY ran
            # ("nim:<model>" / "local:<model>"); run_exam_if_ready copies them into
            # the exam record AFTER grading. Separate cells so an author fallback
            # can never masquerade as the grader in the provenance data.
            author_cell = {"backend": None}
            grader_cell = {"backend": None}
            grader_llm_fn = _make_exam_grader_fn(
                examiner_model, scheduler=_exam_scheduler, used_cell=grader_cell)
            # Author the questions on NIM too (off-CPU, fast); same honest fallback.
            generator_llm_fn = _make_exam_author_fn(
                examiner_model, scheduler=_exam_scheduler, used_cell=author_cell)
            grader_meta = {
                # Independence = the examiner is never the STUDENT (different
                # weights), for EITHER backend. Nuance recorded honestly via the
                # cells: the live NIM (dracarys) is a Llama-3.1 finetune -- same
                # LINEAGE as the student, different weights/scale -- while the
                # qwen3 fallback is a genuinely different family.
                "independent": examiner_model != student_model,
                "grader": f"nim-first|{examiner_model}",
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
            )
            return {
                "success": result["executed"],
                "passed": result["passed"],
                "score": result["score"],
                "file_id": result["file_id"],
                "heldout_fallback": result.get("heldout_fallback", False),
            }
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
