"""Detect intent and confabulation in Maria's chat responses.

Mirror of learning_intent._OP_PATTERNS, but for Maria's *own* utterances in
the Web UI chat path. Closes Bug 3 + Bug 5 from the 24h autonomy postmortem
(2026-05-14):

* Bug 5 (asymmetry): user -> goal_create works via detect_operational_intent,
  Maria -> nothing. Here we add the mirror: when Maria says "Pobiore X" or
  "Zrobie egzamin z Y", that becomes a USER goal forced_action_type=...
  exactly like the user-side flow.

* Bug 3c (confabulation flag): Maria sometimes claims past actions
  ("Napisalam skrypt", "Uruchomilam fix") that never happened, because the
  chat path is pure llama hallucination. We detect such past-tense claims
  and let the handler emit a soft warning to the UI (operator visibility).

Rule-based, zero LLM. Polish + English.

Usage:
    intent = detect_maria_intent("Pobiore nowe materialy o fizyce.")
    if intent:
        # -> {"action": "fetch", "confidence": 0.85, "topic": "fizyce"}
        create_goal(forced_action_type=intent["action"], ...)

    claim = detect_past_claim("Napisalam skrypt naprawiajacy parser.")
    if claim and no_goal_was_just_created:
        emit_warning(claim["snippet"])
"""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent patterns - 1st person singular, future/present
# Each tuple: (compiled regex, action_type, topic_group_index_or_None)
# Mirrors learning_intent._OP_PATTERNS but in Maria's voice.
# ---------------------------------------------------------------------------

_INTENT_PATTERNS = [
    # Planner delegation (explicit) - highest priority
    (re.compile(r"zlec[eę]?\s+(?:to\s+)?(?:plannerowi|planerowi|planer)", re.IGNORECASE),
     "planner_delegation", None),
    (re.compile(r"przeka[zż][eę]\s+(?:to\s+)?(?:plannerowi|planerowi)", re.IGNORECASE),
     "planner_delegation", None),
    # Fetch / download (1st person future)
    (re.compile(r"pobior[eę]\s+(?:nowe\s+)?(?:materia[lł]y|artyku[lł]y)\s*(?:o\s+|na\s+temat\s+)?(.+)?",
                re.IGNORECASE), "fetch", 1),
    (re.compile(r"pobior[eę]\s+(.+?)(?:[.!?]|$)", re.IGNORECASE), "fetch", 1),
    (re.compile(r"[sś]ci[aą]gn[eę]\s+(?:nowe\s+)?(?:materia[lł]y|artyku[lł]y)", re.IGNORECASE),
     "fetch", None),
    # Exam
    (re.compile(r"(?:zrobi[eę]|przeprowadz[eę])\s+(?:sobie\s+)?(?:egzamin|test)\s+(?:z\s+|o\s+)?(.+)",
                re.IGNORECASE), "exam", 1),
    (re.compile(r"przeegzaminuj[eę]\s+(?:si[eę]\s+)?(?:z\s+|o\s+)?(.+)", re.IGNORECASE),
     "exam", 1),
    (re.compile(r"sprawdz[eę]\s+(?:swoj[aą]\s+)?wiedz[eę]\s+(?:z\s+|o\s+)?(.+)", re.IGNORECASE),
     "exam", 1),
    # Critique
    (re.compile(r"(?:zrobi[eę]|uruchomi[eę]|odpal[eę])\s+krytyk[eę]", re.IGNORECASE),
     "critique", None),
    (re.compile(r"przeanalizuj[eę]\s+jako[sś][cć]\s+wiedzy", re.IGNORECASE), "critique", None),
    # Self-analysis
    (re.compile(r"(?:zrobi[eę]|przeprowadz[eę])\s+(?:auto)?analiz[eę]\s+(?:siebie|si[eę]|stanu|swoj)",
                re.IGNORECASE), "self_analyze", None),
    (re.compile(r"przeprowadz[eę]\s+autoanaliz[eę]", re.IGNORECASE), "self_analyze", None),
    (re.compile(r"przeanalizuj[eę]\s+(?:si[eę]|siebie)", re.IGNORECASE), "self_analyze", None),
    # Evaluate
    (re.compile(r"(?:zrobi[eę]|uruchomi[eę])\s+ewaluacj[eę]", re.IGNORECASE), "evaluate", None),
    (re.compile(r"ocen[eę]\s+(?:swoje\s+)?post[eę]py", re.IGNORECASE), "evaluate", None),
    # Creative
    (re.compile(r"(?:zrobi[eę]|uruchomi[eę])\s+refleksj[eę]", re.IGNORECASE), "creative", None),
    (re.compile(r"pomysl[eę]\s+(?:tw[oó]rczo\s+)?(?:o\s+)?(.+)", re.IGNORECASE), "creative", 1),
    # Validate
    (re.compile(r"(?:zwaliduj[eę]|zweryfikuj[eę])\s+wiedz[eę]", re.IGNORECASE), "validate", None),
    # Learning (1st person)
    (re.compile(r"naucz[eę]\s+si[eę]\s+(?:o\s+|z\s+)?(.+)", re.IGNORECASE), "learn", 1),
    (re.compile(r"poczyt[aą]m\s+(?:o\s+|na\s+temat\s+)?(.+)", re.IGNORECASE), "learn", 1),
    (re.compile(r"dowiem\s+si[eę]\s+(?:o\s+)?(.+)", re.IGNORECASE), "learn", 1),
    # English (light coverage)
    (re.compile(r"i\s+will\s+(?:run|do)\s+(?:a\s+)?critique", re.IGNORECASE), "critique", None),
    (re.compile(r"i\s+will\s+fetch\s+(?:new\s+)?(?:materials?|articles?)", re.IGNORECASE),
     "fetch", None),
    (re.compile(r"i\s+will\s+take\s+(?:an?\s+)?exam\s+(?:on\s+|about\s+)?(.+)", re.IGNORECASE),
     "exam", 1),
]


