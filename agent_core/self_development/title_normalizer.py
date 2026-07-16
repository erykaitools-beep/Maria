"""Deterministic title normalization (zero LLM) for meta-goal de-duplication.

Collapses trivial variants onto a stable key:
- casing, surrounding whitespace
- Polish diacritics (rozne -> rozne, predkosc/predkosc)
- embedded numbers / percents ("o 10%", "0.1")
- word order (the key is a sorted set of words)

It deliberately does NOT merge synonyms like "treningowych" vs "szkoleniowych"
-- that is the job of the embedding step (INC-4). This normalizer is the cheap
first pass and the cache key for the embedding assignment.
"""

import re
import unicodedata

# "o 10%", "0.1", "10" -> dropped (variants that mean the same idea)
_NUM_RE = re.compile(r"[0-9]+([.,][0-9]+)?%?")
# anything not a-z or space -> space
_NONALPHA_RE = re.compile(r"[^a-z ]+")
# "l with stroke" has no NFKD decomposition, so map it explicitly first
_PRE_MAP = str.maketrans({"ł": "l", "Ł": "l"})


def normalize_title(title: str) -> str:
    """Return a stable normalized key for a meta-goal title.

    Two titles that are trivial variants of the same idea map to the same key.
    Returns an empty string for empty/None input.
    """
    if not title:
        return ""
    t = title.lower().strip().translate(_PRE_MAP)
    # strip combining diacritics (a-ogonek, z-dot, etc.)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    # drop numbers / percents, then non-letters -> space
    t = _NUM_RE.sub(" ", t)
    t = _NONALPHA_RE.sub(" ", t)
    # unique words longer than 2 chars, sorted -> order-independent key
    words = sorted({w for w in t.split() if len(w) > 2})
    return " ".join(words)
