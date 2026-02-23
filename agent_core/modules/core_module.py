"""Core REPL commands: /status, /episodes, /nodes, /save, /load, /start, /stop, /reload."""

import json
import threading
import time
import importlib

from agent_core.registry import MariaModule, CommandInfo
from maria_core.utils.conversation_logger import log_message


class CoreModule(MariaModule):
    """Basic REPL commands: status, graph operations, agent control."""

    name = "core"
    description = "Basic REPL commands (status, graph, agent control)"

    def __init__(self):
        self._agent_running = False
        self._agent_should_stop = False
        self._agent_thread = None

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/status", self._cmd_status,
                "  /status      - co robi Maria (reasoning + statystyki)",
                "[INFO] PODSTAWOWE",
            ),
            CommandInfo(
                "/episodes", self._cmd_episodes,
                "  /episodes    - ostatnie epizody pracy",
                "[INFO] PODSTAWOWE",
            ),
            CommandInfo(
                "/nodes", self._cmd_nodes,
                "  /nodes       - przykladowe wezly z grafu",
                "[INFO] PODSTAWOWE",
            ),
            CommandInfo(
                "/save", self._cmd_save,
                "  /save        - zapisz graf do pliku semantic_graph.json",
                "[INFO] PODSTAWOWE",
            ),
            CommandInfo(
                "/load", self._cmd_load,
                "  /load        - wczytaj graf z pliku semantic_graph.json",
                "[INFO] PODSTAWOWE",
            ),
            CommandInfo(
                "/start", self._cmd_start,
                "  /start       - uruchom agenta w tle",
                "[AGENT] AGENT CONTROL",
            ),
            CommandInfo(
                "/stop", self._cmd_stop,
                "  /stop        - zatrzymaj agenta w tle",
                "[AGENT] AGENT CONTROL",
            ),
            CommandInfo(
                "/reload", self._cmd_reload,
                "  /reload      - przeladuj kod mozgu i petli (ollama_brain, brain_memory_integration)",
                "[AGENT] AGENT CONTROL",
            ),
        ]

    # -- Command handlers --

    def _cmd_status(self, args):
        last_result = self.ctx.last_result
        if not last_result:
            print("[Status] Brak danych - jeszcze nic nie przetworzylismy.\n")
            return

        try:
            stats = {
                "nodes": len(self.ctx.semantic_memory.nodes),
                "edges": len(self.ctx.semantic_memory.edges),
                "episodes": len(self.ctx.episodic_memory),
                "learning_goals": len(last_result.get("learning_goals", [])),
                "unknown_terms": len(last_result.get("unknown_terms", [])),
            }

            prompt = (
                "Opisz w 3-4 zdaniach co aktualnie robisz, "
                "jak wyglada Twoj proces (percepcja->analiza->pamiec), "
                "i co planujesz dalej.\n\n"
                f"Stats: {json.dumps(stats, ensure_ascii=False)}"
            )

            text = self.ctx.brain.think(prompt, temperature=0.2)
            print("\n[Status]")
            print(text)
            print()
            log_message("maria", f"[Status] {text}")
        except Exception as e:
            print(f"[Status] [ERROR] Error: {e}")

    def _cmd_episodes(self, args):
        if not self.ctx.episodic_memory:
            print("[Episodes] Brak epizodow.\n")
        else:
            print("\n[Episodes] Ostatnie epizody:")
            for ep in self.ctx.episodic_memory[-5:]:
                print(f"- {ep.get('timestamp', '?')} | success={ep.get('success')}")
            print()

    def _cmd_nodes(self, args):
        if not self.ctx.semantic_memory.nodes:
            print("[Graph] Brak wezlow.\n")
        else:
            print("\n[Graph] Przykladowe wezly:")
            for i, (nid, node) in enumerate(self.ctx.semantic_memory.nodes.items()):
                if i >= 10:
                    break
                print(f"- {nid}: {node['label']} (type={node['type']})")
            print()

    def _cmd_save(self, args):
        try:
            self.ctx.semantic_memory.save_to_json("semantic_graph.json")
            print("[Graph] [OK] Zapisano do semantic_graph.json\n")
        except Exception as e:
            print(f"[Graph] [ERROR] Error: {e}\n")

    def _cmd_load(self, args):
        try:
            self.ctx.semantic_memory.load_from_json("semantic_graph.json")
            print("[Graph] [OK] Wczytano z semantic_graph.json\n")
        except Exception as e:
            print(f"[Graph] [ERROR] Error: {e}\n")

    def _cmd_start(self, args):
        if self._agent_running:
            print("[System] Agent juz pracuje.\n")
            return

        self._agent_thread = threading.Thread(
            target=self._agent_worker,
            daemon=True,
        )
        self._agent_thread.start()
        print("[System] [OK] Agent uruchomiony w tle.\n")

    def _cmd_stop(self, args):
        if not self._agent_running:
            print("[System] Agent juz zatrzymany.\n")
            return

        self._agent_should_stop = True
        print("[System] Zatrzymuje agenta...\n")

    def _cmd_reload(self, args):
        if self._agent_running:
            print("[System] Najpierw zatrzymaj agenta komenda /stop.\n")
            return

        try:
            from models import ollama_brain
            from maria_core.memory_engine import brain_memory_integration

            importlib.reload(ollama_brain)
            importlib.reload(brain_memory_integration)

            brain = ollama_brain.OllamaBrain(
                model=self.ctx.brain_model,
                verify_model=True,
            )

            # Try to wrap with LLM Router (same as init_brain)
            from main import _create_router
            router = _create_router(brain)
            active_brain = router if router else brain

            self.ctx.brain = active_brain
            self.ctx.brain_loop = brain_memory_integration.BrainMemoryLoop(
                semantic_memory=self.ctx.semantic_memory,
                episodic_memory=self.ctx.episodic_memory,
                maria_brain=active_brain,
            )
            print("[System] [OK] Przeladowano kod mozgu i petli.\n")
        except Exception as e:
            print(f"[System] [ERROR] Error: {e}\n")

    # -- Agent background worker --

    def _agent_worker(self):
        """Worker agenta w tle - rotuje zadania serwisowe."""
        self._agent_running = True
        self._agent_should_stop = False

        tasks = [
            "Analizuj strukture grafu i szukaj luk w wiedzy",
            "Wygeneruj nowe pytania objasniajace dla operatora",
            "Porownaj ostatnie epizody - co sie poprawilo?",
            "Zaplanuj dalsza strategie nauki",
            "Szukaj wzorow w powiazaniach miedzy pojeciami",
        ]

        task_idx = 0
        print("[Agent] [START] Start pracy w tle...")

        while not self._agent_should_stop:
            try:
                task = tasks[task_idx % len(tasks)]
                self.ctx.brain_loop.process_perception(task)
                task_idx += 1
                time.sleep(10)
            except Exception as e:
                print(f"[Agent] [WARN] Error: {e}")

        self._agent_running = False
        print("[Agent] [STOP] Praca zatrzymana.")

    def cleanup(self):
        if self._agent_running:
            self._agent_should_stop = True
