"""
Query Router for State-Grounded Operator Responses.

Rule-based detection of operator questions about Maria's state.
Zero LLM (ADR-013). Assigns ResponseMode that controls the answer pipeline.

When operator asks "co robisz?" or "jaki blad?" the router detects this
and sets mode to GROUNDED_STATUS or GROUNDED_ERROR, which triggers
the evidence collection + grounded response pipeline instead of
letting LLM hallucinate an answer.
"""

import re
from enum import Enum
from typing import Optional


class ResponseMode(Enum):
    """Controls how Maria answers the operator's question."""
    NORMAL = "normal"                       # Standard chat, no grounding
    GROUNDED_STATUS = "grounded_status"     # "co robisz", general status
    GROUNDED_ERROR = "grounded_error"       # "co za blad", anomalies
    GROUNDED_LEARNING = "grounded_learning" # "czego sie uczysz", learning
    GROUNDED_PLANNER = "grounded_planner"   # "jaki plan", strategy
    GROUNDED_KNOWLEDGE = "grounded_knowledge"  # "co wiesz o X", memory query


# Keyword patterns per mode (Polish + English).
# Order matters: more specific modes checked first.
# Patterns are lowercased substrings matched against lowercased message.
_MODE_PATTERNS = {
    ResponseMode.GROUNDED_ERROR: [
        "blad", "b\u0142\u0105d", "error", "nie dziala", "nie dzia\u0142a",
        "crash", "zapetla", "zap\u0119tla", "problem", "awaria",
        "failed", "co sie stalo", "co si\u0119 sta\u0142o",
        "co nie dziala", "co nie dzia\u0142a", "dlaczego nie",
        "co poszlo nie tak", "co posz\u0142o nie tak",
    ],
    ResponseMode.GROUNDED_LEARNING: [
        "nauka", "uczysz", "egzamin", "ile plikow", "ile plik\u00f3w",
        "chunki", "chunk", "retention", "wiedza",
        "ile sie nauczylam", "ile si\u0119 nauczy\u0142am",
        "czego sie uczysz", "czego si\u0119 uczysz",
        "jak ci idzie nauka", "jak idzie nauka",
        "co uczysz", "learning",
    ],
    ResponseMode.GROUNDED_PLANNER: [
        "plan ", "planer", "planner", "strategia", "cel ",
        "goal", "co dalej", "deliberation", "akcja",
        "jaki plan", "jaki cel", "jaka strategia",
        "nad czym pracujesz",
    ],
    ResponseMode.GROUNDED_KNOWLEDGE: [
        "co wiesz o", "co wiesz na temat",
        "co znasz", "znasz temat",
        "powiedz mi o", "opowiedz o", "opowiedz mi o",
        "what do you know about", "tell me about",
        "ile wiesz o", "jak dobrze znasz",
    ],
    ResponseMode.GROUNDED_STATUS: [
        "co robisz", "co teraz", "status", "jak ci idzie",
        "tryb", "mode", "health", "zdrowie",
        "jak sie czujesz", "jak si\u0119 czujesz",
        "co sie dzieje", "co si\u0119 dzieje",
        "jaki tryb", "jaki stan", "homeostasis",
        "what are you doing", "what's happening",
    ],
}


class OperationalQueryRouter:
    """
    Classifies operator messages into response modes.

    Rule-based keyword matching. No LLM calls.
    Returns ResponseMode.NORMAL for non-operational questions.
    """

    def classify(self, message: str) -> ResponseMode:
        """
        Classify operator message into a response mode.

        Checks more specific modes first (error > learning > planner > status).
        Returns NORMAL if no operational keywords detected.
        """
        if not message or not message.strip():
            return ResponseMode.NORMAL

        lower = message.lower().strip()

        # Short messages (< 3 chars) are not operational queries
        if len(lower) < 3:
            return ResponseMode.NORMAL

        # Check each mode's keywords (most specific first)
        for mode, keywords in _MODE_PATTERNS.items():
            for kw in keywords:
                if kw in lower:
                    return mode

        return ResponseMode.NORMAL

    @staticmethod
    def is_grounded(mode: ResponseMode) -> bool:
        """True if mode requires evidence-based response."""
        return mode != ResponseMode.NORMAL
