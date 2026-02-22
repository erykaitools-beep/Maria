"""Knowledge management REPL commands: /export-learned, /report."""

import json
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo
from maria_core.utils.conversation_logger import log_message


class KnowledgeModule(MariaModule):
    """Knowledge export and reporting."""

    name = "knowledge"
    description = "Export concepts and generate learning reports"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/export-learned", self._cmd_export_learned,
                "  /export-learned        - exportuj wyuczone pojecia do maria_learned_concepts.json",
                "[KNOWLEDGE] KNOWLEDGE MANAGEMENT",
            ),
            CommandInfo(
                "/report", self._cmd_report,
                "  /report                - generuj raport o stanie nauki (maria_report.json)",
                "[KNOWLEDGE] KNOWLEDGE MANAGEMENT",
            ),
        ]

    def _cmd_export_learned(self, args):
        """Exportuj pojecia wyuczone przez rozne tryby learningu."""
        try:
            learned_concepts = {}

            for node_id, node_data in self.ctx.semantic_memory.nodes.items():
                source = node_data.get("source", "unknown")
                if source not in ["self_learning", "perplexity", "ollama_web", "api"]:
                    continue

                attrs = node_data.get("attributes", {}) or {}
                label = node_data.get("label", node_id)
                definition = attrs.get("definition", node_data.get("definition", ""))

                learned_concepts[label] = {
                    "definition": definition,
                    "source": source,
                    "confidence": node_data.get("confidence", 0.0),
                    "learned_at": attrs.get("learned_at", ""),
                }

            export_data = {
                "timestamp": datetime.now().isoformat(),
                "total_learned": len(learned_concepts),
                "nodes": len(self.ctx.semantic_memory.nodes),
                "edges": len(self.ctx.semantic_memory.edges),
                "concepts": learned_concepts,
            }

            with open("maria_learned_concepts.json", "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            print(f"[Export] [OK] Exported {len(learned_concepts)} concepts to maria_learned_concepts.json")
        except Exception as e:
            print(f"[Export] [ERROR] Error: {e}")

    def _cmd_report(self, args):
        """Pokaz i zapisz pelny raport z nauki."""
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
            success_rate = f"{stats['successful_episodes']}/{stats['episodes']}" if stats['episodes'] > 0 else "0/0"
            print(f"Success Rate: {success_rate}")
            print("=" * 70)
            print(report)
            print("=" * 70 + "\n")

            with open("maria_report.json", "w", encoding="utf-8") as f:
                json.dump(
                    {"stats": stats, "report": report},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            print("[Report] [OK] Saved to maria_report.json")
            log_message("maria", f"[Report] {report}")

        except Exception as e:
            print(f"[Report] [ERROR] Error: {e}")