# ---------------------------------------------------------------------------
# Past-tense claim patterns - 1st person, past perfective
# Tripwire for confabulation. Soft signal: if these match AND no goal was
# just created for this turn, the handler logs + emits a UI flag.
#
# Phase 2 (2026-05-15): added _THIRD_PARTY_CLAIM_PATTERNS for "planner/system/
# skrypt zrobil X" - konfabulacja-2.0 vector where Maria attributes past
# actions to other subsystems without verification. Detected separately so
# the handler can verify against goals/action_audit rather than just flag.
# ---------------------------------------------------------------------------

_CLAIM_PATTERNS = [
    re.compile(r"napisa[lł]am\s+(?:ju[zż]\s+)?(?:skrypt|kod|plik|funkcj[eę]|program|test|fix|patch)",
               re.IGNORECASE),
    re.compile(r"uruchomi[lł]am\s+(?:ju[zż]\s+)?(?:t[eę]n?|t[aą]|to|m[oó]j|sw[oó]j)?\s*(?:skrypt|kod|polecenie|komend[eę]|program|exec)",
               re.IGNORECASE),
    re.compile(r"zmodyfikowa[lł]am\s+(?:ju[zż]\s+)?(?:t[eę]n?|t[aą]|to|m[oó]j|sw[oó]j)?\s*(?:plik|kod|parser|funkcj[eę]|skrypt)",
               re.IGNORECASE),
    re.compile(r"wykona[lł]am\s+(?:ju[zż]\s+)?(?:t[eę]|tak[aą]|t[oó]|ca[lł][aą])?\s*(?:akcj[eę]|polecenie|skrypt|kod)",
               re.IGNORECASE),
    re.compile(r"zrobi[lł]am\s+(?:ju[zż]\s+)?(?:t[eę]n?|t[aą]|to|m[oó]j|sw[oó]j)?\s*(?:fix|napraw[eę]|patch|commit)",
               re.IGNORECASE),
    re.compile(r"naprawi[lł]am\s+(?:ju[zż]\s+)?(?:t[eę]n?|t[aą]|to|m[oó]j|sw[oó]j)?\s*(?:parser|kod|plik|skrypt|bug|blad)",
               re.IGNORECASE),
    re.compile(r"pobra[lł]am\s+(?:ju[zż]\s+)?(?:t[eę]n?|t[aą]|to|m[oó]j|sw[oó]j)?\s*(?:plik|materia[lł]|artyku[lł])",
               re.IGNORECASE),
    re.compile(r"zapisa[lł]am\s+(?:ju[zż]\s+)?(?:t[eę]n?|t[aą]|to|m[oó]j|sw[oó]j)?\s*(?:plik|kod|wynik|skrypt)",
               re.IGNORECASE),
    re.compile(r"skompilowa[lł]am\s+", re.IGNORECASE),
    re.compile(r"zacommitowa[lł]am\s+", re.IGNORECASE),
    # English light
    re.compile(r"\bi\s+(?:have\s+)?(?:wrote|written|ran|executed|modified|fixed|patched)\s+the\s+",
               re.IGNORECASE),
]


