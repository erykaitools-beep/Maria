"""NIM API REPL commands: /nim [status|budget|stats]."""

from agent_core.registry import MariaModule, CommandInfo


class NIMModule(MariaModule):
    """NVIDIA NIM API status and budget monitoring."""

    name = "nim"
    description = "NIM API status, token budget, routing stats"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/nim", self._cmd_nim,
                "  /nim             - status routera LLM (backend, model, budzet)\n"
                "  /nim budget      - szczegolowy raport budzetu tokenow\n"
                "  /nim stats       - statystyki routingu (NIM vs Ollama)",
                "[NIM] NVIDIA NIM API",
            ),
        ]

    def _cmd_nim(self, args):
        """Handle /nim commands."""
        subcmd = args[0].lower() if args else "status"

        if subcmd == "status":
            self._show_status()
        elif subcmd == "budget":
            self._show_budget()
        elif subcmd == "stats":
            self._show_stats()
        else:
            print(f"[NIM] Nieznana podkomenda: {subcmd}")
            print("  Uzyj: /nim [status|budget|stats]")

    def _get_router(self):
        """Get LLMRouter from ctx.brain if available."""
        brain = self.ctx.brain
        if brain is None:
            return None
        # Check if brain is actually a router (has get_stats method)
        if hasattr(brain, "get_stats") and hasattr(brain, "get_active_backend"):
            return brain
        return None

    def _show_status(self):
        """Show NIM router status."""
        router = self._get_router()

        print("\n[NIM] Status routera LLM")
        print("-" * 40)

        if router is None:
            print("  Backend: Ollama only (router nieaktywny)")
            print("  NIM API: nie skonfigurowany")
            if self.ctx.brain:
                model = getattr(self.ctx.brain, "model", "?")
                print(f"  Model Ollama: {model}")
            print()
            return

        stats = router.get_stats()
        backend = stats["active_backend"]

        if backend == "hybrid":
            print("  Backend: HYBRID (NIM + Ollama)")
        else:
            print(f"  Backend: {backend.upper()}")

        # NIM info
        if stats.get("nim_available"):
            print(f"  Model NIM: {stats.get('nim_model', '?')}")
        else:
            print("  Model NIM: niedostepny")

        # Ollama info
        ollama_model = getattr(router.ollama, "model", "?")
        print(f"  Model Ollama: {ollama_model}")

        # Budget summary
        budget_info = stats.get("budget", {})
        status_val = budget_info.get("status", "?")
        if status_val == "OK":
            print(f"  Budzet: OK")
        elif status_val == "LOW":
            print(f"  Budzet: NISKI (oszczedzaj!)")
        elif status_val == "DEPLETED":
            print(f"  Budzet: WYCZERPANY (tylko Ollama)")
        else:
            print(f"  Budzet: {status_val}")

        # Routing info
        print(f"\n  Routing:")
        print(f"    think()        -> Ollama (chat)")
        print(f"    analyze_task() -> {'NIM' if backend == 'hybrid' else 'Ollama'} (nauka)")
        print()

    def _show_budget(self):
        """Show detailed token budget."""
        router = self._get_router()

        print("\n[NIM] Budzet tokenow")
        print("-" * 40)

        if router is None:
            print("  Router nieaktywny - brak budzetu do wyswietlenia.")
            print()
            return

        # Use get_budget_status for human-readable text
        budget_text = router.get_budget_status()
        print(f"\n{budget_text}")

        # Show raw numbers
        stats = router.get_stats()
        budget_info = stats.get("budget", {})
        if budget_info:
            daily = budget_info.get("daily", {})
            monthly = budget_info.get("monthly", {})

            if daily:
                used = daily.get("used", 0)
                limit = daily.get("limit", 0)
                pct = (used / limit * 100) if limit > 0 else 0
                print(f"\n  Dzienne: {used:,} / {limit:,} ({pct:.1f}%)")

            if monthly:
                used = monthly.get("used", 0)
                limit = monthly.get("limit", 0)
                pct = (used / limit * 100) if limit > 0 else 0
                print(f"  Miesieczne: {used:,} / {limit:,} ({pct:.1f}%)")

        print()

    def _show_stats(self):
        """Show routing statistics."""
        router = self._get_router()

        print("\n[NIM] Statystyki routingu")
        print("-" * 40)

        if router is None:
            print("  Router nieaktywny.")
            print()
            return

        stats = router.get_stats()

        total = stats.get("total_calls", 0)
        nim_calls = stats.get("nim_calls", 0)
        ollama_calls = stats.get("ollama_calls", 0)
        fallbacks = stats.get("nim_fallbacks", 0)

        print(f"  Lacznie wywolan: {total}")
        print(f"  NIM:    {nim_calls}")
        print(f"  Ollama: {ollama_calls}")
        print(f"  Fallback (NIM -> Ollama): {fallbacks}")

        if total > 0:
            nim_pct = nim_calls / total * 100
            print(f"\n  NIM ratio: {nim_pct:.1f}%")
            if fallbacks > 0 and nim_calls > 0:
                fail_pct = fallbacks / (nim_calls + fallbacks) * 100
                print(f"  NIM failure rate: {fail_pct:.1f}%")

        print()

    def cleanup(self):
        pass
