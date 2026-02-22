"""Learning REPL commands: /learn, /learn-web, /hybrid."""

import json
import time
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo
from maria_core.utils.conversation_logger import log_message
from maria_core.sys.orchestrator import maria_learning_cycle
from maria_core.perception.perception import scan_input_directory
from maria_core.sys.config import INPUT_DIR, KNOWLEDGE_INDEX


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
                "  /learn 0               - ucz sie az skoncza sie pliki",
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