# Third-party attribution patterns: Maria claims that *another subsystem*
# (planner, system, skrypt, executor) did/is-doing something. Konfabulacja-2.0
# vector observed 2026-05-15 22:00 Berlin in Web UI chat ("planer wykonal X",
# "system zaczyna wykonywac skrypt..."). Caller (claim verifier) checks
# goals.jsonl + action_audit.jsonl for matching evidence in recent window.
_THIRD_PARTY_CLAIM_PATTERNS = [
    # planner / planer past-tense or present-progressive claims
    re.compile(
        r"plan(?:er|ner|nera|nerowi)\s+(?:ju[zż]\s+)?(?:otrzyma[lł]|wykona[lł]|"
        r"zrobi[lł]|zaczyna|zaczal|robi|wykonuje|przyjal|przyjela)",
        re.IGNORECASE,
    ),
    # system / agent claims
    re.compile(
        r"system\s+(?:ju[zż]\s+)?(?:wykona[lł]|zrobi[lł]|uruchomi[lł]|"
        r"zaczyna|wykonuje|przetwarza)",
        re.IGNORECASE,
    ),
    # skrypt / kod / executor claims (third-person)
    re.compile(
        r"(?:skrypt|kod|executor|effector)\s+(?:ju[zż]\s+)?(?:zosta[lł]|jest\s+wykonany|"
        r"jest\s+uruchomiony|wykonal\s+sie|sko[nń]czyl|zaczyna)",
        re.IGNORECASE,
    ),
    # "polecenie wyslane / przekazane" passive style
    re.compile(
        r"polecenie\s+(?:ju[zż]\s+)?(?:zosta[lł]o\s+)?(?:wys[lł]ane|przekazane|"
        r"przyjete|wykonane)",
        re.IGNORECASE,
    ),
    # Fake grounded prefix patterns (Maria using "Widze w logach" without real
    # evidence_collector data). The verifier will check whether grounded
    # pipeline actually fired in the last turn.
    re.compile(r"widz[eę]\s+w\s+logach", re.IGNORECASE),
    re.compile(r"zr[oó]d[lł]o\s+danych\s*:", re.IGNORECASE),
]


def detect_third_party_claim(text: str) -> Optional[Dict[str, Any]]:
    """Detect a claim that another subsystem (planner/system/skrypt) acted.

    Konfabulacja-2.0 vector: Maria says "planer wykonal X" / "system zrobil Y"
    without any matching goal_create or action_audit entry. Unlike
    detect_past_claim (which flags 1st-person self-attribution), this requires
    the handler to *verify against the world* before deciding whether to flag.

    Returns dict with keys: matched, snippet, category. None if no match.

    Category is one of: 'planner', 'system', 'executor', 'polecenie',
    'fake_grounded' - lets the verifier pick the right evidence source.
    """
    if not text or len(text) < 6:
        return None

    categories = ["planner", "system", "executor", "polecenie", "fake_grounded", "fake_grounded"]
    for pattern, category in zip(_THIRD_PARTY_CLAIM_PATTERNS, categories):
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 40)
            return {
                "matched": match.group(0),
                "snippet": text[start:end].strip(),
                "category": category,
            }

    return None


_TOPIC_CLEANUP = re.compile(r'[.!?;,]+$')
_TOPIC_MIN_LEN = 3
_TOPIC_MAX_LEN = 80


def detect_maria_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detect intent to act in Maria's response (1st person, future/present).

    Returns dict with keys: action, confidence, topic (optional).
    Returns None if no intent detected or input is too short.

    Mirror of learning_intent.detect_operational_intent but reads Maria's
    side of the dialogue. Used by Web UI chat handler to create USER goals
    when Maria declares an action she wants to take.
    """
    if not text or len(text) < 4:
        return None

    text = text.strip()

    for pattern, action, topic_group in _INTENT_PATTERNS:
        match = pattern.search(text)
        if match:
            topic = None
            if topic_group is not None:
                try:
                    raw = match.group(topic_group)
                    if raw:
                        topic = _clean_topic(raw)
                except (IndexError, AttributeError):
                    pass
            result: Dict[str, Any] = {
                "action": action,
                "confidence": 0.85,
            }
            if topic:
                result["topic"] = topic
            return result

    return None


def detect_past_claim(text: str) -> Optional[Dict[str, Any]]:
    """Detect 1st-person past-tense claim of having done a concrete action.

    Tripwire for confabulation. The handler combines this with
    "was a goal just created for this turn?" to decide whether the claim
    is suspicious. If suspicious -> emit soft warning to UI.

    Returns dict with keys: matched (the exact match string),
    snippet (~50 chars of surrounding context). None if nothing matched.
    """
    if not text or len(text) < 6:
        return None

    for pattern in _CLAIM_PATTERNS:
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 30)
            return {
                "matched": match.group(0),
                "snippet": text[start:end].strip(),
            }

    return None


def _clean_topic(raw: str) -> str:
    """Clean extracted topic string. Cuts at sentence boundary."""
    topic = raw.strip()
    # Cut at sentence boundary (Maria responses are full sentences)
    for sep in ['.', '!', '?', ';', '\n']:
        if sep in topic:
            topic = topic.split(sep)[0]
    topic = _TOPIC_CLEANUP.sub('', topic).strip().rstrip(',')

    if len(topic) < _TOPIC_MIN_LEN:
        return ""
    if len(topic) > _TOPIC_MAX_LEN:
        topic = topic[:_TOPIC_MAX_LEN].rstrip()

    return topic
