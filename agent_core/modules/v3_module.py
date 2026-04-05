"""REPL commands: /v3 - V3 orchestrator interface."""

import logging

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class V3Module(MariaModule):
    """V3 Orchestrator REPL interface."""

    name = "v3"
    description = "V3 Product Shell - task orchestration"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        self._shell = None
        return True

    def _get_shell(self):
        if self._shell is None:
            try:
                from agent_core.orchestrator.product_shell import ProductShell
                self._shell = ProductShell(self.ctx)
            except Exception as e:
                logger.warning(f"V3 ProductShell init failed: {e}")
        return self._shell

    def get_commands(self):
        return [
            CommandInfo(
                "/v3", self._cmd_v3,
                "  /v3                    - status V3 systemu\n"
                "  /v3 do <zadanie>       - zlec zadanie\n"
                "  /v3 approve <task_id>  - zatwierdz zadanie\n"
                "  /v3 cancel <task_id>   - anuluj zadanie\n"
                "  /v3 progress <task_id> - postep zadania\n"
                "  /v3 tasks              - lista zadan\n"
                "  /v3 who                - kim jestem\n"
                "  /v3 what               - co potrafie\n"
                "  /v3 limits             - moje ograniczenia\n"
                "  /v3 tools              - lista narzedzi\n"
                "  /v3 budget             - budzet LLM\n"
                "  /v3 onboarding         - uruchom onboarding",
                "[V3] PRODUCT SHELL",
            ),
        ]

    def _cmd_v3(self, args):
        sub = args[0] if args else ""

        if sub == "do":
            self._do_task(args[1:])
        elif sub == "approve":
            self._approve(args[1:])
        elif sub == "cancel":
            self._cancel(args[1:])
        elif sub == "progress":
            self._progress(args[1:])
        elif sub == "tasks":
            self._list_tasks()
        elif sub == "who":
            self._who()
        elif sub == "what":
            self._what()
        elif sub == "limits":
            self._limits()
        elif sub == "tools":
            self._tools()
        elif sub == "budget":
            self._budget()
        elif sub == "onboarding":
            self._onboarding()
        else:
            self._status()

    # ------------------------------------------------------------------
    # Subcommands
    # ------------------------------------------------------------------

    def _status(self):
        shell = self._get_shell()
        if not shell:
            print("[V3] ProductShell niedostepny")
            return

        status = shell.get_status()
        cap = status["capabilities"]
        budget = status["budget"]
        progress = status["progress"]

        print(f"\n{'=' * 50}")
        print(f"  M.A.R.I.A. V3 Product Shell")
        print(f"{'=' * 50}")
        print(f"  Zdolnosci: {cap['total_capabilities']} "
              f"({cap['free']} free, {cap['guarded']} guarded, {cap['restricted']} restricted)")
        print(f"  Serwisy:   {cap['available_services']}/{cap['external_services']} aktywnych")
        print(f"  NIM:       {budget['nim_remaining_today']} tokenow ({budget['nim_status']})")
        print(f"  Aktywne:   {progress['active_count']} zadan")
        print(f"  Onboarding: {'tak' if status['onboarding_completed'] else 'nie'}")

        lims = status["limitations"]
        if lims["total_limitations"] > 0:
            print(f"  Ograniczenia: {lims['total_limitations']}")
            if lims.get("blocked_count", 0) > 0:
                print(f"  Blokady:  {lims['blocked_count']} akcji")

        print()

    def _do_task(self, args):
        if not args:
            print("[V3] Uzyj: /v3 do <opis zadania>")
            return

        shell = self._get_shell()
        if not shell:
            print("[V3] ProductShell niedostepny")
            return

        description = " ".join(args)
        print(f"[V3] Analizuje: {description}")
        text = shell.do_and_describe(description)
        print(f"\n{text}")

    def _approve(self, args):
        if not args:
            print("[V3] Uzyj: /v3 approve <task_id>")
            return

        shell = self._get_shell()
        if not shell:
            return

        task_id = args[0]
        goal_id = shell.approve(task_id)
        if goal_id:
            print(f"[V3] Zatwierdzono: {task_id} -> goal {goal_id}")
        else:
            print(f"[V3] Nie znaleziono zadania: {task_id}")

    def _cancel(self, args):
        if not args:
            print("[V3] Uzyj: /v3 cancel <task_id>")
            return

        shell = self._get_shell()
        if not shell:
            return

        task_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "user_cancelled"
        if shell.cancel(task_id, reason):
            print(f"[V3] Anulowano: {task_id}")
        else:
            print(f"[V3] Nie znaleziono: {task_id}")

    def _progress(self, args):
        if not args:
            print("[V3] Uzyj: /v3 progress <task_id>")
            return

        shell = self._get_shell()
        if not shell:
            return

        task_id = args[0]
        prog = shell.progress(task_id)
        if not prog:
            print(f"[V3] Nie znaleziono: {task_id}")
            return

        print(f"\n  Task:     {prog['task_id']}")
        print(f"  Opis:     {prog['description']}")
        print(f"  Status:   {prog['status']}")
        print(f"  Postep:   {prog['progress'] * 100:.0f}%")
        print(f"  Goal:     {prog.get('goal_id', '-')}")
        print(f"  Kroki:    {prog.get('plan_steps', '?')}")
        if prog.get("error"):
            print(f"  Blad:     {prog['error']}")
        print()

    def _list_tasks(self):
        shell = self._get_shell()
        if not shell:
            return

        tasks = shell.tasks()
        if not tasks:
            print("[V3] Brak zadan")
            return

        print(f"\n  {'ID':<18} {'Status':<12} {'Kategoria':<14} {'Opis'}")
        print(f"  {'-'*16} {'-'*10} {'-'*12} {'-'*25}")
        for t in tasks:
            tid = t["task_id"][:16]
            print(f"  {tid:<18} {t['status']:<12} {t['category']:<14} {t['description'][:30]}")
        print()

    def _who(self):
        shell = self._get_shell()
        if shell:
            print(f"\n{shell.who_am_i()}\n")

    def _what(self):
        shell = self._get_shell()
        if shell:
            print(f"\n{shell.what_can_i_do()}\n")

    def _limits(self):
        shell = self._get_shell()
        if shell:
            print(f"\n{shell.limitations()}\n")

    def _tools(self):
        shell = self._get_shell()
        if not shell:
            return

        services = shell.tool_registry.list_external_services()
        print(f"\n  Serwisy zewnetrzne:")
        for s in services:
            status = s["status"].upper()
            print(f"    [{status}] {s['name']} ({s['type']})")

        print(f"\n  Zdolnosci wg kategorii:")
        grouped = shell.tool_registry.list_by_category()
        for cat, caps in sorted(grouped.items()):
            names = ", ".join(c["name"] for c in caps)
            print(f"    [{cat}] {names}")
        print()

    def _budget(self):
        shell = self._get_shell()
        if not shell:
            return

        budget = shell.cost_estimator.get_budget_status()
        summary = shell.resource_planner.get_summary()

        print(f"\n  Budzet LLM:")
        print(f"    NIM API:  {budget.nim_remaining_today} tokenow ({budget.nim_status})")
        print(f"    NIM RPM:  {'dostepne' if budget.nim_rpm_available else 'wyczerpane'}")
        print(f"    Claude:   {budget.claude_calls_remaining_hour}/h")
        print(f"    Codex:    {budget.codex_calls_remaining_hour}/h")
        print(f"    Lokalny:  {'dostepny' if budget.local_available else 'niedostepny'}")
        print(f"    Default:  {summary['recommended_default']}")
        print()

    def _onboarding(self):
        shell = self._get_shell()
        if not shell:
            return

        result = shell.onboarding.run()
        print(result["text"])

    def cleanup(self) -> None:
        pass
