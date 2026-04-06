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
    GROUNDED_VISION = "grounded_vision"        # "co widzisz", visual perception
    GROUNDED_IDENTITY = "grounded_identity"    # "kim jestes", "opisz siebie", self-description


# Keyword patterns per mode (Polish + English).
# Order matters: more specific modes checked first.
# Patterns are lowercased substrings matched against lowercased message.
_MODE_PATTERNS = {
    ResponseMode.GROUNDED_VISION: [
        "co widzisz", "co widzi", "co widac",
        "co wida\u0107",  # co widać
        "obraz", "kamera", "oko", "wzrok",
        "what do you see", "what can you see",
        "jak wyglada", "jak wygl\u0105da",
        "opisz co widzisz", "pokaz co widzisz",
        "poka\u017c co widzisz",
        "widzisz co", "widzisz cos",
    ],
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
        "braki", "luki", "czego nie wiesz", "co ci brakuje",
        "czego brakuje", "czego nie umiesz",
        "co powinnas", "co powinna\u015b",
        "slabe strony", "s\u0142abe strony",
        "gaps", "what don't you know",
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
    ResponseMode.GROUNDED_IDENTITY: [
        "kim jestes", "kim jeste\u015b", "czym jestes", "czym jeste\u015b",
        "opisz siebie", "opisz mi siebie", "opowiedz o sobie",
        "co potrafisz", "co umiesz", "jakie masz mozliwosci",
        "jakie masz mo\u017cliwo\u015bci",
        "jak jestes zbudowana", "jak jeste\u015b zbudowana",
        "jaka jest twoja architektura", "twoja architektura",
        "z czego sie skladasz", "z czego si\u0119 sk\u0142adasz",
        "jak dzialasz", "jak dzia\u0142asz",
        "przedstaw sie", "przedstaw si\u0119",
        "who are you", "what can you do",
        "describe yourself", "your architecture",
        "co masz", "jakie moduly",
        "w jakim kierunku", "kierunek rozwoju",
        "twoje ograniczenia", "twoje limity",
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
