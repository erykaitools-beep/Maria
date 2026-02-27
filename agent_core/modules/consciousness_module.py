"""REPL commands for Maria's consciousness: /identity, /feel, /personality, /memory."""

from agent_core.registry import MariaModule, CommandInfo


class ConsciousnessModule(MariaModule):
    """Consciousness REPL commands: identity and feelings."""

    name = "consciousness"
    description = "Consciousness commands (identity, feelings, memory)"

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
            CommandInfo(
                "/personality", self._cmd_personality,
                "  /personality - moja osobowosc (cechy, ich ewolucja)",
                "[CONSCIOUSNESS] SWIADOMOSC",
            ),
            CommandInfo(
                "/memory", self._cmd_memory,
                "  /memory      - pamiec rozmow (podsumowania sesji, fakty)",
                "[CONSCIOUSNESS] SWIADOMOSC",
            ),
            CommandInfo(
                "/dreams", self._cmd_dreams,
                "  /dreams      - moje sny (co mi sie snilo)",
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
        age = d.get("age_string", "")
        if age:
            print(f"  Wiek: {age}")
        print(f"  Sesji lacznie: {d.get('session_count', 0)}")
        print(f"  Restartow: {d.get('restart_count', 0)}")
        print(f"  Calkowity uptime: {d.get('total_uptime_hours', 0):.1f}h")

        uptime_h = d.get("total_uptime_hours", 0)
        session_count = d.get("session_count", 1)
        avg_h = uptime_h / max(session_count, 1)
        print(f"  Srednia sesja: {avg_h:.1f}h")

        longest_h = d.get("longest_session_seconds", 0) / 3600
        if longest_h > 0:
            print(f"  Najdluzsza sesja: {longest_h:.1f}h")

        total_conv = d.get("total_conversations", 0)
        if total_conv > 0:
            print(f"  Rozmow lacznie: {total_conv}")

        offline = d.get("offline_string", "")
        if offline:
            print(f"  Ostatni sen: {offline}")

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

    def _cmd_personality(self, args):
        """Show Maria's evolving personality."""
        consciousness = self.ctx.consciousness
        if not consciousness:
            print("[Personality] Consciousness not available.\n")
            return

        summary = consciousness.get_personality_summary()
        print(f"\n{summary}")

        # Show session experience stats
        if consciousness.experience_tracker:
            counts = consciousness.experience_tracker.get_experience_counts()
            total = consciousness.experience_tracker.get_total_count()
            if counts:
                print(f"\n[Doswiadczenia tej sesji: {total}]")
                for event, count in sorted(counts.items()):
                    print(f"  {event}: {count}")
        print()

    def _cmd_memory(self, args):
        """Show conversation memory - session summaries and user facts."""
        conv_mem = self.ctx.conversation_memory
        if not conv_mem:
            print("[Memory] Conversation memory not available.\n")
            return

        # Current session info
        turn_count = conv_mem.get_session_turn_count()
        print(f"\n[Pamiec rozmow]")
        print(f"  Biezaca sesja: {turn_count} wiadomosci")

        # Recent session summaries
        summaries = conv_mem.get_recent_summaries(limit=5)
        if summaries:
            print(f"\n[Podsumowania ostatnich sesji: {len(summaries)}]")
            for s in summaries:
                session = s.get("session", "?")
                date = s.get("date", "?")
                summary = s.get("summary", "")
                turns = s.get("turn_count", "?")
                sentiment = s.get("sentiment", "?")
                condensed_by = s.get("condensed_by", "?")
                print(f"  Sesja {session} ({date}): {summary}")
                print(f"    [{turns} wiad. | nastroj: {sentiment} | kondensacja: {condensed_by}]")
        else:
            print("\n  Brak zapisanych podsumowah sesji")

        # User facts (never forgotten)
        user_facts = conv_mem.get_all_user_facts()
        if user_facts:
            print(f"\n[Fakty o uzytkowniku: {len(user_facts)}]")
            for fact in user_facts:
                print(f"  - {fact}")

        print()

    def _cmd_dreams(self, args):
        """Show Maria's recent dreams."""
        limit = 5
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                pass

        try:
            from agent_core.consciousness.dream_generator import DreamGenerator
            dreams = DreamGenerator.load_recent_dreams(limit=limit)
        except ImportError:
            print("[Dreams] Dream module not available.\n")
            return

        if not dreams:
            print("\n[Sny] Jeszcze nie snilam - nie bylo fazy SLEEP.\n")
            return

        print(f"\n[Sny: {len(dreams)}]")
        for dream in dreams:
            ts = dream.get("timestamp", "?")
            session = dream.get("session", "?")
            content = dream.get("content", "?")
            dtype = dream.get("type", "?")
            labels = dream.get("labels", [])
            confidence = dream.get("confidence", 0)

            print(f"\n  [{ts}] (sesja {session})")
            print(f"    {content}")
            print(f"    Typ: {dtype} | Koncepty: {', '.join(labels)} | Pewnosc: {confidence:.1f}")

        # Show sleep report if available
        if self.ctx.homeostasis_core:
            report = self.ctx.homeostasis_core.get_last_sleep_report()
            if report:
                phases = report.get("phases_completed", 0)
                nrem3 = report.get("nrem3", {})
                nodes_cleaned = nrem3.get("nodes_marked_outdated", 0)
                print(f"\n  [Ostatni cykl snu: {phases} fazy, wyczyszczono {nodes_cleaned} nodow]")

        print()

    def cleanup(self):
        pass
