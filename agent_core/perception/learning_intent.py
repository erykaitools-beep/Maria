"""Detect learning intent from user messages.

Rule-based intent extraction - zero LLM. Recognizes Polish and English
phrases that indicate the user wants Maria to learn about a topic.

Usage:
    intent = detect_learning_intent("Naucz sie o fizyce kwantowej")
    if intent:
        print(intent["topic"])   # "fizyce kwantowej"
        print(intent["action"])  # "learn"
"""

import re
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Polish learning request patterns
# Each tuple: (compiled regex, action type)
# action: "learn" = study topic, "fetch" = download material, "explore" = broad exploration
_PL_PATTERNS = [
    # Direct commands
    (re.compile(r"(?:naucz|ucz)\s+si[eę]\s+(?:o\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"poczytaj\s+(?:o\s+|na\s+temat\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"dowiedz\s+si[eę]\s+(?:o\s+|czegos\s+o\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"przeczytaj\s+(?:o\s+|na\s+temat\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"poznaj\s+(?:temat\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"zg[lł][eę]b\s+(?:temat\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"zbadaj\s+(?:temat\s+)?(.+)", re.IGNORECASE), "explore"),
    # Fetch/download patterns
    (re.compile(r"(?:znajd[zź]|poszukaj|pobierz)\s+(?:materialy?\s+)?(?:o\s+|na\s+temat\s+)?(.+)", re.IGNORECASE), "fetch"),
    (re.compile(r"(?:sciagnij|[sś]ci[aą]gnij)\s+(?:o\s+|na\s+temat\s+)?(.+)", re.IGNORECASE), "fetch"),
    # Interest expressions
    (re.compile(r"interesuje\s+(?:mnie|mne)\s+(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"chc[eę]\s+(?:[zż]eby[sś]?\s+)?(?:si[eę]\s+)?(?:nauczy[lł]a|dowiedzia[lł]a|poczyta[lł]a)\s+(?:o\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"mo[zż]esz\s+(?:si[eę]\s+)?(?:nauczy[cć]|poczyta[cć]|dowiedzie[cć])\s+(?:o\s+)?(.+)", re.IGNORECASE), "learn"),
]

# English patterns (basic)
_EN_PATTERNS = [
    (re.compile(r"learn\s+(?:about\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"read\s+(?:about\s+)?(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"study\s+(.+)", re.IGNORECASE), "learn"),
    (re.compile(r"find\s+(?:materials?\s+)?(?:about\s+|on\s+)?(.+)", re.IGNORECASE), "fetch"),
    (re.compile(r"fetch\s+(?:articles?\s+)?(?:about\s+|on\s+)?(.+)", re.IGNORECASE), "fetch"),
]

# Cancellation patterns (Polish + English)
_CANCEL_PATTERNS = [
    (re.compile(r"(?:zapomnij|olej|anuluj|przerwij|zrezygnuj)\s+(?:z\s+)?(?:nauk[ieę]\s+(?:o\s+)?|temat(?:u)?\s+)?(.+)", re.IGNORECASE), "cancel"),
    (re.compile(r"nie\s+ucz\s+si[eę]\s+(?:o\s+)?(.+)", re.IGNORECASE), "cancel"),
    (re.compile(r"przesta[nń]\s+(?:si[eę]\s+)?uczy[cć]\s+(?:o\s+)?(.+)", re.IGNORECASE), "cancel"),
    (re.compile(r"(?:cancel|stop|forget)\s+(?:learning\s+)?(?:about\s+)?(.+)", re.IGNORECASE), "cancel"),
]

# Topic cleanup: remove trailing punctuation, articles, etc.
_TOPIC_CLEANUP = re.compile(r'[.!?;,]+$')
_TOPIC_MIN_LEN = 2
_TOPIC_MAX_LEN = 100


def detect_learning_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detect learning intent from user text.

    Args:
        text: User message text.

    Returns:
        Dict with keys: topic, action, confidence, pattern
        Or None if no learning intent detected.
    """
    if not text or len(text) < 5:
        return None

    text = text.strip()

    # Try Polish patterns first
    for pattern, action in _PL_PATTERNS:
        match = pattern.search(text)
        if match:
            topic = _clean_topic(match.group(1))
            if topic:
                return {
                    "topic": topic,
                    "action": action,
                    "confidence": 0.9,
                    "language": "pl",
                }

    # Try English patterns
    for pattern, action in _EN_PATTERNS:
        match = pattern.search(text)
        if match:
            topic = _clean_topic(match.group(1))
            if topic:
                return {
                    "topic": topic,
                    "action": action,
                    "confidence": 0.8,
                    "language": "en",
                }

    return None


def detect_cancel_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detect intent to cancel learning about a topic.

    Args:
        text: User message text.

    Returns:
        Dict with keys: topic, action ("cancel"), confidence
        Or None if no cancel intent detected.
    """
    if not text or len(text) < 5:
        return None

    text = text.strip()

    for pattern, action in _CANCEL_PATTERNS:
        match = pattern.search(text)
        if match:
            topic = _clean_topic(match.group(1))
            if topic:
                return {
                    "topic": topic,
                    "action": action,
                    "confidence": 0.85,
                }

    return None


# Operational command patterns (Polish + English)
# These trigger planner actions directly, not learning goals
_OP_PATTERNS = [
    # Fetch / download
    (re.compile(r"(?:zrob|zr[oó]b)\s+fetch", re.IGNORECASE), "fetch", None),
    (re.compile(r"pobierz\s+(?:nowe\s+)?materia[lł]y", re.IGNORECASE), "fetch", None),
    (re.compile(r"(?:sciagnij|[sś]ci[aą]gnij)\s+(?:nowe\s+)?(?:artyku[lł]y|materia[lł]y)", re.IGNORECASE), "fetch", None),
    (re.compile(r"fetch\s+(?:new\s+)?(?:materials?|articles?)", re.IGNORECASE), "fetch", None),
    # Evaluate
    (re.compile(r"(?:zrob|zr[oó]b)\s+(?:ewaluacj[eę]|ocen[eę])", re.IGNORECASE), "evaluate", None),
    (re.compile(r"oce[nń]\s+(?:si[eę]|siebie|swoje\s+post[eę]py)", re.IGNORECASE), "evaluate", None),
    (re.compile(r"(?:run|do)\s+evaluat", re.IGNORECASE), "evaluate", None),
    # Critique
    (re.compile(r"(?:zrob|zr[oó]b)\s+krytyk[eę]", re.IGNORECASE), "critique", None),
    (re.compile(r"(?:uruchom|odpal)\s+krytyk[eę]", re.IGNORECASE), "critique", None),
    (re.compile(r"(?:run|do)\s+critique", re.IGNORECASE), "critique", None),
    (re.compile(r"(?:sprawd[zź]|przeanalizuj)\s+(?:jako[sś][cć]|sp[oó]jno[sś][cć])\s+wiedzy", re.IGNORECASE), "critique", None),
    # Self-analysis
    (re.compile(r"(?:przeanalizuj|zanalizuj)\s+(?:si[eę]|siebie)", re.IGNORECASE), "self_analyze", None),
    (re.compile(r"(?:zrob|zr[oó]b)\s+(?:auto)?analiz[eę]", re.IGNORECASE), "self_analyze", None),
    (re.compile(r"(?:run|do)\s+(?:self.?)?analysis", re.IGNORECASE), "self_analyze", None),
    # Exam
    (re.compile(r"(?:zrob|zr[oó]b)\s+(?:mi\s+)?egzamin\s+(?:z\s+)?(.+)", re.IGNORECASE), "exam", 1),
    (re.compile(r"(?:sprawdz|sprawd[zź])\s+(?:moj[aą]?\s+)?wiedz[eę]\s+(?:o\s+|z\s+)?(.+)", re.IGNORECASE), "exam", 1),
    (re.compile(r"(?:prze)?egzaminuj\s+(?:si[eę]\s+)?(?:z\s+)?(.+)", re.IGNORECASE), "exam", 1),
    # Creative / reflection
    (re.compile(r"(?:zrob|zr[oó]b)\s+refleksj[eę]", re.IGNORECASE), "creative", None),
    (re.compile(r"(?:uruchom|odpal)\s+(?:modu[lł]\s+)?kreatywn", re.IGNORECASE), "creative", None),
    # Validate
    (re.compile(r"(?:zwaliduj|zweryfikuj)\s+wiedz[eę]", re.IGNORECASE), "validate", None),
    (re.compile(r"(?:sprawd[zź])\s+(?:czy\s+)?wiedza\s+(?:si[eę]\s+)?zgadza", re.IGNORECASE), "validate", None),
]


def detect_operational_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detect operational command intent from user text.

    Recognizes commands like "zrob fetch", "odpal krytykę", "przeanalizuj się".
    These trigger planner actions, not learning goals.

    Returns:
        Dict with keys: action, topic (optional), confidence
        Or None if no operational intent detected.
    """
    if not text or len(text) < 4:
        return None

    text = text.strip()

    for pattern, action, topic_group in _OP_PATTERNS:
        match = pattern.search(text)
        if match:
            topic = None
            if topic_group is not None:
                try:
                    topic = _clean_topic(match.group(topic_group))
                except (IndexError, AttributeError):
                    pass
            result = {
                "action": action,
                "confidence": 0.9,
            }
            if topic:
                result["topic"] = topic
            return result

    return None


def _clean_topic(raw: str) -> str:
    """Clean extracted topic string."""
    topic = raw.strip()
    topic = _TOPIC_CLEANUP.sub('', topic)
    topic = topic.strip()

    if len(topic) < _TOPIC_MIN_LEN:
        return ""
    if len(topic) > _TOPIC_MAX_LEN:
        topic = topic[:_TOPIC_MAX_LEN]

    return topic
