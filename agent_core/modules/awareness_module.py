"""REPL commands for Maria's self-awareness: /awareness."""

from agent_core.registry import MariaModule, CommandInfo


class AwarenessModule(MariaModule):
    """Self-awareness REPL commands."""

    name = "awareness"
    description = "Self-awareness: what Maria sees in her context"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/awareness", self._cmd_awareness,
                "  /awareness        - co widze w swoim kontekscie (pliki, wiedza, kod, system)\n"
                "  /awareness files  - szczegolowa lista plikow do nauki\n"
                "  /awareness reload - wymus odswiezenie kontekstu (czysci cache)",
                "[AWARENESS] SWIADOMOSC KONTEKSTU",
            ),
        ]

    def _cmd_awareness(self, args):
        """Handle /awareness [files|reload]."""
        subcmd = args[0].lower() if args else "show"

        if subcmd == "files":
            self._show_files()
        elif subcmd == "reload":
            self._reload_cache()
        else:
            self._show_context()

    def _get_builder(self):
        """Get ContextBuilder instance (from brain or create new)."""
        # Try to get the module-level builder from ollama_brain
        try:
            from models.ollama_brain import _AWARENESS_BUILDER, AWARENESS_AVAILABLE
            if AWARENESS_AVAILABLE and _AWARENESS_BUILDER is not None:
                return _AWARENESS_BUILDER
        except ImportError:
            pass

        # Fallback: create a new one
        try:
            from agent_core.awareness import ContextBuilder
            return ContextBuilder()
        except Exception:
            return None

    def _show_context(self):
        """Show the current awareness context string."""
        builder = self._get_builder()
        if builder is None:
            print("[Awareness] Modul niedostepny.\n")
            return

        context = builder.build()

        print("\n[Awareness] Kontekst ktory widze w swoim promptcie:")
        print("-" * 60)

        if not context:
            print("  (brak danych - wszystkie zrodla niedostepne)")
        else:
            # Pretty print - split by ". " for readability
            content = context.replace("[Swiadomosc: ", "").rstrip(".]")
            parts = content.split(". ")
            for part in parts:
                if part.strip():
                    print(f"  {part.strip()}")

        print()
        print(f"  Cache TTL: {builder.CACHE_TTL}s")
        import time
        if builder._cache_time > 0:
            age = time.time() - builder._cache_time
            print(f"  Wiek cache: {age:.0f}s")
        print()

    def _show_files(self):
        """Show detailed file list with statuses."""
        builder = self._get_builder()
        if builder is None:
            print("[Awareness] Modul niedostepny.\n")
            return

        files = builder.get_detailed_file_list()
        input_files = builder.get_input_files()

        print("\n[Awareness] Pliki do nauki:")
        print("-" * 60)

        if not files:
            print("  Brak plikow w knowledge_index.jsonl")
            if input_files:
                print(f"\n  Folder input/ zawiera {len(input_files)} plikow .txt:")
                for f in input_files:
                    print(f"    - {f}")
            print()
            return

        # Group by status
        STATUS_LABELS = {
            "completed":   "[DONE]   ",
            "learning":    "[TRWA]   ",
            "learned":     "[OK]     ",
            "new":         "[NOWE]   ",
            "hard_topic":  "[TRUDNE] ",
            "exam_failed": "[NIEZDANE]",
            "other":       "[?]      ",
        }

        # Sort: completed first, then learning, then new
        order = ["completed", "learned", "learning", "new", "hard_topic", "exam_failed", "other"]
        files_sorted = sorted(files, key=lambda r: order.index(r.get("status", "other"))
                              if r.get("status", "other") in order else 99)

        for f in files_sorted:
            status = f.get("status", "?")
            label = STATUS_LABELS.get(status, "[?]      ")
            name = f.get("file", "?")
            score = f.get("exam_score")
            chunks = f.get("chunks_learned", 0)
            total = f.get("total_chunks", 0)

            line = f"  {label} {name}"
            if score is not None:
                line += f"  (egzamin: {score*100:.0f}%)"
            if total > 0:
                line += f"  [{chunks}/{total} chunkow]"
            print(line)

        print()
        stats = {}
        for f in files:
            s = f.get("status", "other")
            stats[s] = stats.get(s, 0) + 1

        summary_parts = []
        for status in order:
            if stats.get(status, 0) > 0:
                summary_parts.append(f"{stats[status]} {status}")
        print(f"  Razem: {len(files)} ({', '.join(summary_parts)})")
        print()

    def _reload_cache(self):
        """Force cache invalidation."""
        builder = self._get_builder()
        if builder is None:
            print("[Awareness] Modul niedostepny.\n")
            return

        builder.invalidate_cache()
        context = builder.build()

        print("[Awareness] Cache odswiezony.")
        if context:
            content = context.replace("[Swiadomosc: ", "").rstrip(".]")
            print(f"  {content}")
        print()

    def cleanup(self):
        pass
