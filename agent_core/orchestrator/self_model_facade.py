"""
UserFacingSelfModel (V3 Phase A, Module 3)

User-facing aggregation of Maria's self-model: identity, personality,
capabilities, awareness, and current state - all in one place.

Wraps existing V2 components (SelfModelBuilder, CapabilityRouter,
ContextBuilder, IdentityStore, HomeostasisCore). Does NOT rewrite them.

Usage:
    model = UserFacingSelfModel(ctx)
    status = model.get_status()       # Full dashboard dict
    desc = model.describe_self()      # Chatty self-description
    caps = model.get_capabilities()   # Grouped capability list
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Capability tag grouping for user-facing display
_TAG_GROUPS = {
    "learning": "Nauka",
    "meta": "Samoanaliza",
    "system": "System",
    "external": "Zewnetrzne",
    "web": "Internet",
    "monitoring": "Monitoring",
    "tuning": "Tuning",
    "validation": "Walidacja",
}

# Mode descriptions in Polish
_MODE_LABELS = {
    "ACTIVE": "aktywna",
    "REDUCED": "ograniczona",
    "SLEEP": "uspiona",
    "SURVIVAL": "tryb awaryjny",
}


class UserFacingSelfModel:
    """User-facing self-model - combines consciousness + capabilities + awareness."""

    def __init__(self, ctx):
        """
        Initialize from SharedContext.

        All dependencies are read lazily from ctx so that this object
        can be created early (before all modules finish init).

        Args:
            ctx: SharedContext instance
        """
        self._ctx = ctx

    # ------------------------------------------------------------------
    # Core identity (from consciousness)
    # ------------------------------------------------------------------

    def _get_consciousness(self):
        return self._ctx.consciousness

    def _get_identity(self):
        return self._ctx.identity_store

    def _get_capability_router(self):
        return getattr(self._ctx, "capability_router", None)

    def _get_homeostasis(self):
        return self._ctx.homeostasis_core

    def _get_context_builder(self):
        return getattr(self._ctx, "context_builder", None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_identity(self) -> Dict[str, Any]:
        """
        Core identity data: name, purpose, session, uptime.

        Returns:
            Dict with identity fields or minimal fallback.
        """
        result = {
            "name": "Maria",
            "full_name": "M.A.R.I.A.",
            "expanded": "Meta Analysis Recalibration Intelligence Architecture",
            "purpose": "autonomiczna nauka z plikow tekstowych",
        }

        identity = self._get_identity()
        if identity:
            id_dict = identity.get_identity_dict()
            result.update({
                "session_count": id_dict.get("session_count", 0),
                "total_uptime_hours": id_dict.get("total_uptime_hours", 0),
                "birth_date": id_dict.get("birth_date", ""),
                "age_string": id_dict.get("age_string", ""),
                "primary_user": id_dict.get("primary_user", "Eryk"),
                "last_session_summary": id_dict.get("last_session_summary", ""),
            })

        return result

    def get_personality(self) -> Dict[str, Any]:
        """
        Personality traits with scores.

        Returns:
            Dict with 'traits' list and 'trait_scores' dict.
        """
        consciousness = self._get_consciousness()
        if not consciousness:
            return {"traits": [], "trait_scores": {}}

        self_model = consciousness.self_model
        return {
            "traits": self_model.get_traits(),
            "trait_scores": self_model.get_trait_scores(),
        }

    def get_capabilities(self, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List registered capabilities, optionally filtered by tag.

        Args:
            tag: Filter by tag (e.g. 'learning', 'meta', 'external')

        Returns:
            List of capability dicts with name, description, tags, classification.
        """
        router = self._get_capability_router()
        if not router:
            return []

        specs = router.list_capabilities()
        if tag:
            specs = [s for s in specs if tag in s.tags]

        return [
            {
                "name": s.name,
                "description": s.description,
                "tags": list(s.tags),
                "k7_classification": s.k7_classification,
                "available": router.is_available(s.name),
            }
            for s in specs
        ]

    def get_capabilities_grouped(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Capabilities grouped by tag for UI display.

        Returns:
            Dict mapping group label -> list of capability dicts.
        """
        all_caps = self.get_capabilities()
        groups: Dict[str, List[Dict[str, Any]]] = {}

        for cap in all_caps:
            placed = False
            for tag in cap["tags"]:
                label = _TAG_GROUPS.get(tag)
                if label:
                    groups.setdefault(label, []).append(cap)
                    placed = True
                    break
            if not placed:
                groups.setdefault("Inne", []).append(cap)

        return groups

    def get_awareness(self) -> Dict[str, Any]:
        """
        Current awareness: learning status, system metrics.

        Returns:
            Dict with learning_status, knowledge_tags, system fields.
        """
        result: Dict[str, Any] = {}

        builder = self._get_context_builder()
        if builder:
            # File counts from knowledge index
            files = builder.get_detailed_file_list()
            if files:
                by_status: Dict[str, int] = {}
                for f in files:
                    st = f.get("status", "other")
                    by_status[st] = by_status.get(st, 0) + 1
                result["files_total"] = len(files)
                result["files_by_status"] = by_status
            else:
                result["files_total"] = 0
                result["files_by_status"] = {}

            # Input files waiting
            input_files = builder.get_input_files()
            result["input_files_count"] = len(input_files)

        return result

    def get_current_mode(self) -> str:
        """
        Current homeostasis mode.

        Returns:
            Mode string (ACTIVE, REDUCED, SLEEP, SURVIVAL) or 'UNKNOWN'.
        """
        core = self._get_homeostasis()
        if core:
            mode = getattr(core, "_current_mode", None)
            if mode:
                return str(mode.name) if hasattr(mode, "name") else str(mode)
        return "UNKNOWN"

    def get_limitations(self) -> List[str]:
        """
        Known limitations as a list of strings.

        Returns:
            List of limitation descriptions in Polish.
        """
        base = [
            "Model LLM: llama3.1:8b (lokalne przetwarzanie)",
            "Brak stalego dostepu do internetu",
            "Nauka tylko z plikow tekstowych (input/)",
        ]

        # Check OpenClaw availability
        if not self._ctx.openclaw_client:
            base.append("OpenClaw efektor niedostepny")

        # Check NIM availability
        try:
            from agent_core.llm.nim_client import NIMClient
            nim = NIMClient()
            if not nim.is_available():
                base.append("NIM API niedostepne (brak zewnetrznego LLM)")
        except Exception:
            pass

        return base

    def get_status(self) -> Dict[str, Any]:
        """
        Complete status dump for dashboard / onboarding.

        Aggregates identity, personality, capabilities, awareness,
        limitations, and current mode into one dict.

        Returns:
            Full status dict.
        """
        return {
            "identity": self.get_identity(),
            "personality": self.get_personality(),
            "capabilities": self.get_capabilities(),
            "capabilities_grouped": self.get_capabilities_grouped(),
            "awareness": self.get_awareness(),
            "limitations": self.get_limitations(),
            "mode": self.get_current_mode(),
            "mode_label": _MODE_LABELS.get(self.get_current_mode(), "nieznany"),
        }

    def describe_self(self) -> str:
        """
        Chatty self-description including current state.

        Suitable for chat responses to "kim jestes?" or onboarding intro.

        Returns:
            Multi-line Polish self-description.
        """
        identity = self.get_identity()
        personality = self.get_personality()
        caps = self.get_capabilities()
        awareness = self.get_awareness()
        mode = self.get_current_mode()

        lines = []

        # Who am I
        lines.append(
            f"Jestem {identity['name']} ({identity['full_name']}) - "
            f"{identity.get('expanded', '')}."
        )
        lines.append(f"Moj cel: {identity['purpose']}.")

        # Personality
        traits = personality.get("traits", [])
        if traits:
            lines.append(f"Moje cechy: {', '.join(traits[:5])}.")

        # Age & session
        age = identity.get("age_string")
        session = identity.get("session_count")
        if age and session:
            lines.append(f"Mam {age}, to moja {session}. sesja.")

        # Capabilities count
        if caps:
            free = sum(1 for c in caps if c["k7_classification"] == "free")
            guarded = sum(1 for c in caps if c["k7_classification"] == "guarded")
            lines.append(
                f"Mam {len(caps)} zdolnosci ({free} swobodnych, "
                f"{guarded} wymagajacych nadzoru)."
            )

        # Learning awareness
        files_total = awareness.get("files_total", 0)
        if files_total > 0:
            by_status = awareness.get("files_by_status", {})
            learned = by_status.get("learned", 0) + by_status.get("completed", 0)
            lines.append(f"Mam {files_total} plikow w bazie ({learned} nauczonych).")

        # Mode
        mode_label = _MODE_LABELS.get(mode, mode)
        lines.append(f"Stan: {mode_label}.")

        return "\n".join(lines)

    def describe_capabilities_text(self) -> str:
        """
        Human-readable capabilities list grouped by category.

        Returns:
            Multi-line Polish text.
        """
        grouped = self.get_capabilities_grouped()
        if not grouped:
            return "Brak zarejestrowanych zdolnosci."

        lines = ["Moje zdolnosci:"]
        for group_label, caps in sorted(grouped.items()):
            lines.append(f"\n  [{group_label}]")
            for cap in caps:
                classification = cap["k7_classification"].upper()
                lines.append(f"    {cap['name']}: {cap['description']} [{classification}]")

        return "\n".join(lines)

    def get_system_prompt_context(self) -> str:
        """
        Compact self-model context for LLM system prompt.

        Shorter than describe_self(), focused on what the LLM needs
        to know to respond in character.

        Returns:
            Compact string for system prompt injection.
        """
        identity = self.get_identity()
        personality = self.get_personality()

        parts = [
            f"Jestes {identity['name']} ({identity['full_name']}).",
            f"Cel: {identity['purpose']}.",
        ]

        traits = personality.get("traits", [])
        if traits:
            parts.append(f"Cechy: {', '.join(traits[:5])}.")

        caps = self.get_capabilities()
        if caps:
            cap_names = [c["name"] for c in caps if c["k7_classification"] != "forbidden"]
            parts.append(f"Umiesz: {', '.join(cap_names[:8])}.")

        limitations = self.get_limitations()
        if limitations:
            parts.append(f"Ograniczenia: {'; '.join(limitations[:3])}.")

        mode = self.get_current_mode()
        mode_label = _MODE_LABELS.get(mode, mode)
        parts.append(f"Stan: {mode_label}.")

        return " ".join(parts)
