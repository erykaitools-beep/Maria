"""
LimitationReporter (V3 Phase D, Module 13)

Reports what Maria can and cannot do, with reasons.
Aggregates limitations from K7 (autonomy), K9 (meta-cognition),
K10 (action safety), mode constraints, and resource availability.

Wraps V2: K7 classifications, K9 needs_human, K10 safety modes,
homeostasis mode, model availability.

Usage:
    reporter = LimitationReporter(ctx)
    limits = reporter.get_current_limitations()
    can = reporter.can_do("effector")
    report = reporter.get_report()
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LimitationReporter:
    """Reports Maria's current limitations and constraints."""

    def __init__(self, ctx):
        self._ctx = ctx

    def get_current_limitations(self) -> List[Dict[str, Any]]:
        """
        Get all current active limitations.

        Returns:
            List of limitation dicts with category, description, severity.
        """
        limitations = []

        # Mode limitations
        limitations.extend(self._mode_limitations())

        # K7 autonomy limitations
        limitations.extend(self._autonomy_limitations())

        # Resource limitations
        limitations.extend(self._resource_limitations())

        # Hardware limitations
        limitations.extend(self._hardware_limitations())

        return limitations

    def can_do(self, action: str) -> Dict[str, Any]:
        """
        Check if Maria can do a specific action right now.

        Args:
            action: Action name

        Returns:
            Dict with can_do, reasons, and suggestions.
        """
        reasons = []
        suggestions = []

        # Check capability availability
        router = getattr(self._ctx, "capability_router", None)
        if router:
            if not router.is_available(action):
                reasons.append(f"Zdolnosc '{action}' nie jest zarejestrowana")
                suggestions.append("Sprawdz czy modul jest zainicjalizowany")
        else:
            reasons.append("CapabilityRouter niedostepny")

        # Check K7 autonomy
        policy = self._ctx.autonomy_policy
        if policy:
            try:
                classification = policy.classify_action(action)
                level = getattr(classification, "level",
                               getattr(classification, "value", str(classification)))
                if level == "forbidden":
                    reasons.append(f"Akcja '{action}' jest zabroniona (K7)")
                elif level == "restricted":
                    suggestions.append("Wymaga zatwierdzenia operatora (/approve)")
            except Exception:
                pass

        # Check mode
        mode = self._get_mode()
        if mode in ("SLEEP", "SURVIVAL"):
            if action not in ("noop", "evaluate", "maintenance"):
                reasons.append(f"Tryb {mode} blokuje wiekszosc akcji")
                suggestions.append("Poczekaj na powrot do trybu ACTIVE")
        elif mode == "REDUCED":
            heavy_actions = {"learn", "exam", "self_analyze", "creative", "ask_expert"}
            if action in heavy_actions:
                reasons.append("Tryb REDUCED ogranicza ciezkie operacje LLM")

        can = len(reasons) == 0

        return {
            "action": action,
            "can_do": can,
            "reasons": reasons,
            "suggestions": suggestions,
        }

    def get_blocked_actions(self) -> List[Dict[str, Any]]:
        """
        List all currently blocked actions with reasons.

        Returns:
            List of blocked action dicts.
        """
        router = getattr(self._ctx, "capability_router", None)
        if not router:
            return []

        blocked = []
        for spec in router.list_capabilities():
            check = self.can_do(spec.name)
            if not check["can_do"]:
                blocked.append({
                    "action": spec.name,
                    "reasons": check["reasons"],
                    "suggestions": check["suggestions"],
                })
        return blocked

    def get_report(self) -> Dict[str, Any]:
        """
        Complete limitation report.

        Returns:
            Dict with all limitations, blocked actions, and suggestions.
        """
        limitations = self.get_current_limitations()
        blocked = self.get_blocked_actions()

        # Severity counts
        by_severity = {}
        for lim in limitations:
            sev = lim.get("severity", "info")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return {
            "total_limitations": len(limitations),
            "by_severity": by_severity,
            "limitations": limitations,
            "blocked_actions": blocked,
            "blocked_count": len(blocked),
            "mode": self._get_mode(),
        }

    def describe(self) -> str:
        """Human-readable limitation summary in Polish."""
        report = self.get_report()
        lines = [f"Ograniczenia ({report['total_limitations']}):"]

        for lim in report["limitations"]:
            sev = lim["severity"].upper()
            lines.append(f"  [{sev}] {lim['description']}")

        if report["blocked_actions"]:
            lines.append(f"\nZablokowane akcje ({report['blocked_count']}):")
            for b in report["blocked_actions"]:
                lines.append(f"  {b['action']}: {'; '.join(b['reasons'])}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Limitation sources
    # ------------------------------------------------------------------

    def _mode_limitations(self) -> List[Dict]:
        mode = self._get_mode()
        if mode == "ACTIVE":
            return []
        if mode == "REDUCED":
            return [{
                "category": "mode",
                "severity": "warning",
                "description": "Tryb REDUCED - ciezkie operacje LLM ograniczone",
                "suggestion": "System wroci do ACTIVE gdy zasoby beda wystarczajace",
            }]
        if mode == "SLEEP":
            return [{
                "category": "mode",
                "severity": "critical",
                "description": "Tryb SLEEP - tylko operacje konsolidacji pamieci",
                "suggestion": "System obudzi sie automatycznie lub przy interakcji",
            }]
        if mode == "SURVIVAL":
            return [{
                "category": "mode",
                "severity": "critical",
                "description": "Tryb SURVIVAL - tylko minimalne operacje",
                "suggestion": "Sprawdz zasoby systemowe (RAM, CPU, temperatura)",
            }]
        return []

    def _autonomy_limitations(self) -> List[Dict]:
        limitations = []
        policy = self._ctx.autonomy_policy
        if not policy:
            return []

        # Check K9 needs_human
        meta = self._ctx.meta_cognition
        if meta:
            try:
                if meta.needs_human():
                    limitations.append({
                        "category": "cognition",
                        "severity": "warning",
                        "description": "K9 sygnalizuje potrzebe konsultacji z operatorem",
                        "suggestion": "Przejrzyj /trace i /goals aby ocenic sytuacje",
                    })
            except Exception:
                pass

        return limitations

    def _resource_limitations(self) -> List[Dict]:
        limitations = []

        # NIM budget
        try:
            from agent_core.orchestrator.cost_estimator import CostEstimator
            budget = CostEstimator(self._ctx).get_budget_status()
            if budget.nim_status == "DEPLETED":
                limitations.append({
                    "category": "budget",
                    "severity": "warning",
                    "description": "Budzet NIM API wyczerpany na dzis",
                    "suggestion": "Mozna uzywac lokalnego LLM (nizsza jakosc analizy)",
                })
            elif budget.nim_status == "LOW":
                limitations.append({
                    "category": "budget",
                    "severity": "info",
                    "description": f"Budzet NIM niski ({budget.nim_remaining_today} tokenow)",
                    "suggestion": "Ogranicz uzycie self_analyze i creative",
                })
        except Exception:
            pass

        return limitations

    def _hardware_limitations(self) -> List[Dict]:
        """Static hardware limitations."""
        limitations = [
            {
                "category": "hardware",
                "severity": "info",
                "description": "Lokalne LLM: llama3.1:8b (32GB RAM, brak GPU)",
                "suggestion": "Uzywaj NIM API do zlozonych analiz",
            },
            {
                "category": "hardware",
                "severity": "info",
                "description": "Nauka tylko z plikow tekstowych w input/",
                "suggestion": "Wrzuc pliki .txt do input/ lub uzyj /fetch",
            },
        ]

        # OpenClaw check
        if not self._ctx.openclaw_client:
            limitations.append({
                "category": "hardware",
                "severity": "info",
                "description": "OpenClaw efektor niedostepny",
                "suggestion": "Uruchom gateway OpenClaw jesli potrzebna egzekucja",
            })

        return limitations

    def _get_mode(self) -> str:
        core = self._ctx.homeostasis_core
        if core:
            mode = getattr(core, "_current_mode", None)
            if mode:
                return mode.name if hasattr(mode, "name") else str(mode)
        return "UNKNOWN"
