"""K12 Self-Analysis REPL commands: /analyze."""

import logging
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class SelfAnalysisModule(MariaModule):
    """K12 Self-Analysis - cognitive loop REPL interface."""

    name = "self_analysis"
    description = "Self-analysis cognitive loop (K12)"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/analyze", self._cmd_analyze,
                "  /analyze          - uruchom self-analysis (zbierz stan, analizuj, stworz cele)\n"
                "  /analyze status   - status modulu K12\n"
                "  /analyze report   - ostatni raport\n"
                "  /analyze collect  - pokaz skompresowany stan (bez analizy)",
                "[K12] SELF-ANALYSIS",
            ),
        ]

    def _get_sa(self):
        return getattr(self.ctx, 'self_analysis', None)

    def _cmd_analyze(self, args):
        """Handle /analyze commands."""
        args = args.strip()

        if args == "status":
            self._show_status()
        elif args == "report":
            self._show_last_report()
        elif args == "collect":
            self._show_collected_state()
        elif args == "" or args == "run":
            self._run_analysis()
        else:
            print("[K12] Nieznana komenda. Uzyj: /analyze [status|report|collect]")

    def _run_analysis(self):
        """Run full self-analysis cycle."""
        sa = self._get_sa()
        if sa is None:
            print("[K12] SelfAnalysis nie zainicjalizowany")
            return

        print("\n[K12] Uruchamiam self-analysis...")
        print("  Faza 1: Zbieranie stanu z logow...")

        report = sa.run_analysis()

        if report.error:
            print(f"  [BLAD] {report.error}")
            return

        print(f"  Faza 2: Analiza ukonczona ({report.duration_ms:.0f}ms)")
        print(f"  Faza 3: {len(report.recommendations)} rekomendacji")
        print()

        if not report.recommendations:
            print("  Brak rekomendacji - system dziala dobrze!")
            return

        print("=" * 60)
        print("[K12] REKOMENDACJE")
        print("=" * 60)

        for i, rec in enumerate(report.recommendations, 1):
            priority_bar = "#" * int(rec.priority * 10)
            print(f"\n  {i}. [{rec.category.upper()}] {rec.topic}")
            print(f"     {rec.description[:120]}")
            print(f"     Priorytet: [{priority_bar:<10}] {rec.priority:.1f}")
            print(f"     Akcja: {rec.suggested_action}")

        print()
        if report.goals_created:
            print(f"  Utworzono {len(report.goals_created)} celow PROPOSED:")
            for gid in report.goals_created:
                print(f"    - {gid}")
            print("  Zatwierdz: /goal confirm <id>")
        else:
            print("  Cele nie zostaly utworzone (brak goal_store)")

        print(f"\n  Raport: {report.report_id}")

    def _show_status(self):
        """Show K12 status."""
        sa = self._get_sa()
        if sa is None:
            print("[K12] SelfAnalysis nie zainicjalizowany")
            return

        status = sa.get_status()

        print("\n" + "=" * 50)
        print("[K12] SELF-ANALYSIS STATUS")
        print("=" * 50)
        print(f"  Dostepny:          {'TAK' if status['available'] else 'NIE (brak LLM)'}")
        print(f"  Cooldown:          {status['cooldown_sec'] / 3600:.0f}h")

        if status['last_analysis_ts'] > 0:
            dt = datetime.fromtimestamp(status['last_analysis_ts'])
            print(f"  Ostatnia analiza:  {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"  Ostatnia analiza:  nigdy")

        if status['last_report_id']:
            print(f"  Ostatni raport:    {status['last_report_id']}")
            print(f"  Rekomendacji:      {status['last_recommendations']}")
            print(f"  Celow utworzonych:  {status['last_goals_created']}")

    def _show_last_report(self):
        """Show last analysis report."""
        sa = self._get_sa()
        if sa is None:
            print("[K12] SelfAnalysis nie zainicjalizowany")
            return

        report = sa.get_last_report()
        if report is None:
            print("[K12] Brak raportow. Uruchom: /analyze")
            return

        dt = datetime.fromtimestamp(report.timestamp)
        print(f"\n{'=' * 60}")
        print(f"[K12] RAPORT: {report.report_id}")
        print(f"{'=' * 60}")
        print(f"  Czas:      {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Backend:   {report.analyzer}")
        print(f"  Czas exec: {report.duration_ms:.0f}ms")

        if report.error:
            print(f"  BLAD:      {report.error}")
            return

        print(f"  Rekomendacje ({len(report.recommendations)}):")
        for i, rec in enumerate(report.recommendations, 1):
            print(f"    {i}. [{rec.category}] {rec.topic} (p={rec.priority:.1f}, akcja={rec.suggested_action})")
            print(f"       {rec.description[:100]}")

        if report.goals_created:
            print(f"\n  Cele: {', '.join(report.goals_created)}")

    def _show_collected_state(self):
        """Show compressed state (debug)."""
        sa = self._get_sa()
        if sa is None:
            print("[K12] SelfAnalysis nie zainicjalizowany")
            return

        import json
        state = sa._collector.collect()

        print(f"\n[K12] Stan skompresowany ({len(json.dumps(state))} bytes):")
        print()

        # Metrics trend
        mt = state.get("metrics_trend", {})
        for key, values in mt.items():
            if values:
                print(f"  {key}: {' -> '.join(f'{v:.2f}' for v in values[-5:])}")

        # Knowledge gaps
        gaps = state.get("knowledge_gaps", [])
        if gaps:
            print(f"\n  Luki wiedzy ({len(gaps)}):")
            for g in gaps[:5]:
                print(f"    - {g['topic']} (confidence: {g['confidence']:.2f})")

        # Action distribution
        dist = state.get("action_distribution", {})
        if dist:
            print(f"\n  Dystrybucja akcji:")
            for action, stats in dist.items():
                print(f"    {action}: {stats['count']}x (success: {stats['success_pct']:.0%})")

        # Stale goals
        stale = state.get("stale_goals", [])
        if stale:
            print(f"\n  Stale goals ({len(stale)}):")
            for g in stale:
                print(f"    - {g['description']} ({g['days_stale']:.1f}d)")

        # Learning progress
        lp = state.get("learning_progress", {})
        if lp:
            print(f"\n  Nauka: {lp.get('total_files', 0)} plikow, "
                  f"ostatnie {lp.get('recent_learn_count', 0)} prob: "
                  f"{lp.get('recent_learn_success_rate', 0):.0%} success")
