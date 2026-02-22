"""Query and teaching REPL commands: /ask, /teach."""

from agent_core.registry import MariaModule, CommandInfo
from maria_core.utils.conversation_logger import log_message


class QueryModule(MariaModule):
    """Direct queries to Maria and API teaching bridge."""

    name = "query"
    description = "Ask questions and teach Maria via API"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/ask", self._cmd_ask,
                "  /ask PYTANIE           - zapytaj Marie o to, co wie\n"
                "  /ask Co to jest LLM?   - przyklad",
                "[QUERY] QUERY MODE",
            ),
            CommandInfo(
                "/teach", self._cmd_teach,
                "  /teach                 - uruchom lokalny API server (Ty odpowiadasz, Maria zapisuje)",
                "[TEACH] API BRIDGE",
            ),
        ]

    def _cmd_ask(self, args):
        """Zapytaj Marie (szybki tryb, bez REPL-a)."""
        if not self.ctx.brain:
            print("[System] [ERROR] Maria's brain not initialized")
            return

        question = " ".join(args) if args else ""
        if not question:
            print("[System] Brak pytania. Uzyj: /ask Co to jest LLM?")
            return

        try:
            log_message("user", f"/ask {question}")
            prompt = f"Na podstawie tego co wiesz, odpowiedz na pytanie: {question}"
            answer = self.ctx.brain.think(prompt, temperature=0.2)
            print(f"\nMaria: {answer}\n")
            log_message("maria", f"[Answer] {answer}")
        except Exception as e:
            print(f"[Query] [ERROR] Error: {e}")

    def _cmd_teach(self, args):
        """Uruchom API Bridge (TY nauczasz Marie)."""
        try:
            from maria_api_bridge import MariaAPIBridge, SimpleAPIServer

            print("[API Bridge] [TEACH] Starting API Server (Ty bedziesz nauczac Marie)")
            print("[API Bridge] Running on http://localhost:8000")

            server = SimpleAPIServer(port=8000)
            server.run()
        except ImportError:
            print("[System] [ERROR] maria_api_bridge.py not found")
        except Exception as e:
            print(f"[API Bridge] [ERROR] Error: {e}")
