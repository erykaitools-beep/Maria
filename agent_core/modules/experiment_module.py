"""Experiment REPL commands: /experiments, /experiment approve/reject/status/report/params."""

import logging
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class ExperimentModule(MariaModule):
    """K11 Experiment System - autonomous parameter tuning."""

    name = "experiment"
    description = "Autonomous parameter tuning (K11)"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/experiments", self._cmd_experiments,
                "  /experiments            - lista propozycji i eksperymentow\n"
                "  /experiment approve <id> - zatwierdz propozycje\n"
                "  /experiment reject <id>  - odrzuc propozycje\n"
                "  /experiment status       - aktualny eksperyment\n"
                "  /experiment report <id>  - pokaz raport\n"
                "  /experiment params       - lista parametrow do tuningu\n"
                "  /experiment comment <id> <text> - dodaj uwage",
                "[LAB] EXPERIMENT SYSTEM (K11)",
            ),
            CommandInfo(
                "/experiment", self._cmd_experiment,
                "",  # Subcommands shown above
                "[LAB] EXPERIMENT",
            ),
        ]

    def _get_system(self):
        return getattr(self.ctx, 'experiment_system', None)

    def _cmd_experiments(self, args):
        """Handle /experiments - list proposals and experiments."""
        system = self._get_system()
        if system is None:
            print("[Experiment] Nie zainicjalizowany")
            return

        proposals = system.proposal_engine.get_all_proposals()
        reports = system.get_all_reports()

        print("\n" + "=" * 60)
        print("[LAB] EXPERIMENT SYSTEM (K11)")
        print("=" * 60)

        if not proposals and not reports:
            print("  Brak propozycji i raportow.")
            print("  System automatycznie wygeneruje propozycje")
            print("  na podstawie obserwacji K4/K9.")
        else:
            if proposals:
                print(f"\n  PROPOZYCJE ({len(proposals)}):")
                print("  " + "-" * 56)
                for p in proposals[-10:]:
                    status_icon = {
                        "draft": "[...]",
                        "proposed": "[?]",
                        "approved": "[OK]",
                        "rejected": "[X]",
                        "expired": "[~]",
                    }.get(p.status.value, "[?]")

                    ts = datetime.fromtimestamp(p.timestamp).strftime("%m-%d %H:%M")
                    print(f"  {status_icon} {p.proposal_id}")
                    print(f"      {ts} | {p.parameter_id}")
                    print(f"      {p.current_value} -> {p.proposed_value}")
                    print(f"      {p.hypothesis[:60]}")
                    if p.comments:
                        print(f"      ({len(p.comments)} uwag)")

            if reports:
                print(f"\n  RAPORTY ({len(reports)}):")
                print("  " + "-" * 56)
                for r in reports[-5:]:
                    ts = datetime.fromtimestamp(r.timestamp).strftime("%m-%d %H:%M")
                    rec_icon = {
                        "ADOPT": "[+]",
                        "REJECT": "[-]",
                        "INCONCLUSIVE": "[?]",
                    }.get(r.recommendation, "[?]")
                    print(f"  {rec_icon} {r.report_id}")
                    print(f"      {ts} | {r.parameter_id}")
                    print(f"      {r.recommendation} (confidence: {r.confidence:.0%})")
                    print(f"      {r.conclusion[:60]}")

        # Status summary
        status = system.get_status()
        current = status.get("current_experiment")
        if current:
            print(f"\n  AKTUALNY EKSPERYMENT:")
            print(f"    {current['experiment_id']} ({current['status']})")
            print(f"    Cykli: {current['test_cycles']}/{current['target_cycles']}")

        print("\n" + "=" * 60 + "\n")

    def _cmd_experiment(self, args):
        """Handle /experiment subcommands."""
        system = self._get_system()
        if system is None:
            print("[Experiment] Nie zainicjalizowany")
            return

        if not args:
            return self._cmd_experiments([])

        sub = args[0].lower()

        if sub == "approve":
            if len(args) < 2:
                print("[Experiment] Uzycie: /experiment approve <proposal_id>")
                return
            self._approve(system, args[1])

        elif sub == "reject":
            if len(args) < 2:
                print("[Experiment] Uzycie: /experiment reject <proposal_id>")
                return
            self._reject(system, args[1])

        elif sub == "status":
            self._show_status(system)

        elif sub == "report":
            if len(args) < 2:
                print("[Experiment] Uzycie: /experiment report <report_id>")
                return
            self._show_report(system, args[1])

        elif sub == "params":
            self._show_params()

        elif sub == "comment":
            if len(args) < 3:
                print("[Experiment] Uzycie: /experiment comment <proposal_id> <text>")
                return
            proposal_id = args[1]
            text = " ".join(args[2:])
            self._add_comment(system, proposal_id, text)

        else:
            print(f"[Experiment] Nieznana komenda: {sub}")
            print("  Dostepne: approve, reject, status, report, params, comment")

    def _approve(self, system, proposal_id):
        """Approve a proposal."""
        proposal = system.proposal_engine.get_proposal(proposal_id)
        if proposal is None:
            # Try partial match
            proposals = system.proposal_engine.get_all_proposals()
            matches = [p for p in proposals if proposal_id in p.proposal_id]
            if len(matches) == 1:
                proposal = matches[0]
                proposal_id = proposal.proposal_id
            else:
                print(f"[Experiment] Propozycja {proposal_id} nie znaleziona")
                return

        if system.approve(proposal_id):
            print(f"[Experiment] [OK] Propozycja {proposal_id} zatwierdzona")
            print(f"  Parametr: {proposal.parameter_id}")
            print(f"  Zmiana: {proposal.current_value} -> {proposal.proposed_value}")
            print(f"  Eksperyment zostanie uruchomiony w nastepnym cyklu planera.")
        else:
            print(f"[Experiment] [WARN] Nie udalo sie zatwierdzic {proposal_id}")

    def _reject(self, system, proposal_id):
        """Reject a proposal."""
        proposal = system.proposal_engine.get_proposal(proposal_id)
        if proposal is None:
            proposals = system.proposal_engine.get_all_proposals()
            matches = [p for p in proposals if proposal_id in p.proposal_id]
            if len(matches) == 1:
                proposal_id = matches[0].proposal_id
            else:
                print(f"[Experiment] Propozycja {proposal_id} nie znaleziona")
                return

        if system.reject(proposal_id):
            print(f"[Experiment] [OK] Propozycja {proposal_id} odrzucona")
        else:
            print(f"[Experiment] [WARN] Nie udalo sie odrzucic {proposal_id}")

    def _show_status(self, system):
        """Show experiment system status."""
        status = system.get_status()
        prop_status = status["proposals"]

        print("\n" + "=" * 50)
        print("[LAB] EXPERIMENT STATUS")
        print("=" * 50)
        print(f"  Propozycji razem:  {prop_status['total_proposals']}")
        print(f"  Aktywnych:         {prop_status['active']}")
        print(f"  Dzis wygenerowano: {prop_status['today_count']}/{prop_status['daily_limit']}")
        print(f"  Raportow:          {status['total_reports']}")

        current = status.get("current_experiment")
        if current:
            print(f"\n  Aktualny eksperyment:")
            print(f"    ID: {current['experiment_id']}")
            print(f"    Parametr: {current['parameter_id']}")
            print(f"    Cykli: {current['test_cycles']}/{current['target_cycles']}")
            print(f"    Status: {current['status']}")
        else:
            print(f"\n  Brak aktywnego eksperymentu")

        print("=" * 50 + "\n")

    def _show_report(self, system, report_id):
        """Show detailed report."""
        report = system.get_report(report_id)
        if report is None:
            # Try partial match
            reports = system.get_all_reports()
            matches = [r for r in reports if report_id in r.report_id]
            if len(matches) == 1:
                report = matches[0]
            else:
                print(f"[Experiment] Raport {report_id} nie znaleziony")
                return

        print("\n" + "=" * 60)
        print(f"[LAB] RAPORT: {report.report_id}")
        print("=" * 60)
        ts = datetime.fromtimestamp(report.timestamp).strftime("%Y-%m-%d %H:%M")
        print(f"  Data:          {ts}")
        print(f"  Eksperyment:   {report.experiment_id}")
        print(f"  Propozycja:    {report.proposal_id}")

        print(f"\n  Parametr:      {report.parameter_id}")
        print(f"  Bazowa:        {report.baseline_value}")
        print(f"  Testowa:       {report.test_value}")

        print(f"\n  Hipoteza:      {report.hypothesis}")
        print(f"  Metoda:        {report.method}")

        print(f"\n  Metryki PRZED:")
        for k, v in report.baseline_metrics.items():
            print(f"    {k}: {v:.3f}")
        print(f"\n  Metryki PO:")
        for k, v in report.result_metrics.items():
            print(f"    {k}: {v:.3f}")
        print(f"\n  Delty:")
        for k, v in report.delta_metrics.items():
            sign = "+" if v > 0 else ""
            print(f"    {k}: {sign}{v:.3f}")

        print(f"\n  Cykli:         {report.test_cycles}")
        print(f"  Czas:          {report.duration_sec:.0f}s")

        rec_icon = {"ADOPT": "[+]", "REJECT": "[-]", "INCONCLUSIVE": "[?]"}
        icon = rec_icon.get(report.recommendation, "[?]")
        print(f"\n  {icon} REKOMENDACJA: {report.recommendation}")
        print(f"  Pewnosc:       {report.confidence:.0%}")
        print(f"  Wniosek:       {report.conclusion}")

        print("\n" + "=" * 60 + "\n")

    def _show_params(self):
        """Show all tunable parameters."""
        from agent_core.experiment import parameter_registry

        params = parameter_registry.list_parameters()

        print("\n" + "=" * 70)
        print("[LAB] PARAMETRY DO TUNINGU")
        print("=" * 70)

        by_risk = {"low": [], "medium": [], "high": []}
        for pid, spec in params.items():
            by_risk[spec.risk_level.value].append((pid, spec))

        for risk in ["low", "medium", "high"]:
            items = by_risk[risk]
            if items:
                label = {"low": "LOW RISK", "medium": "MEDIUM RISK", "high": "HIGH RISK"}
                print(f"\n  {label[risk]}:")
                print("  " + "-" * 66)
                for pid, spec in items:
                    print(f"    {pid}")
                    print(f"      Wartosc: {spec.current_value} "
                          f"[{spec.min_value} - {spec.max_value}] step={spec.step}")
                    print(f"      Metryka: {spec.impact_metric}")
                    print(f"      {spec.description}")

        print(f"\n  Razem: {len(params)} parametrow")
        print("=" * 70 + "\n")

    def _add_comment(self, system, proposal_id, text):
        """Add comment to a proposal."""
        if system.add_comment(proposal_id, text, "user"):
            print(f"[Experiment] [OK] Dodano uwage do {proposal_id}")
        else:
            print(f"[Experiment] [WARN] Nie udalo sie dodac uwagi do {proposal_id}")
