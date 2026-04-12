"""
CapabilityManifest (K15) - Auto-generated manifest of what Maria can do.

Aggregates data from:
- CapabilityRouter (registered action handlers)
- SharedContext (which subsystems are actually available)
- Homeostasis mode (what's allowed right now)

Provides honest answers to "co umiesz?" with confidence levels.
Never claims capabilities that aren't verified.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CapabilityEntry:
    """A single capability with status and confidence."""

    name: str
    description: str
    available: bool  # handler registered AND subsystems present
    confidence: float  # 0.0-1.0, how well this works
    classification: str  # free/guarded/restricted/forbidden
    tags: tuple = ()
    reason_unavailable: str = ""  # why it's not available

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "description": self.description,
            "available": self.available,
            "confidence": self.confidence,
            "classification": self.classification,
            "tags": list(self.tags),
        }
        if self.reason_unavailable:
            d["reason_unavailable"] = self.reason_unavailable
        return d


@dataclass
class Limitation:
    """A known limitation of the system."""

    category: str  # hardware, software, autonomy, knowledge
    description: str
    severity: str = "info"  # info, warning, blocking

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "description": self.description,
            "severity": self.severity,
        }


class CapabilityManifest:
    """
    Auto-generated manifest of Maria's capabilities and limitations.

    Updates on demand - not cached, always reflects current state.
    """

    def __init__(self):
        self._capability_router = None
        self._ctx = None
        self._mode_fn = None

    def set_capability_router(self, router) -> None:
        self._capability_router = router

    def set_context(self, ctx) -> None:
        """Set SharedContext for subsystem availability checks."""
        self._ctx = ctx

    def set_mode_fn(self, fn) -> None:
        """Set function that returns current homeostasis mode."""
        self._mode_fn = fn

    def get_capabilities(self) -> List[CapabilityEntry]:
        """Get all capabilities with availability status."""
        entries = []

        if not self._capability_router:
            return entries

        specs = getattr(self._capability_router, '_specs', {})
        handlers = getattr(self._capability_router, '_handlers', {})

        for name, spec in specs.items():
            has_handler = name in handlers
            subsystems_ok, missing = self._check_subsystems(
                spec.required_subsystems
            )

            available = has_handler and subsystems_ok
            reason = ""
            if not has_handler:
                reason = "brak handlera"
            elif not subsystems_ok:
                reason = f"brak: {', '.join(missing)}"

            # Confidence based on classification and availability
            confidence = self._estimate_confidence(name, available, spec)

            entries.append(CapabilityEntry(
                name=name,
                description=spec.description,
                available=available,
                confidence=confidence,
                classification=spec.k7_classification,
                tags=spec.tags,
                reason_unavailable=reason,
            ))

        return sorted(entries, key=lambda e: (not e.available, e.name))

    def get_available(self) -> List[CapabilityEntry]:
        """Get only available capabilities."""
        return [c for c in self.get_capabilities() if c.available]

    def get_unavailable(self) -> List[CapabilityEntry]:
        """Get capabilities that are NOT available."""
        return [c for c in self.get_capabilities() if not c.available]

    def get_limitations(self) -> List[Limitation]:
        """Get known system limitations."""
        limitations = []

        # Hardware
        limitations.append(Limitation(
            category="hardware",
            description="32GB RAM - max 1 heavy model at a time (mutex)",
            severity="info",
        ))
        limitations.append(Limitation(
            category="hardware",
            description="Brak GPU - LLM inference on CPU only (slow)",
            severity="warning",
        ))

        # Mode-based
        mode = self._get_mode()
        if mode and mode != "ACTIVE":
            limitations.append(Limitation(
                category="software",
                description=f"Tryb {mode} - ograniczone dzialania",
                severity="warning",
            ))

        # Network
        limitations.append(Limitation(
            category="software",
            description="Brak dostepu do email, kalendarza, smart home",
            severity="info",
        ))

        # Autonomy
        limitations.append(Limitation(
            category="autonomy",
            description="Domyslny poziom: OBSERVE - nie wykonuje akcji bez approval",
            severity="info",
        ))

        # Knowledge
        limitations.append(Limitation(
            category="knowledge",
            description="Ucze sie tylko z plikow txt w input/ i Wikipedia PL",
            severity="info",
        ))

        return limitations

    def can_do(self, action_name: str) -> bool:
        """Quick check: can Maria do this action right now?"""
        for cap in self.get_capabilities():
            if cap.name == action_name:
                return cap.available
        return False

    def get_summary(self) -> str:
        """Human-readable summary for /profile or chat."""
        caps = self.get_capabilities()
        available = [c for c in caps if c.available]
        unavailable = [c for c in caps if not c.available]

        lines = [f"*Moje mozliwosci ({len(available)}/{len(caps)}):*", ""]

        if available:
            for c in available:
                conf_str = f" ({c.confidence:.0%})" if c.confidence < 1.0 else ""
                cls_icon = {"free": "", "guarded": " [G]", "restricted": " [R]"}.get(
                    c.classification, ""
                )
                lines.append(f"  + {c.description}{cls_icon}{conf_str}")

        if unavailable:
            lines.append(f"\n*Niedostepne ({len(unavailable)}):*")
            for c in unavailable:
                lines.append(f"  - {c.description}: {c.reason_unavailable}")

        # Limitations
        limits = self.get_limitations()
        if limits:
            lines.append("\n*Ograniczenia:*")
            for lim in limits:
                sev = {"warning": "!", "blocking": "!!"}.get(lim.severity, "")
                lines.append(f"  {sev} {lim.description}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Full manifest as dict (for API)."""
        return {
            "capabilities": [c.to_dict() for c in self.get_capabilities()],
            "limitations": [l.to_dict() for l in self.get_limitations()],
            "available_count": len(self.get_available()),
            "total_count": len(self.get_capabilities()),
            "mode": self._get_mode(),
            "generated_at": datetime.now().isoformat(),
        }

    # ── Internal ─────────────────────────────────────────────

    def _check_subsystems(self, required: tuple) -> tuple:
        """Check if required subsystems are available in SharedContext."""
        if not self._ctx or not required:
            return True, []

        missing = []
        for sub in required:
            val = getattr(self._ctx, sub, None)
            if val is None:
                missing.append(sub)
        return len(missing) == 0, missing

    def _get_mode(self) -> str:
        if self._mode_fn:
            try:
                return str(self._mode_fn())
            except Exception:
                pass
        return "UNKNOWN"

    @staticmethod
    def _estimate_confidence(
        name: str, available: bool, spec
    ) -> float:
        """Estimate confidence for a capability."""
        if not available:
            return 0.0

        # Internal, well-tested capabilities
        high_confidence = {
            "learn", "exam", "review", "evaluate",
            "noop", "maintenance", "self_analyze",
            "creative", "critique",
        }
        if name in high_confidence:
            return 0.95

        # External dependencies (network, API)
        medium_confidence = {"fetch", "validate", "ask_expert"}
        if name in medium_confidence:
            return 0.7

        # Risky / external execution
        low_confidence = {"effector", "experiment"}
        if name in low_confidence:
            return 0.5

        return 0.8
