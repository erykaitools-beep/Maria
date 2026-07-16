"""
TaskIntentDetector - Map natural-language task descriptions to OpenClaw tool calls.

Given an operator request like "napisz plik /tmp/x.txt z trescia 'hello'", produce
a TaskIntent describing which OpenClaw tool to invoke and with what arguments.

Scope: explicit, pattern-based detection for the first five tools. No LLM. If no
pattern matches, returns None — caller decides how to surface that to the operator
(typically: "nie rozumiem zadania, doprecyzuj").

Supported patterns (Polish + English):
- write   : "napisz/zapisz plik <path> z trescia <content>"
- read    : "przeczytaj/pokaz plik <path>"
- web_fetch: "pobierz <url>" / "fetch <url>"
- web_search: "wyszukaj <query>" / "search <query>"
- exec    : "wykonaj/uruchom komende <command>" (dangerous, explicit keyword)

Design principles:
- Explicit trigger keywords only — no guessing from ambiguous input.
- Preserve original content verbatim when possible (quotes stripped).
- Return None rather than guess — "/do" command then echoes examples.
- Zero LLM in v1; richer intent parsing is a later milestone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TaskIntent:
    """A detected task intent ready to submit to ApprovalQueue."""
    tool_name: str
    tool_args: Dict[str, Any]
    raw_text: str
    pattern_id: str  # for debugging / telemetry
    confidence: float = 1.0  # 0..1; currently always 1.0 (rule-based)


# --- pattern table ---------------------------------------------------------
#
# Each pattern is (id, compiled regex, builder).
# builder(match) -> (tool_name, tool_args).
# Order matters: first match wins, so more specific patterns go first.
# Regex uses re.IGNORECASE | re.DOTALL so quoted multi-line content works.

_PATTERNS: List[Tuple[str, "re.Pattern[str]", "callable"]] = []


def _register(pattern_id: str, regex: str, builder) -> None:
    _PATTERNS.append(
        (pattern_id, re.compile(regex, re.IGNORECASE | re.DOTALL), builder)
    )


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"', "`"):
        return s[1:-1]
    return s


# Polish diacritics fold, used for KEYWORD matching only. Each accented char
# maps to exactly one ASCII char, so the fold is length-preserving: a match on
# the folded text has spans that index 1:1 back into the original. That lets
# the ASCII keyword patterns match natural Polish ("z trescia") while path and
# content are sliced from the ORIGINAL text, so accented file content survives.
# Escapes (not literal glyphs) so the source stays pure ASCII.
_PL_FOLD = str.maketrans(
    "ąćęłńóśźż"
    "ĄĆĘŁŃÓŚŹŻ",
    "acelnoszzACELNOSZZ",
)


class _OriginalMatch:
    """Adapts a regex Match made on FOLDED text so ``group(i)`` returns the
    matching slice of the ORIGINAL (un-folded) text. The fold is
    length-preserving, so the folded match's spans are valid indices into the
    original; an unmatched optional group falls back to the raw group (None)."""

    __slots__ = ("_original", "_match")

    def __init__(self, original: str, match: "re.Match[str]") -> None:
        self._original = original
        self._match = match

    def group(self, index: int = 0) -> Optional[str]:
        start, end = self._match.span(index)
        if start < 0:
            return self._match.group(index)
        return self._original[start:end]


# write: "napisz/zapisz plik <path> z trescia/tekstem <content>"
_register(
    "write_pl",
    r"^(?:napisz|zapisz|stworz|utworz)\s+(?:plik|do\s+pliku)\s+(\S+)"
    r"\s+(?:z\s+trescia|z\s+tekstem|z\s+zawartoscia|z)\s+(.+)$",
    lambda m: ("write", {"path": m.group(1), "content": _strip_quotes(m.group(2))}),
)
# write: English fallback
_register(
    "write_en",
    r"^(?:write|create)\s+(?:file\s+)?(\S+)\s+(?:with|containing)\s+(.+)$",
    lambda m: ("write", {"path": m.group(1), "content": _strip_quotes(m.group(2))}),
)

# read: "przeczytaj/pokaz plik <path>"
_register(
    "read_pl",
    r"^(?:przeczytaj|pokaz|odczytaj|przejrzyj)\s+(?:plik\s+)?(\S+)\s*$",
    lambda m: ("read", {"path": m.group(1)}),
)
_register(
    "read_en",
    r"^(?:read|show|cat)\s+(?:file\s+)?(\S+)\s*$",
    lambda m: ("read", {"path": m.group(1)}),
)

# web_fetch: "pobierz <url>" / "fetch <url>"
_register(
    "web_fetch",
    r"^(?:pobierz|fetch|sciagnij)\s+(https?://\S+)\s*$",
    lambda m: ("web_fetch", {"url": m.group(1)}),
)

# web_search: "wyszukaj <query>" / "search <query>"
_register(
    "web_search_pl",
    r"^(?:wyszukaj|znajdz)\s+(.+)$",
    lambda m: ("web_search", {"query": _strip_quotes(m.group(1))}),
)
_register(
    "web_search_en",
    r"^search\s+(?:for\s+)?(.+)$",
    lambda m: ("web_search", {"query": _strip_quotes(m.group(1))}),
)

# exec: "wykonaj/uruchom komende <cmd>" — explicit, no shorthand
_register(
    "exec_pl",
    r"^(?:wykonaj|uruchom)\s+(?:komende|polecenie)\s+(.+)$",
    lambda m: ("exec", {"command": _strip_quotes(m.group(1))}),
)
_register(
    "exec_en",
    r"^(?:run|execute)\s+(?:command\s+)?(.+)$",
    lambda m: ("exec", {"command": _strip_quotes(m.group(1))}),
)


# --- public API -------------------------------------------------------------


class TaskIntentDetector:
    """Detect tool-use intent from a free-form task description.

    Stateless. Thread-safe. Zero external dependencies.
    """

    def detect(self, text: str) -> Optional[TaskIntent]:
        if not text:
            return None
        norm = text.strip()
        if not norm:
            return None

        # Match keywords on a diacritics-folded copy (so natural Polish like
        # "z trescia" hits the ASCII patterns) but build args from the ORIGINAL
        # via _OriginalMatch, so accented paths/content are preserved verbatim.
        folded = norm.translate(_PL_FOLD)
        for pattern_id, regex, builder in _PATTERNS:
            match = regex.match(folded)
            if match:
                tool_name, tool_args = builder(_OriginalMatch(norm, match))
                return TaskIntent(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    raw_text=text,
                    pattern_id=pattern_id,
                )
        return None

    def help_examples(self) -> List[str]:
        """Human-readable examples shown when /do doesn't match."""
        return [
            "napisz plik /tmp/x.txt z trescia 'hello world'",
            "przeczytaj plik /etc/hostname",
            "pobierz https://example.com/page",
            "wyszukaj 'python asyncio tutorial'",
            "wykonaj komende 'uptime'",
        ]


__all__ = ["TaskIntent", "TaskIntentDetector"]
