"""Introspection REPL commands: /introspect [summary|detail|issues|layers|module|start|stop]."""

import os

from agent_core.registry import MariaModule, CommandInfo
from agent_core.introspection import (
    init_introspection,
    get_introspection_scheduler,
    CodeAnalyzer,
    DualReporter,
)


class IntrospectionModule(MariaModule):
    """Code self-awareness - Maria can analyze her own architecture."""

    name = "introspection"
    description = "READ-ONLY code analysis (AST, layers, issues)"

    def __init__(self):
        self._scheduler = None

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/introspect", self._cmd_introspect,
                "  /introspect            - pokaz jak jestem zbudowana\n"
                "  /introspect detail     - szczegolowy raport techniczny\n"
                "  /introspect issues     - pokaz problemy w kodzie\n"
                "  /introspect module X   - info o module X\n"
                "  /introspect layers     - pokaz warstwy architektury",
                "[MIRROR] CODE INTROSPECTION",
            ),
        ]

    def _ensure_scheduler(self):
        """Lazy-initialize introspection scheduler."""
        if self._scheduler is None:
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            self._scheduler = init_introspection(
                project_root=project_root,
                start_scheduler=False,
            )

    def _cmd_introspect(self, args):
        """Handle /introspect commands."""
        self._ensure_scheduler()

        subcommand = args[0].lower() if args else "summary"

        if subcommand in ("summary", ""):
            self._show_summary()
        elif subcommand == "detail":
            self._show_detail()
        elif subcommand == "issues":
            self._show_issues()
        elif subcommand == "layers":
            self._show_layers()
        elif subcommand == "module":
            module_name = args[1] if len(args) >= 2 else None
            self._show_module(module_name)
        elif subcommand == "start":
            self._scheduler.start()
            print(f"[Introspect] [OK] Okresowa analiza uruchomiona (co {self._scheduler.interval_sec}s)")
        elif subcommand == "stop":
            self._scheduler.stop()
            print("[Introspect] [OK] Okresowa analiza zatrzymana")
        else:
            print(f"[Introspect] Nieznana podkomenda: {subcommand}")
            print("  Uzycie: /introspect [summary|detail|issues|layers|module|start|stop]")

    def _show_summary(self):
        print("[Introspect] Analizuje swoj kod...")
        model = self._scheduler.run_now()

        if not model:
            print("[Introspect] [ERROR] Analiza nie powiodla sie")
            return

        reporter = DualReporter(model)
        human_text, tech_text = reporter.full_report()

        print("\n" + "=" * 60)
        print("[MIRROR] JAK JESTEM ZBUDOWANA")
        print("=" * 60)
        print(f"\nMaria: {human_text}")
        print(f"\n       {tech_text}")
        print("=" * 60 + "\n")

    def _show_detail(self):
        model = self._scheduler.get_model()
        if not model:
            print("[Introspect] Uruchamiam analize...")
            model = self._scheduler.run_now()

        if not model:
            print("[Introspect] [ERROR] Brak danych")
            return

        reporter = DualReporter(model)
        print("\n" + reporter.tech.detailed_stats())
        print()

    def _show_issues(self):
        model = self._scheduler.get_model()
        if not model:
            model = self._scheduler.run_now()

        if not model:
            print("[Introspect] [ERROR] Brak danych")
            return

        reporter = DualReporter(model)
        print("\n" + reporter.tech.issues_report())
        print()

    def _show_layers(self):
        model = self._scheduler.get_model()
        if not model:
            model = self._scheduler.run_now()

        if not model:
            print("[Introspect] [ERROR] Brak danych")
            return

        reporter = DualReporter(model)
        print("\n" + reporter.tech.layers_report())

        print("\n--- HUMAN DESCRIPTIONS ---")
        for layer in model.layers.keys():
            desc = reporter.human.describe_layer(layer)
            if desc:
                print(f"\n{layer.upper()}: {desc}")
        print()

    def _show_module(self, module_name):
        if not module_name:
            print("[Introspect] Uzycie: /introspect module <nazwa>")
            print("  Przyklad: /introspect module agent_core.homeostasis.core")
            return

        model = self._scheduler.get_model()
        if not model:
            model = self._scheduler.run_now()

        if not model:
            print("[Introspect] [ERROR] Brak danych")
            return

        reporter = DualReporter(model)

        # Try partial match
        found = None
        for pkg in model.modules.keys():
            if module_name in pkg:
                found = pkg
                break

        if not found:
            print(f"[Introspect] Nie znalazlem modulu: {module_name}")
            print(f"  Dostepne: {', '.join(list(model.modules.keys())[:10])}...")
            return

        tech_report = reporter.tech.module_report(found)
        human_desc = reporter.human.describe_module(found)

        print("\n" + "=" * 60)
        print(f"[MODULE] {found}")
        print("=" * 60)
        if human_desc:
            print(f"\nMaria: {human_desc}")
        if tech_report:
            print(f"\n{tech_report}")
        print("=" * 60 + "\n")

    def cleanup(self):
        if self._scheduler:
            self._scheduler.stop()
