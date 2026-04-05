"""
OnboardingFlow (V3 Phase A, Module 2)

First-run guidance for new users. Walks through Maria's identity,
capabilities, learning workflow, and preferences.

Detection: checks IdentityStore for 'onboarding_completed' flag.
Persistence: saves flag + preferences to IdentityStore.

Designed for both REPL (text) and Web UI (data dict) consumption.

Usage:
    flow = OnboardingFlow(ctx, self_model)
    if flow.should_run():
        result = flow.run()          # REPL interactive
        # or
        steps = flow.get_steps()     # Web UI data
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Available autonomy presets
AUTONOMY_PRESETS = {
    "low": {
        "label": "Ostrozna",
        "description": "Potrzebuje zatwierdzenia dla wiekszosci dzialan",
        "authority_level": "OBSERVE",
    },
    "medium": {
        "label": "Zrownowazana",
        "description": "Ucze sie sama, pytam o wazne decyzje",
        "authority_level": "SUGGEST",
    },
    "high": {
        "label": "Autonomiczna",
        "description": "Dzialaj samodzielnie, informuj o wynikach",
        "authority_level": "CONFIRM",
    },
}


class OnboardingStep:
    """Single step in the onboarding flow."""

    __slots__ = ("key", "title", "content", "data", "completed")

    def __init__(self, key: str, title: str, content: str, data: Optional[Dict] = None):
        self.key = key
        self.title = title
        self.content = content
        self.data = data or {}
        self.completed = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "content": self.content,
            "data": self.data,
            "completed": self.completed,
        }


class OnboardingFlow:
    """First-run onboarding flow for Maria."""

    # Identity store key for onboarding state
    _ONBOARDING_KEY = "onboarding_completed"
    _PREFERENCES_KEY = "onboarding_preferences"

    def __init__(self, ctx, self_model):
        """
        Initialize onboarding flow.

        Args:
            ctx: SharedContext instance
            self_model: UserFacingSelfModel instance (Module 3)
        """
        self._ctx = ctx
        self._self_model = self_model
        self._steps: Optional[List[OnboardingStep]] = None

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def should_run(self) -> bool:
        """
        Check if onboarding should run (first launch).

        Returns:
            True if onboarding has not been completed yet.
        """
        identity = self._ctx.identity_store
        if not identity:
            return True

        data = getattr(identity, "_data", {})
        return not data.get(self._ONBOARDING_KEY, False)

    def is_completed(self) -> bool:
        """Check if onboarding was already completed."""
        return not self.should_run()

    # ------------------------------------------------------------------
    # Step builders
    # ------------------------------------------------------------------

    def _build_steps(self) -> List[OnboardingStep]:
        """Build all onboarding steps with current data."""
        return [
            self._step_introduction(),
            self._step_capabilities(),
            self._step_learning(),
            self._step_limitations(),
            self._step_ready(),
        ]

    def _step_introduction(self) -> OnboardingStep:
        """Step 1: Who is Maria?"""
        identity = self._self_model.get_identity()
        personality = self._self_model.get_personality()

        content_lines = [
            f"Jestem {identity['name']} ({identity['full_name']}).",
            f"{identity.get('expanded', '')}.",
            "",
            f"Moj cel: {identity['purpose']}.",
        ]

        traits = personality.get("traits", [])
        if traits:
            content_lines.append(f"Moje cechy osobowosci: {', '.join(traits)}.")

        age = identity.get("age_string")
        session = identity.get("session_count")
        if age:
            content_lines.append(f"Mam {age}.")
        if session:
            content_lines.append(f"To moja {session}. sesja.")

        return OnboardingStep(
            key="introduction",
            title="Kim jestem?",
            content="\n".join(content_lines),
            data={"identity": identity, "personality": personality},
        )

    def _step_capabilities(self) -> OnboardingStep:
        """Step 2: What can Maria do?"""
        grouped = self._self_model.get_capabilities_grouped()
        all_caps = self._self_model.get_capabilities()

        content_lines = [
            f"Mam {len(all_caps)} zarejestrowanych zdolnosci:",
        ]

        for group_label, caps in sorted(grouped.items()):
            cap_names = [c["name"] for c in caps]
            content_lines.append(f"  {group_label}: {', '.join(cap_names)}")

        content_lines.append("")
        free = sum(1 for c in all_caps if c["k7_classification"] == "free")
        guarded = sum(1 for c in all_caps if c["k7_classification"] == "guarded")
        restricted = sum(1 for c in all_caps if c["k7_classification"] == "restricted")
        content_lines.append(
            f"Klasyfikacja autonomii: {free} swobodnych, "
            f"{guarded} nadzorowanych, {restricted} ograniczonych."
        )

        return OnboardingStep(
            key="capabilities",
            title="Co potrafie?",
            content="\n".join(content_lines),
            data={"capabilities_grouped": grouped, "total": len(all_caps)},
        )

    def _step_learning(self) -> OnboardingStep:
        """Step 3: How does learning work?"""
        awareness = self._self_model.get_awareness()

        content_lines = [
            "Ucze sie autonomicznie z plikow tekstowych w folderze input/.",
            "",
            "Proces nauki:",
            "  1. Pliki trafiaja do input/ (reczny upload lub web fetch)",
            "  2. Dziele tekst na fragmenty (chunki)",
            "  3. Ucze sie kazdego fragmentu (LLM ekstrakcja wiedzy)",
            "  4. Sprawdzam sie egzaminami (spaced repetition)",
            "  5. Buduje graf wiedzy z polaczeniami",
            "",
        ]

        files_total = awareness.get("files_total", 0)
        if files_total > 0:
            by_status = awareness.get("files_by_status", {})
            learned = by_status.get("learned", 0) + by_status.get("completed", 0)
            content_lines.append(
                f"Aktualnie: {files_total} plikow w bazie, {learned} nauczonych."
            )
        else:
            content_lines.append(
                "Baza wiedzy jest pusta. Wrzuc pliki .txt do input/ aby zaczac nauke."
            )

        input_count = awareness.get("input_files_count", 0)
        if input_count > 0:
            content_lines.append(f"Plikow w input/: {input_count}")

        return OnboardingStep(
            key="learning",
            title="Jak sie ucze?",
            content="\n".join(content_lines),
            data={"awareness": awareness},
        )

    def _step_limitations(self) -> OnboardingStep:
        """Step 4: What are the limitations?"""
        limitations = self._self_model.get_limitations()

        content_lines = [
            "Wazne ograniczenia, o ktorych warto wiedziec:",
            "",
        ]
        for i, lim in enumerate(limitations, 1):
            content_lines.append(f"  {i}. {lim}")

        content_lines.extend([
            "",
            "Dzialanie: offline-first, lokalne LLM (Ollama).",
            "Komunikacja: Telegram (@ClawBot) lub Web UI.",
        ])

        return OnboardingStep(
            key="limitations",
            title="Moje ograniczenia",
            content="\n".join(content_lines),
            data={"limitations": limitations},
        )

    def _step_ready(self) -> OnboardingStep:
        """Step 5: Ready to begin!"""
        mode = self._self_model.get_current_mode()
        mode_label = self._self_model.get_status().get("mode_label", mode)

        content_lines = [
            f"Stan: {mode_label}.",
            "",
            "Dostepne poziomy autonomii:",
        ]

        for key, preset in AUTONOMY_PRESETS.items():
            content_lines.append(
                f"  [{key}] {preset['label']}: {preset['description']}"
            )

        content_lines.extend([
            "",
            "Mozesz zmienic poziom autonomii pozniej komenda /authority.",
            "",
            "Jestem gotowa do pracy!",
        ])

        return OnboardingStep(
            key="ready",
            title="Gotowa!",
            content="\n".join(content_lines),
            data={
                "mode": mode,
                "autonomy_presets": AUTONOMY_PRESETS,
            },
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def get_steps(self) -> List[Dict[str, Any]]:
        """
        Get all onboarding steps as dicts (for Web UI).

        Returns:
            List of step dicts.
        """
        self._steps = self._build_steps()
        return [s.to_dict() for s in self._steps]

    def get_step(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get a single step by key.

        Args:
            key: Step key (introduction, capabilities, learning, limitations, ready)

        Returns:
            Step dict or None.
        """
        if self._steps is None:
            self._steps = self._build_steps()

        for step in self._steps:
            if step.key == key:
                return step.to_dict()
        return None

    def run(self) -> Dict[str, Any]:
        """
        Run the full onboarding flow (text output for REPL).

        Prints each step and returns summary.
        Does NOT require user interaction - just informational.

        Returns:
            Dict with steps shown and completion status.
        """
        steps = self._build_steps()
        output_lines = []

        output_lines.append("")
        output_lines.append("=" * 50)
        output_lines.append("  Witaj! Jestem M.A.R.I.A.")
        output_lines.append("  Oto krotkie wprowadzenie.")
        output_lines.append("=" * 50)

        for i, step in enumerate(steps, 1):
            output_lines.append("")
            output_lines.append(f"--- [{i}/{len(steps)}] {step.title} ---")
            output_lines.append(step.content)
            step.completed = True

        output_lines.append("")
        output_lines.append("=" * 50)
        output_lines.append("  Onboarding zakonczony. Milej pracy!")
        output_lines.append("=" * 50)
        output_lines.append("")

        text = "\n".join(output_lines)

        # Mark as completed
        self.mark_completed()

        return {
            "text": text,
            "steps_count": len(steps),
            "completed": True,
        }

    def mark_completed(self, preferences: Optional[Dict] = None) -> None:
        """
        Mark onboarding as completed in IdentityStore.

        Args:
            preferences: Optional user preferences from onboarding.
        """
        identity = self._ctx.identity_store
        if not identity:
            logger.warning("No IdentityStore - cannot persist onboarding state")
            return

        data = getattr(identity, "_data", {})
        data[self._ONBOARDING_KEY] = True
        if preferences:
            data[self._PREFERENCES_KEY] = preferences

        # Persist
        try:
            identity._save()
        except Exception as e:
            logger.warning(f"Failed to save onboarding state: {e}")

    def reset(self) -> None:
        """
        Reset onboarding (for testing or re-onboarding).

        Clears the completed flag so should_run() returns True again.
        """
        identity = self._ctx.identity_store
        if not identity:
            return

        data = getattr(identity, "_data", {})
        data.pop(self._ONBOARDING_KEY, None)
        data.pop(self._PREFERENCES_KEY, None)

        try:
            identity._save()
        except Exception:
            pass
