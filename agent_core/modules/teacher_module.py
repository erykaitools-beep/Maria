"""Teacher REPL commands: /teacher, /teacher status, /teacher plan, /teacher history."""

import threading
from pathlib import Path
from typing import Optional

from agent_core.registry import MariaModule, CommandInfo


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

        self._agent = agent
        return agent

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
            from maria_core.sys.config import INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY

            router = self._get_router()
            llm_fn = None
            if router and hasattr(router, "_ask_once"):
                llm_fn = lambda prompt: router._ask_once(prompt, temperature=0.3)

            success = learn_next_chunk(
                base_dir=INPUT_DIR,
                index_path=KNOWLEDGE_INDEX,
                memory_path=LONGTERM_MEMORY,
            )
            return {"success": success}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_exam_wrapped(self, file_id: str):
        """Wrap run_exam_if_ready to work with TeacherAgent."""
        try:
            from maria_core.learning.exam_agent import run_exam_if_ready
            from maria_core.sys.config import KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS

            success = run_exam_if_ready(
                index_path=KNOWLEDGE_INDEX,
                memory_path=LONGTERM_MEMORY,
                exam_path=EXAM_RESULTS,
            )
            return {"success": success, "passed": success}
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
