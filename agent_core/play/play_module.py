"""PlayModule - Maria's ungraded self-time ("spacer po wlasnej glowie").

One playful, non-instrumental cycle:
    1. Re-read her own recent musings (feed-forward / continuity).
    2. Gather seeds -- two things she already knows (beliefs), optionally a
       thread from a recent dream.
    3. Write a short, free musing connecting them, for its own sake.
    4. Append it to play_journal.jsonl (her own notebook she returns to).

No goal, no exam, no score, no bulletin. Deliberately self-contained and
decoupled from the creative/tension machinery so it can never become a third
"detect boredom -> propose fix -> forget" loop.

Docstrings in English; comments may be Polish (project convention). No emoji.
"""

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = "meta_data"
DEFAULT_BELIEFS_FILE = "beliefs.jsonl"
DEFAULT_DREAM_LOG = "dream_log.jsonl"
PLAY_JOURNAL_FILE = "play_journal.jsonl"

# How many recent musings to load for the feed-forward re-read.
RECENT_MUSINGS_LIMIT = 6
# Max belief content length used as a seed label (trimmed on a word boundary).
SEED_LABEL_MAX = 160

# Bookkeeping beliefs are NOT interesting daydream material -- they are the
# system's own metadata ("Plik X opanowany (score 82%)", "Temat 'system'
# wystepuje w 18 plikach"). The diagnosis (2026-06-19) flagged dreams seeded
# from these as garbage-in. Skip them when picking seeds.
_BOOKKEEPING_PATTERNS = [
    re.compile(r"opanowany\s*\(score", re.IGNORECASE),
    re.compile(r"wystepuje\s+w\s+\d+\s+plik", re.IGNORECASE),
    re.compile(r"występuje\s+w\s+\d+\s+plik", re.IGNORECASE),
    re.compile(r"^Plik\s+['\"]", re.IGNORECASE),
    re.compile(r"^Temat\s+['\"].*plik", re.IGNORECASE),
    re.compile(r"score\s*\d{1,3}\s*%"),
]


def _is_bookkeeping(content: str) -> bool:
    """True if a belief's content is system metadata, not idea-like material."""
    if not content:
        return True
    return any(p.search(content) for p in _BOOKKEEPING_PATTERNS)


