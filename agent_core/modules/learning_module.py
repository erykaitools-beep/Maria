"""Learning REPL commands: /learn, /learn-web, /hybrid, /learn history/stats/file."""

import json
import time
from datetime import datetime
from pathlib import Path

from agent_core.registry import MariaModule, CommandInfo
from maria_core.utils.conversation_logger import log_message
from maria_core.perception.perception import scan_input_directory
from maria_core.sys.config import INPUT_DIR, KNOWLEDGE_INDEX, EXAM_RESULTS, LONGTERM_MEMORY


class LearningModule(MariaModule):
    """Automatic and web-based learning from input/ folder."""

    name = "learning"
    description = "Auto-learning from files and web sources"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/learn", self._cmd_learn,
                "  /learn                 - ucz sie z plikow w input/ (5 iteracji)\n"
                "  /learn 10              - 10 iteracji nauki\n"
                "  /learn 0               - ucz sie az skoncza sie pliki\n"
                "  /learn history         - historia nauki (pliki, statusy, wyniki)\n"
                "  /learn stats           - statystyki nauki (sumaryczne)\n"
                "  /learn file NAZWA      - szczegoly o konkretnym pliku",
                "[LEARN] AUTO-LEARNING",
            ),
            CommandInfo(
                "/learn-web", self._cmd_learn_web,
                "  /learn-web             - web learning przez Perplexity\n"
                "  /learn-web ollama      - web learning przez Ollama (bez API key)",
                "[LEARN] AUTO-LEARNING",
            ),
            CommandInfo(
                "/hybrid", self._cmd_hybrid,
                "  /hybrid                - sekwencja: self-learning -> web-learning -> report",
                "[LEARN] AUTO-LEARNING",
            ),
        ]

    def _cmd_learn(self, args):
        """Uruchom automatyczne uczenie sie z plikow w input/."""
        # Route subcommands
        if args:
            sub = args[0].lower()
            if sub == "history":
                return self._show_history()
            elif sub == "stats":
                return self._show_stats()
            elif sub == "file":
                name = args[1] if len(args) > 1 else None
                return self._show_file_details(name)

        max_iterations = 5
        if args:
            try:
                max_iterations = int(args[0])
                if max_iterations < 0:
                    max_iterations = 5
            except (ValueError, IndexError):
                max_iterations = 5

        print(f"[Learn] Scanning input/ folder...")
        try:
            stats = scan_input_directory(INPUT_DIR, KNOWLEDGE_INDEX)
            print(f"[Learn] Found: {stats['new']} new, {stats['changed']} changed, {stats['unchanged']} unchanged")

            if stats['new'] == 0 and stats['changed'] == 0 and stats['unchanged'] == 0:
                print("[Learn] [WARN] No files found in input/ folder!")
                print(f"[Learn] Put .txt files in: {INPUT_DIR}")
                return
        except Exception as e:
            print(f"[Learn] [ERROR] Scan error: {e}")
            return

        if max_iterations == 0:
            print(f"[Learn] [BRAIN] Starting learning (unlimited iterations)...")
            max_iterations = 9999
        else:
            print(f"[Learn] [BRAIN] Starting learning ({max_iterations} iterations)...")

        try:
            maria_learning_cycle(
                max_iterations=max_iterations,
                learn_steps_per_exam=5,
                use_ollama_priority=False,
            )
            print("[Learn] [OK] Learning cycle complete")
        except KeyboardInterrupt:
            print("\n[Learn] [STOP] Stopped by user")
        except Exception as e:
            print(f"[Learn] [ERROR] Error: {e}")

    # ── Learning Observability ──────────────────────────

    def _load_index(self):
        """Load knowledge index records."""
        if not KNOWLEDGE_INDEX.exists():
            return []
        records = []
        with open(KNOWLEDGE_INDEX, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def _load_exams(self):
        """Load exam result records."""
        if not EXAM_RESULTS.exists():
            return []
        records = []
        with open(EXAM_RESULTS, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def _show_history(self):
        """Show learning history - all files with status and scores."""
        records = self._load_index()
        if not records:
            print("\n[Learn] Brak historii nauki - knowledge_index pusty.\n")
            return

        # Status symbols
        status_sym = {
            "completed": "[OK]",
            "learning": "[...]",
            "new": "[NEW]",
            "exam_failed": "[FAIL]",
            "hard_topic": "[HARD]",
            "learned": "[EXAM]",
        }

        print("\n" + "=" * 70)
        print("[LEARN] HISTORIA NAUKI")
        print("=" * 70)

        for rec in records:
            name = rec.get("file", rec.get("id", "?"))
            status = rec.get("status", "?")
            sym = status_sym.get(status, f"[{status}]")
            chunks = rec.get("chunks_learned", 0)
            total = rec.get("total_chunks", 0)
            scores = rec.get("last_scores", [])
            attempts = rec.get("exam_attempts", 0)
            priority = rec.get("priority", 0)

            score_str = ""
            if scores:
                score_str = f" | Score: {scores[-1]:.0%}"
                if len(scores) > 1:
                    score_str += f" (proby: {', '.join(f'{s:.0%}' for s in scores)})"

            chunk_str = f"{chunks}/{total}" if total > 0 else "0/?"

            print(f"  {sym:6s} {name}")
            print(f"         Chunki: {chunk_str} | Egzaminy: {attempts}{score_str} | Priorytet: {priority:.0f}")

        print("=" * 70 + "\n")

    def _show_stats(self):
        """Show aggregate learning statistics."""
        records = self._load_index()
        exams = self._load_exams()

        if not records:
            print("\n[Learn] Brak danych - knowledge_index pusty.\n")
            return

        # Count by status
        status_counts = {}
        total_chunks = 0
        chunks_learned = 0
        for rec in records:
            status = rec.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            total_chunks += rec.get("total_chunks", 0)
            chunks_learned += rec.get("chunks_learned", 0)

        # Exam stats
        all_scores = [e.get("score", 0) for e in exams if "score" in e]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
        pass_count = sum(1 for s in all_scores if s >= 0.6)

        # File size stats
        total_files = len(records)
        input_files = list(INPUT_DIR.glob("*.txt")) if INPUT_DIR.exists() else []

        print("\n" + "=" * 50)
        print("[LEARN] STATYSTYKI NAUKI")
        print("=" * 50)

        print(f"\n  [Pliki]")
        print(f"    W indeksie:    {total_files}")
        print(f"    W input/:      {len(input_files)}")
        for status, count in sorted(status_counts.items()):
            label = {
                "completed": "Ukonczone",
                "learning": "W trakcie",
                "new": "Nowe",
                "exam_failed": "Oblane",
                "hard_topic": "Trudne",
                "learned": "Czeka na egz.",
            }.get(status, status)
            print(f"    {label:14s}  {count}")

        print(f"\n  [Chunki]")
        print(f"    Nauczone:      {chunks_learned}/{total_chunks}")
        if total_chunks > 0:
            print(f"    Postep:        {chunks_learned/total_chunks:.0%}")

        print(f"\n  [Egzaminy]")
        print(f"    Lacznie:       {len(exams)}")
        print(f"    Sredni wynik:  {avg_score:.0%}")
        print(f"    Zdane (>=60%): {pass_count}/{len(all_scores)}")
        if all_scores:
            print(f"    Najlepszy:     {max(all_scores):.0%}")
            print(f"    Najgorszy:     {min(all_scores):.0%}")

        # Date range
        dates = [e.get("timestamp", "") for e in exams if e.get("timestamp")]
        if dates:
            first = dates[0][:10]
            last = dates[-1][:10]
            print(f"\n  [Okres nauki]")
            print(f"    Od: {first}")
            print(f"    Do: {last}")

        print("=" * 50 + "\n")

    def _show_file_details(self, name):
        """Show detailed info about a specific learned file."""
        if not name:
            print("[Learn] Uzycie: /learn file NAZWA")
            print("[Learn] Podaj nazwe pliku (lub fragment).")
            return

        records = self._load_index()
        exams = self._load_exams()

        # Find matching record (partial match)
        match = None
        for rec in records:
            file_name = rec.get("file", rec.get("id", ""))
            if name.lower() in file_name.lower():
                match = rec
                break

        if not match:
            print(f"[Learn] Nie znaleziono pliku pasujacego do: {name}")
            print("[Learn] Dostepne pliki:")
            for rec in records[:10]:
                print(f"  - {rec.get('file', rec.get('id', '?'))}")
            if len(records) > 10:
                print(f"  ... i {len(records) - 10} wiecej")
            return

        file_name = match.get("file", match.get("id", "?"))
        print(f"\n{'=' * 60}")
        print(f"[LEARN] SZCZEGOLY: {file_name}")
        print(f"{'=' * 60}")

        print(f"\n  Status:      {match.get('status', '?')}")
        print(f"  Priorytet:   {match.get('priority', 0):.0f}")
        print(f"  Chunki:      {match.get('chunks_learned', 0)}/{match.get('total_chunks', 0)}")
        print(f"  Egzaminy:    {match.get('exam_attempts', 0)}")
        scores = match.get("last_scores", [])
        if scores:
            print(f"  Wyniki:      {', '.join(f'{s:.0%}' for s in scores)}")
        print(f"  Dodano:      {match.get('created_at', '?')[:19]}")
        print(f"  Aktualizacja: {match.get('updated_at', '?')[:19]}")

        # Find exam results for this file
        file_exams = [e for e in exams if name.lower() in e.get("file", "").lower()]
        if file_exams:
            print(f"\n  [Egzaminy ({len(file_exams)})]")
            for exam in file_exams:
                ts = exam.get("timestamp", "?")[:19]
                score = exam.get("score", 0)
                n_q = exam.get("num_questions", 0)
                attempt = exam.get("attempt", "?")
                print(f"    [{ts}] Proba {attempt}: {score:.0%} ({n_q} pytan)")

                # Show questions and grades
                grading = exam.get("grading", [])
                for g in grading:
                    q = g.get("pytanie", g.get("question", "?"))
                    s = g.get("score", 0)
                    if isinstance(q, int):
                        # Some gradings have question number instead of text
                        questions = exam.get("questions", [])
                        if q - 1 < len(questions):
                            q = questions[q - 1].get("q", f"Pytanie {q}")
                    # Truncate long questions
                    if isinstance(q, str) and len(q) > 60:
                        q = q[:57] + "..."
                    bar = "#" * int(s * 10) + "." * (10 - int(s * 10))
                    print(f"      [{bar}] {s:.0%} {q}")

        # Find longterm memory entries
        if LONGTERM_MEMORY.exists():
            memories = []
            with open(LONGTERM_MEMORY, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            mem = json.loads(line)
                            if name.lower() in mem.get("source_file", "").lower():
                                memories.append(mem)
                        except json.JSONDecodeError:
                            continue

            if memories:
                print(f"\n  [Pamiec ({len(memories)} chunkow)]")
                for mem in memories:
                    chunk_id = mem.get("chunk_index", "?")
                    summary = mem.get("summary", "")
                    tags = mem.get("tags", [])
                    simple = mem.get("learned_simple", False)

                    if len(summary) > 80:
                        summary = summary[:77] + "..."
                    print(f"    Chunk {chunk_id}: {summary}")
                    if tags:
                        print(f"      Tagi: {', '.join(tags[:8])}")
                    if simple:
                        print(f"      [uproszczona nauka]")

        print(f"{'=' * 60}\n")

    def _cmd_learn_web(self, args):
        """Uruchom Web Learning (Perplexity lub Ollama web)."""
        source = "perplexity"
        if args and args[0].lower() == "ollama":
            source = "ollama"

        if source == "perplexity":
            api_key = input("[Web Learning] Enter Perplexity API Key: ").strip()
            log_message("user", "[/learn-web] Entered Perplexity API key (hidden)")
            if not api_key:
                print("[System] No API key provided, aborting web learning.")
                return
        else:
            api_key = None

        print(f"[Web Learning] [WEB] Starting (source={source})")

        try:
            from maria_web_learning import WebLearningMode

            web_mode = WebLearningMode(None, perplexity_key=api_key, source=source)
            web_mode.semantic_memory = self.ctx.semantic_memory
            web_mode.brain = self.ctx.brain
            web_mode.agent = self.ctx.brain_loop
            web_mode.run_cycle_with_web_learning()
            print("[Web Learning] [OK] Cycle complete")
        except Exception as e:
            print(f"[Web Learning] [ERROR] Error: {e}")

    def _cmd_hybrid(self, args):
        """Uruchom sekwencje: self-learning -> web-learning -> report."""
        print("[Hybrid] [START] Starting all learning sources...\n")

        # 1. Self-Learning
        print("[1/3] Self-Learning...")
        self._cmd_learn(["5"])
        time.sleep(2)

        # 2. Web Learning (optional)
        print("\n[2/3] Web Learning...")
        api_key = input("[Web Learning] Perplexity API Key (optional, Enter to skip): ").strip()
        if api_key:
            try:
                from maria_web_learning import WebLearningMode

                web_mode = WebLearningMode(None, perplexity_key=api_key, source="perplexity")
                web_mode.semantic_memory = self.ctx.semantic_memory
                web_mode.brain = self.ctx.brain
                web_mode.agent = self.ctx.brain_loop
                web_mode.run_cycle_with_web_learning()
            except Exception as e:
                print(f"[Web Learning] [ERROR] Error: {e}")
        else:
            print("[Web Learning] Skipped (no API key)")
        time.sleep(2)

        # 3. Report (inline to avoid cross-module dependency)
        print("\n[3/3] Generating report...")
        try:
            stats = {
                "nodes": len(self.ctx.semantic_memory.nodes),
                "edges": len(self.ctx.semantic_memory.edges),
                "episodes": len(self.ctx.episodic_memory),
                "successful_episodes": len([e for e in self.ctx.episodic_memory if e.get("success")]),
                "timestamp": datetime.now().isoformat(),
            }

            prompt = (
                "Napisz krotki raport (3-5 zdan) o postepach w nauce.\n\n"
                f"Statystyki:\n"
                f"- Wezlow w grafie: {stats['nodes']}\n"
                f"- Krawedzi: {stats['edges']}\n"
                f"- Epizodow: {stats['episodes']}\n"
                f"- Pomyslnych: {stats['successful_episodes']}\n\n"
                "Jakie sa glowne obszary nauki? Co nauczylas sie najciekawszego?"
            )

            report = self.ctx.brain.think(prompt, temperature=0.3)

            print("\n" + "=" * 70)
            print("[REPORT] MARIA'S LEARNING REPORT")
            print("=" * 70)
            print(f"Timestamp: {stats['timestamp']}")
            print(f"Nodes: {stats['nodes']} | Edges: {stats['edges']} | Episodes: {stats['episodes']}")
            print("=" * 70)
            print(report)
            print("=" * 70 + "\n")
        except Exception as e:
            print(f"[Report] [ERROR] Error: {e}")

        print("[Hybrid] [OK] All sources processed!")
