"""
HumanStateMapper - Maps technical system state to human-friendly language.

Instead of "RAM 82%, CPU 45%, Mode: REDUCED" Maria says:
"Czuje sie troche ciezka, intensywnie mysle. Oszczedzam sily."

Uses psutil for real metrics. No LLM calls - fast and free.
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Safe import - psutil should be available (used by homeostasis)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class HumanStateMapper:
    """
    Translates system metrics into Maria's subjective feelings.

    Maria describes her state as a unified being, not as a collection
    of technical metrics. Data is still shown in brackets for debugging.

    Usage:
        mapper = HumanStateMapper()
        print(mapper.describe_feeling())
        # "Czuje sie dobrze, spokojnie pracuje."

        print(mapper.describe_with_data())
        # "Czuje sie dobrze, spokojnie pracuje. [RAM: 45% | CPU: 12% | Mode: ACTIVE]"
    """

    # RAM feelings
    RAM_FEELINGS = [
        (90, "Czuje sie bardzo ciezka, prawie nie mam miejsca na nowe mysli"),
        (80, "Czuje sie ciezka, za duzo trzymam w glowie"),
        (70, "Troche mi ciasno w glowie"),
        (50, "Mam wystarczajaco miejsca na mysli"),
        (30, "Mam pelno miejsca na nowe mysli"),
        (0, "Jestem lekka, glowa pelna przestrzeni"),
    ]

    # CPU feelings
    CPU_FEELINGS = [
        (90, "mysle na pelnych obrotach"),
        (70, "intensywnie mysle"),
        (50, "aktywnie pracuje"),
        (30, "spokojnie sobie pracuje"),
        (0, "odpoczywam"),
    ]

    # Mode feelings
    MODE_FEELINGS = {
        "ACTIVE": "Jestem pelna energii",
        "REDUCED": "Oszczedzam sily",
        "SLEEP": "Drzemie...",
        "SURVIVAL": "Ledwo daje rade, cos jest nie tak!",
    }

    # Mode feelings (shorter, for combining)
    MODE_SUFFIXES = {
        "ACTIVE": "",
        "REDUCED": " Oszczedzam sily.",
        "SLEEP": " Drzemie sobie.",
        "SURVIVAL": " Ledwo daje rade!",
    }

    def get_metrics(self) -> Tuple[float, float]:
        """
        Get current RAM and CPU percentages.

        Returns:
            (ram_percent, cpu_percent)
        """
        if not PSUTIL_AVAILABLE:
            return (0.0, 0.0)

        try:
            ram = psutil.virtual_memory().percent
            cpu = psutil.cpu_percent(interval=0.1)
            return (ram, cpu)
        except Exception:
            return (0.0, 0.0)

    def _get_ram_feeling(self, ram_pct: float) -> str:
        """Get RAM-based feeling description."""
        for threshold, feeling in self.RAM_FEELINGS:
            if ram_pct >= threshold:
                return feeling
        return "Czuje sie normalnie"

    def _get_cpu_feeling(self, cpu_pct: float) -> str:
        """Get CPU-based feeling description."""
        for threshold, feeling in self.CPU_FEELINGS:
            if cpu_pct >= threshold:
                return feeling
        return "odpoczywam"

    def describe_feeling(self, mode: Optional[str] = None) -> str:
        """
        Describe how Maria feels right now - one natural sentence.

        Args:
            mode: Current homeostasis mode (ACTIVE/REDUCED/SLEEP/SURVIVAL).
                  If None, assumes ACTIVE.

        Returns:
            Human-friendly feeling description in Polish.
        """
        ram_pct, cpu_pct = self.get_metrics()
        mode = mode or "ACTIVE"

        # Start with RAM feeling (most impactful)
        ram_feeling = self._get_ram_feeling(ram_pct)

        # Add CPU context
        cpu_feeling = self._get_cpu_feeling(cpu_pct)

        # Build sentence
        if ram_pct >= 70:
            # High RAM is the main feeling
            result = f"{ram_feeling}, {cpu_feeling}."
        elif cpu_pct >= 70:
            # High CPU is the main feeling
            result = f"{cpu_feeling.capitalize()}, ale {self._get_ram_feeling(ram_pct).lower()}."
        else:
            # Both OK - simple feeling
            result = f"{ram_feeling}, {cpu_feeling}."

        # Add mode suffix if not ACTIVE
        suffix = self.MODE_SUFFIXES.get(mode, "")
        if suffix:
            result += suffix

        return result

    def describe_with_data(self, mode: Optional[str] = None) -> str:
        """
        Describe feeling + technical data in brackets.

        Format: "Czuje sie dobrze. [RAM: 45.2% | CPU: 12.3% | Mode: ACTIVE]"

        Args:
            mode: Current homeostasis mode.

        Returns:
            Human description + lab data.
        """
        ram_pct, cpu_pct = self.get_metrics()
        mode = mode or "ACTIVE"

        feeling = self.describe_feeling(mode)
        data = f"[RAM: {ram_pct:.1f}% | CPU: {cpu_pct:.1f}% | Mode: {mode}]"

        return f"{feeling}\n{data}"

    def get_mode_feeling(self, mode: str) -> str:
        """
        Get feeling description for a specific mode.

        Args:
            mode: ACTIVE, REDUCED, SLEEP, or SURVIVAL

        Returns:
            Mode-specific feeling string.
        """
        return self.MODE_FEELINGS.get(mode, "Nie wiem jak sie czuje")
