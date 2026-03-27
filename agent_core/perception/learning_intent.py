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
