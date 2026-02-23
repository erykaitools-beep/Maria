"""REPL commands for Maria's consciousness: /identity, /feel."""

from agent_core.registry import MariaModule, CommandInfo


class ConsciousnessModule(MariaModule):
    """Consciousness REPL commands: identity and feelings."""

    name = "consciousness"
    description = "Consciousness commands (identity, feelings)"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        # Check if consciousness is available
        if ctx.consciousness is None and ctx.identity_store is None:
            print("[Consciousness] [WARN] No consciousness or identity_store in context")
            return False
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/identity", self._cmd_identity,
                "  /identity    - kim jestem (torzsamosc, urodziny, sesja)",
                "[CONSCIOUSNESS] SWIADOMOSC",
            ),
            CommandInfo(
                "/feel", self._cmd_feel,
                "  /feel        - jak sie czuje (ludzki jezyk + dane lab)",
                "[CONSCIOUSNESS] SWIADOMOSC",
            ),
        ]

    # -- Command handlers --

    def _cmd_identity(self, args):
        """Show Maria's identity information."""
        # Check for subcommand
        if args and args[0].lower() == "history":
            return self._identity_history()

        consciousness = self.ctx.consciousness
        if consciousness:
            # Full identity summary from ConsciousnessCore
            summary = consciousness.get_identity_summary()
            print("\n[Identity]")
            print(summary)
            print()
            return

        # Fallback to identity_store only
        identity_store = self.ctx.identity_store
        if identity_store:
            d = identity_store.get_identity_dict()
            print("\n[Identity]")
            print(f"  Imie: {d.get('name', '?')} ({d.get('full_name', '?')})")
            print(f"  Pelna nazwa: {d.get('full_name_expanded', '?')}")
            print(f"  Urodziny: {d.get('birth_date', '?')}")
            print(f"  Sesja: {d.get('session_count', '?')}")
            print(f"  Calkowity uptime: {d.get('total_uptime_hours', 0):.1f}h")
            print(f"  Restartow: {d.get('restart_count', 0)}")
            print(f"  Operator: {d.get('primary_user', '?')}")
            last = d.get("last_session_summary", "")
            if last:
                print(f"  Ostatnia sesja: {last}")
            print()
        else:
            print("[Identity] Consciousness not available.\n")

    def _identity_history(self):
        """Show session history summary."""
        identity_store = self.ctx.identity_store
        if not identity_store:
            print("[Identity] No identity store available.\n")
            return

        d = identity_store.get_identity_dict()
        print("\n[Identity History]")
        print(f"  Narodziny: {d.get('birth_date', '?')}")
        print(f"  Sesji lacznie: {d.get('session_count', 0)}")
        print(f"  Restartow: {d.get('restart_count', 0)}")
        print(f"  Calkowity uptime: {d.get('total_uptime_hours', 0):.1f}h")

        uptime_h = d.get("total_uptime_hours", 0)
        session_count = d.get("session_count", 1)
        avg_h = uptime_h / max(session_count, 1)
        print(f"  Srednia sesja: {avg_h:.1f}h")

        last = d.get("last_session_summary", "")
        if last:
            print(f"  Ostatnia sesja: {last}")

        shutdown = d.get("last_shutdown_timestamp", "")
        if shutdown:
            print(f"  Ostatni shutdown: {shutdown}")

        print()

    def _cmd_feel(self, args):
        """Show how Maria feels right now."""
        consciousness = self.ctx.consciousness
        if consciousness:
            # Get mode from homeostasis if available
            mode = None
            if self.ctx.homeostasis_core:
                try:
                    mode = self.ctx.homeostasis_core.state.mode.value.upper()
                except Exception:
                    pass

            feeling = consciousness.get_current_feeling(mode=mode)
            print(f"\n[Feeling]\n{feeling}\n")
            return

        # Fallback - try to create HumanStateMapper directly
        try:
            from agent_core.consciousness.human_state import HumanStateMapper

            mapper = HumanStateMapper()
            feeling = mapper.describe_with_data()
            print(f"\n[Feeling]\n{feeling}\n")
        except ImportError:
            print("[Feeling] Consciousness not available.\n")

    def cleanup(self):
        pass
