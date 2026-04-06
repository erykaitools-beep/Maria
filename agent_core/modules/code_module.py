"""
CodeModule - REPL interface for Code Agent.

Commands:
    /code <task>           - Start a coding task
    /code status           - Show active session
    /code approve [id]     - Approve pending checkpoint
    /code reject [id]      - Reject pending checkpoint
    /code cancel [id]      - Cancel active session
    /code history [N]      - Show recent sessions
"""

import logging
from typing import List

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class CodeModule(MariaModule):
    """REPL interface for autonomous coding."""

    name = "code"
    description = "Code Agent - autonomous coding"

    def init(self, ctx) -> bool:
        self._ctx = ctx
        self._agent = getattr(ctx, "code_agent", None)
        return self._agent is not None

    def get_commands(self) -> List[CommandInfo]:
        return [
            CommandInfo(
                "/code", self._handle,
                "  /code <task>           - zlec zadanie kodowania\n"
                "  /code status           - aktywna sesja\n"
                "  /code approve [id]     - zatwierdz checkpoint\n"
                "  /code reject [id]      - odrzuc checkpoint\n"
                "  /code cancel [id]      - anuluj sesje\n"
                "  /code history [N]      - historia sesji",
                "[CODE] AUTONOMOUS CODING",
            ),
        ]

    def _handle(self, args: List[str]) -> None:
        if not self._agent:
            print("[Code] Code Agent niedostepny")
            return

        if not args:
            self._show_status()
            return

        cmd = args[0].lower()

        if cmd == "status":
            self._show_status()
        elif cmd == "approve":
            self._approve(args[1] if len(args) > 1 else None)
        elif cmd == "reject":
            self._reject(args[1] if len(args) > 1 else None)
        elif cmd == "cancel":
            self._cancel(args[1] if len(args) > 1 else None)
        elif cmd == "history":
            limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
            self._show_history(limit)
        else:
            # Everything else is a task description
            task = " ".join(args)
            self._start_task(task)

    def _start_task(self, task: str) -> None:
        """Start a new coding task."""
        active = self._agent.get_active()
        if active:
            print(f"[Code] Aktywna sesja: {active.session_id} ({active.status.value})")
            print("[Code] Uzyj /code cancel aby anulowac")
            return

        print(f"[Code] Rozpoczynam: {task}")
        session = self._agent.start(task)
        print(f"[Code] Sesja: {session.session_id}")
        print(f"[Code] Status: {session.status.value}")
        if session.files_planned:
            print(f"[Code] Zaplanowane pliki: {len(session.files_planned)}")
            for f in session.files_planned:
                print(f"  - {f.path} ({f.purpose})")

    def _show_status(self) -> None:
        """Show active session status."""
        active = self._agent.get_active()
        if not active:
            print("[Code] Brak aktywnej sesji kodowania")
            return
        print(active.describe())

    def _approve(self, session_id_prefix: str = None) -> None:
        """Approve pending checkpoint."""
        active = self._agent.get_active()
        if not active:
            print("[Code] Brak sesji czekajacych na zatwierdzenie")
            return
        sid = session_id_prefix or active.session_id
        if self._agent.approve_checkpoint(sid):
            print(f"[Code] Zatwierdzono checkpoint dla {active.session_id}")
            # Resume pipeline
            self._agent.resume(active.session_id)
            # Show updated status
            updated = self._agent.get_session(active.session_id)
            if updated:
                print(f"[Code] Nowy status: {updated.status.value}")
        else:
            print("[Code] Nie ma czekajacego checkpointu")

    def _reject(self, session_id_prefix: str = None) -> None:
        """Reject pending checkpoint."""
        active = self._agent.get_active()
        if not active:
            print("[Code] Brak sesji czekajacych na zatwierdzenie")
            return
        sid = session_id_prefix or active.session_id
        if self._agent.reject_checkpoint(sid):
            print(f"[Code] Odrzucono - sesja anulowana")
        else:
            print("[Code] Nie ma czekajacego checkpointu")

    def _cancel(self, session_id_prefix: str = None) -> None:
        """Cancel active session."""
        active = self._agent.get_active()
        if not active:
            print("[Code] Brak aktywnej sesji")
            return
        sid = session_id_prefix or active.session_id
        if self._agent.cancel(sid):
            print(f"[Code] Sesja {active.session_id} anulowana")
        else:
            print("[Code] Nie mozna anulowac")

    def _show_history(self, limit: int = 5) -> None:
        """Show recent sessions."""
        sessions = self._agent.list_sessions(limit)
        if not sessions:
            print("[Code] Brak sesji w historii")
            return
        for s in sessions:
            status = s.status.value
            files = len(s.files_written)
            calls = s.total_llm_calls
            print(f"  {s.session_id}  {status:<20} {files} plikow  {calls} LLM calls  {s.task_description[:40]}")

    def cleanup(self) -> None:
        pass