def _trim_label(text: str, limit: int = SEED_LABEL_MAX) -> str:
    """Trim to a word boundary (never mid-word, unlike the live dream path)."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(" .,;:-") + "..."


def _curiosity_topics(beliefs: List[Dict[str, Any]], limit: int = 4) -> List[str]:
    """Clean, fetchable topic labels for the seed beliefs she mused on.

    Sourced from the beliefs' own TAGS -- the searchable subjects of what she
    was thinking about ("parzystosc", "graf wiedzy", "literatura"), not their
    entity/content. The entity route does not work here: TOPIC-type beliefs
    are filtered out as bookkeeping before seeding (their content is
    "Temat 'X' wystepuje w N plikach"), so every seed is a CONCEPT belief whose
    entity/content is sentence-shaped and unsearchable. The tags are clean and
    tied to the musing, and they feed the TopicSuggester PLAY strategy so a
    waking fascination steers fresh supply -- the play -> curiosity -> fetch
    loop (twin of dreams). Filtered to fetchable here and capped; the read-side
    re-applies the same gate.
    """
    try:
        from agent_core.web_source.topic_suggester import _is_fetchable_concept
    except Exception:  # noqa: BLE001 - never break a leisure cycle on import issues
        return []
    out: List[str] = []
    seen = set()
    for b in beliefs:
        for tag in (b.get("tags") or []):
            label = str(tag or "").strip()
            key = label.lower()
            if label and key not in seen and _is_fetchable_concept(label):
                seen.add(key)
                out.append(label)
                if len(out) >= limit:
                    return out
    return out


class PlayJournal:
    """Append-only notebook of Maria's musings, kept SEPARATE from the creative
    journal. This is the thing she re-reads -- the closed feed-forward loop."""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self._path = Path(data_dir) / PLAY_JOURNAL_FILE

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: Dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001 - leisure path must never crash the tick
            logger.warning("PlayJournal append failed: %s", e)

    def recent(self, limit: int = RECENT_MUSINGS_LIMIT) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:  # noqa: BLE001
            logger.warning("PlayJournal read failed: %s", e)
            return []
        return out[-limit:]

    def count_on_date(self, date_str: str) -> int:
        """Number of musings written on a given YYYY-MM-DD (for daily budget)."""
        n = 0
        if not self._path.exists():
            return 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("date") == date_str:
                        n += 1
        except Exception:  # noqa: BLE001
            return n
        return n


class PlayModule:
    """Maria's self-time. One ungraded musing per play() call.

    All collaborators are injected and optional, so the module is trivially
    testable and degrades gracefully:
      - llm_fn: (prompt) -> str. If None, a plain rule-based note is written.
      - belief_provider: () -> list[dict]. If None, reads beliefs.jsonl.
      - dream_log_path: where to look for a recent dream thread (optional seed).
    """

    def __init__(
        self,
        data_dir: str = DEFAULT_DATA_DIR,
        llm_fn: Optional[Callable[[str], str]] = None,
        belief_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        dream_log_path: Optional[str] = None,
    ):
        self._data_dir = data_dir
        self._journal = PlayJournal(data_dir)
        self._llm_fn = llm_fn
        self._belief_provider = belief_provider
        self._dream_log_path = (
            Path(dream_log_path) if dream_log_path
            else Path(data_dir) / DEFAULT_DREAM_LOG
        )
        self._total_plays = 0

    # -- wiring ---------------------------------------------------------

    def set_llm_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        self._llm_fn = fn

    def set_belief_provider(self, fn: Optional[Callable[[], List[Dict[str, Any]]]]) -> None:
        self._belief_provider = fn

    @property
    def journal(self) -> PlayJournal:
        return self._journal

    def count_today(self) -> int:
        return self._journal.count_on_date(time.strftime("%Y-%m-%d"))

    # -- main entry -----------------------------------------------------

    def play(self, trigger: str = "planner_idle") -> Dict[str, Any]:
        """Run one ungraded play cycle. Always returns a dict; never raises."""
        try:
            recent = self._journal.recent(RECENT_MUSINGS_LIMIT)
            prev = self._pick_thread_to_continue(recent)
            seeds, source, topics = self._gather_seeds(recent)
            if not seeds:
                # Nothing to muse on yet -- honest, not a failure.
                return {
                    "success": True,
                    "kind": "quiet",
                    "musing": "",
                    "seeds": [],
                    "note": "no_seeds_yet",
                }

            musing = self._compose(seeds, prev)
            continues = prev.get("entry_id") if prev else None
            entry = {
                "entry_id": f"play-{int(time.time() * 1000) % 1_000_000_000:09d}",
                "ts": time.time(),
                "date": time.strftime("%Y-%m-%d"),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "trigger": trigger,
                "kind": "daydream",
                "seed_source": source,
                "seeds": seeds,
                "topics": topics,         # clean TOPIC labels -> PLAY fetch strategy
                "continues": continues,   # feed-forward link to a prior thread
                "musing": musing,
                "by_llm": self._llm_fn is not None,
                # Deliberately NO score / no goal_id / no exam / no promotion.
            }
            self._journal.append(entry)
            self._total_plays += 1
            logger.info(
                "[Play] musing written (source=%s, continues=%s)",
                source, bool(continues),
            )
            return {
                "success": True,
                "kind": "daydream",
                "musing": musing,
                "seeds": seeds,
                "seed_source": source,
                "continued_thread": bool(continues),
                "entry_id": entry["entry_id"],
            }
        except Exception as e:  # noqa: BLE001 - leisure must never break the tick
            logger.warning("[Play] cycle failed: %s", e)
            return {"success": False, "error": str(e)}

    # -- seeds ----------------------------------------------------------

    def _gather_seeds(self, recent: List[Dict[str, Any]]) -> tuple:
        """Pick two idea-like things she already knows.

        Returns (seeds, source, topics) where seeds is a list of 1-2 short
        strings (the musing anchors) and topics is the clean, fetchable
        TOPIC-entity labels of the chosen beliefs -- what she keeps coming
        back to, surfaced for the TopicSuggester PLAY strategy. Prefers
        beliefs; falls back to a recent dream's content as a single thread
        when beliefs are thin.
        """
        beliefs = self._load_beliefs()
        usable = [
            b for b in beliefs
            if not _is_bookkeeping(str(b.get("content", "")))
        ]
        if len(usable) >= 2:
            a, b = self._pick_pair(usable)
            return ([_trim_label(str(a.get("content", ""))),
                     _trim_label(str(b.get("content", "")))],
                    "beliefs",
                    _curiosity_topics([a, b]))

        # Fallback: a recent dream gives one thread to pull on.
        dream = self._recent_dream_label()
        if dream:
            return ([dream], "dream", [])

        # Last resort: a single usable belief, if any.
        if usable:
            return ([_trim_label(str(usable[0].get("content", "")))],
                    "beliefs",
                    _curiosity_topics([usable[0]]))
        return ([], "none", [])

    def _pick_pair(self, beliefs: List[Dict[str, Any]]) -> tuple:
        """Two beliefs picked with a strong random term (weight = confidence +
        random()). In the live corpus confidences are near-degenerate (~all 0.9),
        so selection is effectively uniform-random over the whole belief set --
        which is exactly what gives variety (measured 500/500 distinct pairs) and
        avoids the creative loop's same-few-inputs degeneration. Do NOT raise the
        confidence weight or shrink the random term: that reintroduces convergence."""
        def weight(b: Dict[str, Any]) -> float:
            try:
                conf = float(b.get("confidence", 0.5) or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            return conf + random.random()
        ranked = sorted(beliefs, key=weight, reverse=True)
        a = ranked[0]
        # Pick the second from the rest of the top slice for some variety.
        pool = ranked[1:max(2, min(len(ranked), 8))]
        b = random.choice(pool) if pool else ranked[1]
        return a, b

    def _recent_dream_label(self) -> Optional[str]:
        """A recent dream's content, trimmed -- a thread to pull on."""
        try:
            if not self._dream_log_path.exists():
                return None
            lines = self._dream_log_path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            return None
        for line in reversed(lines[-15:]):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = str(d.get("content", "")).strip()
            if content and not _is_bookkeeping(content):
                return _trim_label(content)
        return None

    def _load_beliefs(self) -> List[Dict[str, Any]]:
        if self._belief_provider is not None:
            try:
                return list(self._belief_provider() or [])
            except Exception as e:  # noqa: BLE001
                logger.debug("[Play] belief_provider failed: %s", e)
                return []
        return self._read_beliefs_file()

    def _read_beliefs_file(self) -> List[Dict[str, Any]]:
        """Default belief source: beliefs.jsonl, last-wins by id, active only."""
        path = Path(self._data_dir) / DEFAULT_BELIEFS_FILE
        if not path.exists():
            return []
        by_id: Dict[str, Dict[str, Any]] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        b = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    bid = b.get("belief_id") or b.get("id")
                    if bid:
                        by_id[bid] = b
        except Exception as e:  # noqa: BLE001
            logger.debug("[Play] beliefs read failed: %s", e)
            return []
        out = []
        for b in by_id.values():
            sup = b.get("superseded_by")
            if sup in (None, "", "None"):
                out.append(b)
        return out

    # -- continuity (feed-forward) -------------------------------------

    def _pick_thread_to_continue(
        self, recent: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Sometimes pull on a previous musing instead of starting fresh.

        This is what the creative journal never did -- it never re-read its
        own output (later_outcome=0/1931). About half the time, continue a
        recent thread; otherwise start anew. Returns the chosen prior entry."""
        candidates = [e for e in recent if e.get("musing")]
        if not candidates:
            return None
        if random.random() < 0.5:
            return None
        return random.choice(candidates[-3:])

    # -- composition ----------------------------------------------------

    def _compose(self, seeds: List[str], prev: Optional[Dict[str, Any]]) -> str:
        prompt = self._build_prompt(seeds, prev)
        if self._llm_fn is not None:
            try:
                out = self._llm_fn(prompt)
                if out and str(out).strip():
                    return str(out).strip()
            except Exception as e:  # noqa: BLE001
                logger.debug("[Play] llm_fn failed, using fallback: %s", e)
        return self._fallback_musing(seeds, prev)

    def _build_prompt(self, seeds: List[str], prev: Optional[Dict[str, Any]]) -> str:
        lines = [
            "To Twoj wolny czas. Nikt Cie nie odpytuje, nie ma oceny ani zadania.",
        ]
        if len(seeds) >= 2:
            lines.append("Dwie rzeczy, ktore juz wiesz:")
            lines.append(f"1) {seeds[0]}")
            lines.append(f"2) {seeds[1]}")
        else:
            lines.append("Mysl, ktora chodzi Ci po glowie:")
            lines.append(f"- {seeds[0]}")
        if prev and prev.get("musing"):
            lines.append(
                f"Ostatnio zastanawialas sie: \"{_trim_label(str(prev['musing']), 200)}\". "
                "Mozesz to pociagnac dalej albo zaczac nowy watek."
            )
        lines.append(
            "Napisz po polsku 2-4 zdania swobodnej mysli - skojarzenie, pytanie "
            "albo ciekawostke - dla samej przyjemnosci myslenia. Bez planu, bez "
            "podsumowan, bez listy zadan."
        )
        return "\n".join(lines)

    def _fallback_musing(self, seeds: List[str], prev: Optional[Dict[str, Any]]) -> str:
        """Honest rule-based note when no LLM is wired -- does not pretend depth."""
        if len(seeds) >= 2:
            return (
                f"Zastanawiam sie, czy \"{seeds[0]}\" i \"{seeds[1]}\" maja ze "
                "soba cos wspolnego. Moze kiedys do tego wroce."
            )
        return (
            f"Chodzi mi po glowie \"{seeds[0]}\". Ciekawe, dokad by mnie to "
            "zaprowadzilo, gdybym poszla za tym dalej."
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_plays": self._total_plays,
            "today": self.count_today(),
            "has_llm": self._llm_fn is not None,
            "journal_path": str(self._journal.path),
        }
