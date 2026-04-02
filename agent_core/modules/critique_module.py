"""REPL commands: /critique - knowledge quality gate (Faza G)."""

import logging
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class CritiqueModule(MariaModule):
    """Faza G: Knowledge quality critique REPL interface."""

    name = "critique"
    description = "Knowledge quality critique (Faza G)"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/critique", self._cmd_critique,
                "  /critique              - ostatni raport krytyki\n"
                "  /critique run          - uruchom krtyke teraz\n"
                "  /critique status       - status systemu krytyki\n"
                "  /critique findings     - szczegoly ostatnich findings",
                "[QUALITY] KNOWLEDGE CRITIQUE (Faza G)",
            ),
        ]

    def _get_critic(self):
        return getattr(self.ctx, "critic_agent", None)

    def _cmd_critique(self, args):
        sub = args[0] if args else ""

        if sub == "run":
            self._run_critique()
        elif sub == "status":
            self._show_status()
        elif sub == "findings":
            self._show_findings()
        else:
            self._show_last_report()

    def _show_last_report(self):
        critic = self._get_critic()
        if critic is None:
            print("[Critique] Nie zainicjalizowano")
            return

        report = critic.get_last_report()
        if report is None:
            print("[Critique] Brak raportow. Uzyj /critique run")
            return

        ts = datetime.fromtimestamp(report.timestamp).strftime("%Y-%m-%d %H:%M")
        print(f"\n{'=' * 60}")
        print(f"  RAPORT KRYTYKI  |  {ts}  |  {report.report_id[:12]}")
        print(f"{'=' * 60}")
        print(f"  Trigger:    {report.trigger}")
        print(f"  Findings:   {len(report.findings)} (total: {report.findings_total})")
        print(f"  Goals:      {len(report.goals_created)} created")
        print(f"  Duration:   {report.duration_ms:.0f}ms")

        if report.findings_by_severity:
            sev = ", ".join(
                f"{k}: {v}" for k, v in sorted(report.findings_by_severity.items())
            )
            print(f"  Severity:   {sev}")

        if report.findings_by_category:
            cats = ", ".join(
                f"{k}: {v}" for k, v in sorted(report.findings_by_category.items())
            )
            print(f"  Categories: {cats}")

        if report.findings:
            print(f"\n  {'---'*10}")
            for i, f in enumerate(report.findings, 1):
                sev_marker = {"CRITICAL": "!!", "WARNING": "!", "INFO": "."}
                marker = sev_marker.get(f.severity, "?")
                print(f"  [{marker}] {f.category}: {f.topic}")
                print(f"      {f.description[:80]}")
                print(f"      -> {f.suggested_action}")

        if report.llm_summary:
            print(f"\n  Podsumowanie LLM:")
            print(f"    {report.llm_summary[:200]}")

        if report.error:
            print(f"\n  BLAD: {report.error}")

        print()

    def _run_critique(self):
        critic = self._get_critic()
        if critic is None:
            print("[Critique] Nie zainicjalizowano")
            return

        print("[Critique] Uruchamiam analize...")
        report = critic.run_critique(trigger="manual")

        if report.error:
            print(f"[Critique] Blad: {report.error}")
            return

        print(
            f"[Critique] Gotowe: {len(report.findings)} findings, "
            f"{len(report.goals_created)} goals created "
            f"({report.duration_ms:.0f}ms)"
        )

        if report.findings:
            for f in report.findings:
                sev_marker = {"CRITICAL": "!!", "WARNING": "!", "INFO": "."}
                marker = sev_marker.get(f.severity, "?")
                print(f"  [{marker}] {f.category}: {f.topic} -> {f.suggested_action}")

    def _show_status(self):
        critic = self._get_critic()
        if critic is None:
            print("[Critique] Nie zainicjalizowano")
            return

        status = critic.get_status()
        print(f"\n[Critique] Status:")
        print(f"  Available:     {status['available']}")

        last_ts = status["last_critique_ts"]
        if last_ts > 0:
            ts_str = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M")
            print(f"  Last critique: {ts_str}")
        else:
            print(f"  Last critique: nigdy")

        cooldown_h = status["cooldown_sec"] / 3600
        print(f"  Cooldown:      {cooldown_h:.0f}h")
        print(f"  Last findings: {status['last_findings']} (total: {status['last_findings_total']})")
        print(f"  Last goals:    {status['last_goals_created']}")
        print()

    def _show_findings(self):
        critic = self._get_critic()
        if critic is None:
            print("[Critique] Nie zainicjalizowano")
            return

        report = critic.get_last_report()
        if report is None or not report.findings:
            print("[Critique] Brak findings")
            return

        print(f"\n{'=' * 60}")
        print(f"  FINDINGS DETAIL  |  {len(report.findings)} items")
        print(f"{'=' * 60}")

        for i, f in enumerate(report.findings, 1):
            sev_marker = {"CRITICAL": "!!", "WARNING": "!", "INFO": "."}
            marker = sev_marker.get(f.severity, "?")
            print(f"\n  {i}. [{marker}] {f.category} ({f.severity})")
            print(f"     Topic:    {f.topic}")
            print(f"     Opis:     {f.description}")
            print(f"     Akcja:    {f.suggested_action}")
            if f.belief_ids:
                print(f"     Beliefs:  {', '.join(f.belief_ids[:3])}")
            if f.evidence_sources:
                print(f"     Sources:  {', '.join(f.evidence_sources[:3])}")
            if f.confidence_delta != 0:
                print(f"     Conf delta: {f.confidence_delta:+.2f}")
            if f.recommended_goal_title:
                print(f"     Goal:     {f.recommended_goal_title}")

        print()

    def cleanup(self) -> None:
        pass
