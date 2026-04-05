"""
ToolCapabilityRegistry (V3 Phase D, Module 11)

User-facing tool and capability discovery. Presents Maria's abilities
in a structured way: what tools exist, what's available, what requires
approval, and what external services are connected.

Wraps V2: CapabilityRouter, OpenClaw tool_specs, Claude/Codex clients.

Usage:
    registry = ToolCapabilityRegistry(ctx)
    tools = registry.list_all()
    external = registry.list_external_services()
    summary = registry.get_summary()
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolCapabilityRegistry:
    """User-facing capability and tool discovery."""

    def __init__(self, ctx):
        self._ctx = ctx

    def list_all(self) -> List[Dict[str, Any]]:
        """
        List all capabilities with user-friendly descriptions.

        Returns:
            List of capability dicts grouped and described.
        """
        router = getattr(self._ctx, "capability_router", None)
        if not router:
            return []

        results = []
        for spec in router.list_capabilities():
            results.append({
                "name": spec.name,
                "description": spec.description,
                "tags": list(spec.tags),
                "k7_classification": spec.k7_classification,
                "available": router.is_available(spec.name),
                "requires_approval": spec.k7_classification == "restricted",
                "category": self._categorize(spec.tags),
            })
        return results

    def list_by_category(self) -> Dict[str, List[Dict[str, Any]]]:
        """List capabilities grouped by category."""
        all_caps = self.list_all()
        groups: Dict[str, List[Dict]] = {}
        for cap in all_caps:
            cat = cap["category"]
            groups.setdefault(cat, []).append(cap)
        return groups

    def list_external_services(self) -> List[Dict[str, Any]]:
        """
        List connected external services and their status.

        Returns:
            List of external service status dicts.
        """
        services = []

        # NIM API
        try:
            from agent_core.orchestrator.cost_estimator import CostEstimator
            budget = CostEstimator(self._ctx).get_budget_status()
            services.append({
                "name": "NVIDIA NIM API",
                "type": "llm_api",
                "status": "available" if budget.nim_status != "DEPLETED" else "depleted",
                "details": {
                    "remaining_today": budget.nim_remaining_today,
                    "budget_status": budget.nim_status,
                    "rpm_available": budget.nim_rpm_available,
                },
            })
        except Exception:
            services.append({
                "name": "NVIDIA NIM API",
                "type": "llm_api",
                "status": "unknown",
                "details": {},
            })

        # Ollama (local)
        services.append({
            "name": "Ollama (local LLM)",
            "type": "local_llm",
            "status": "available",
            "details": {
                "model": getattr(self._ctx, "brain_model", "llama3.1:8b"),
            },
        })

        # OpenClaw
        openclaw = self._ctx.openclaw_client
        services.append({
            "name": "OpenClaw Effector",
            "type": "effector",
            "status": "available" if openclaw else "disconnected",
            "details": {},
        })

        # Codex (ChatGPT)
        codex = self._ctx.codex_client
        services.append({
            "name": "Codex (ChatGPT Plus)",
            "type": "external_llm",
            "status": "available" if codex else "not_configured",
            "details": {},
        })

        # Telegram
        telegram = self._ctx.telegram_bridge
        services.append({
            "name": "Telegram (ClawBot)",
            "type": "communication",
            "status": "available" if telegram else "not_configured",
            "details": {},
        })

        return services

    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Search capabilities by name, description, or tag.

        Args:
            query: Search text

        Returns:
            Matching capabilities.
        """
        query_lower = query.lower()
        results = []
        for cap in self.list_all():
            if (query_lower in cap["name"].lower() or
                query_lower in cap["description"].lower() or
                any(query_lower in t for t in cap["tags"])):
                results.append(cap)
        return results

    def get_summary(self) -> Dict[str, Any]:
        """Get high-level capability summary."""
        all_caps = self.list_all()
        services = self.list_external_services()

        free = sum(1 for c in all_caps if c["k7_classification"] == "free")
        guarded = sum(1 for c in all_caps if c["k7_classification"] == "guarded")
        restricted = sum(1 for c in all_caps if c["k7_classification"] == "restricted")
        available_services = sum(1 for s in services if s["status"] == "available")

        return {
            "total_capabilities": len(all_caps),
            "free": free,
            "guarded": guarded,
            "restricted": restricted,
            "external_services": len(services),
            "available_services": available_services,
            "categories": list(self.list_by_category().keys()),
        }

    def describe(self) -> str:
        """Human-readable summary."""
        summary = self.get_summary()
        lines = [
            f"Maria ma {summary['total_capabilities']} zdolnosci:",
            f"  {summary['free']} swobodnych, {summary['guarded']} nadzorowanych, "
            f"{summary['restricted']} ograniczonych",
            f"  {summary['available_services']}/{summary['external_services']} "
            f"serwisow zewnetrznych aktywnych",
        ]
        categories = self.list_by_category()
        for cat, caps in sorted(categories.items()):
            names = [c["name"] for c in caps]
            lines.append(f"  [{cat}] {', '.join(names)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    _CATEGORY_MAP = {
        "learning": "Nauka",
        "teacher": "Nauka",
        "meta": "Samoanaliza",
        "system": "System",
        "external": "Zewnetrzne",
        "web": "Internet",
        "monitoring": "Monitoring",
        "tuning": "Tuning",
        "validation": "Walidacja",
        "effector": "Efektory",
    }

    def _categorize(self, tags: tuple) -> str:
        for tag in tags:
            if tag in self._CATEGORY_MAP:
                return self._CATEGORY_MAP[tag]
        return "Inne"
