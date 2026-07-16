"""
FetchRegistry - tracks fetched web content in JSONL.

MERGE semantics: last record per URL wins (same as knowledge_index.jsonl).
File: meta_data/web_fetch_registry.jsonl
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_REGISTRY_PATH = _META_DIR / "web_fetch_registry.jsonl"
MAX_ENTRIES = 500
# Jak dlugo "Wikipedia nie ma tego hasla" pozostaje wiazace. Skonczone, bo
# werdykt bywal falszywy (transient 429 czytany jako brak hasla) i nic w repo
# nigdy nie kasowalo wpisu -- temat znikal z ciekawosci Marii na zawsze.
# Ponowne sprawdzenie kosztuje jedno wyszukanie na temat na miesiac.
DEAD_TOPIC_TTL_SEC = 30 * 86400  # 30 dni
# Jak dlugo "juz mam wszystkie artykuly Wikipedii o tym temacie" pozostaje
# wiazace. KROTSZE niz dead (30d): martwy temat to trwaly self-jargon, wyczerpany
# to zywy temat, ktory po prostu jest juz na dysku -- Wikipedia moze dopisac nowe
# haslo, a Maria moze chciec go dotknac ponownie szybciej niz martwy zmartwychwstaje.
EXHAUSTED_TOPIC_TTL_SEC = 7 * 86400  # 7 dni


class FetchRegistry:
    """
    Tracks fetched web content to avoid re-downloading.

    Each record represents a successfully fetched URL.
    JSONL with MERGE semantics: last record per URL wins.
    """

    def __init__(self, registry_path: Optional[Path] = None):
        self._path = Path(registry_path or _DEFAULT_REGISTRY_PATH)
        self._cache: Optional[Dict[str, Dict]] = None
        self._topic_cache: Optional[Set[str]] = None
        # Topics Wikipedia has no article for (search -> 0 titles). Kept next to
        # the registry so the suggester stops re-proposing un-searchable self-jargon.
        self._dead_path = self._path.with_name("web_dead_topics.jsonl")
        self._dead_cache: Optional[Set[str]] = None
        # Topics whose Wikipedia articles are ALL already on disk (search returned
        # titles, but every one was a file we already have). Distinct from dead:
        # the topic is real and searchable, just fully harvested -- skipping it
        # frees the EXPLORE slot so a fresh topic gets fetched instead of the
        # picker re-proposing the same saturated one every session.
        self._exhausted_path = self._path.with_name("web_exhausted_topics.jsonl")
        self._exhausted_cache: Optional[Set[str]] = None

    def is_fetched(self, url: str) -> bool:
        """Check if URL has already been fetched."""
        data = self._load()
        return url in data

    def is_topic_fetched(self, topic: str) -> bool:
        """Check if a topic (search query) has already been used."""
        if self._topic_cache is None:
            data = self._load()
            self._topic_cache = set()
            for record in data.values():
                t = record.get("topic")
                if t:
                    self._topic_cache.add(t.lower().strip())
        return topic.lower().strip() in self._topic_cache

    def _load_ttl_topic_set(self, path: Path, ttl_sec: float) -> Set[str]:
        """Load a {topic, ts} JSONL into a lowercased set, dropping entries older
        than ttl_sec. Missing ts = pre-TTL entry -> treated as expired, so a stale
        record never lives forever through a missing field."""
        result: Set[str] = set()
        cutoff = time.time() - ttl_sec
        if not path.exists():
            return result
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = record.get("topic")
                    if t and record.get("ts", 0) >= cutoff:
                        result.add(t.lower().strip())
        except IOError:
            pass
        return result

    def _append_ttl_topic(self, path: Path, cache: Optional[Set[str]], topic: str) -> None:
        """Append a {topic, ts} line (append-only). Caller dedups via its is_*
        check first (which also warms the cache), so this just records + updates."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"topic": topic, "ts": time.time()}, ensure_ascii=False) + "\n")
            if cache is not None:
                cache.add(topic)
        except IOError as e:
            logger.warning(f"Could not write {path.name}: {e}")

    def is_topic_dead(self, topic: str) -> bool:
        """True if Wikipedia has no article for this topic (search returned 0
        titles). Such topics are Maria's un-searchable self-jargon ('analiza
        tekstu', 'strukturyzacja wiedzy'); skipping them stops the EXPLORE-slot
        drain so fresh real topics get fetched instead.

        Entries older than DEAD_TOPIC_TTL_SEC are ignored, so the verdict is
        provisional rather than lifelong. Real self-jargon simply gets re-marked
        on its next miss (one search); anything marked by mistake comes back.
        """
        if self._dead_cache is None:
            self._dead_cache = self._load_ttl_topic_set(self._dead_path, DEAD_TOPIC_TTL_SEC)
        return topic.lower().strip() in self._dead_cache

    def mark_topic_dead(self, topic: str) -> None:
        """Record a topic Wikipedia has no article for (search -> 0 titles), so the
        suggester stops handing EXPLORE slots to it. Append-only + deduped.

        One strike is enough ONLY because WikiClient.search now raises on
        transient failures instead of returning []: an empty list therefore means
        Wikipedia answered and had nothing. Before that fix a 429 reached here as
        "no article" and killed live topics permanently. The strike still expires
        (DEAD_TOPIC_TTL_SEC) so no single verdict is final.
        """
        t = (topic or "").lower().strip()
        if not t or self.is_topic_dead(t):
            return
        self._append_ttl_topic(self._dead_path, self._dead_cache, t)

    def is_topic_exhausted(self, topic: str) -> bool:
        """True if every Wikipedia article for this topic is already on disk
        (search returned titles, but each was a file we already have). Unlike a
        dead topic, this one is real -- it is just fully harvested. Skipping it
        stops the picker from re-proposing a saturated topic every session while
        thousands of fresh topics wait behind it.

        Expires after EXHAUSTED_TOPIC_TTL_SEC (shorter than dead), so a topic that
        gains a new Wikipedia article, or is simply worth revisiting, comes back.
        """
        if self._exhausted_cache is None:
            self._exhausted_cache = self._load_ttl_topic_set(
                self._exhausted_path, EXHAUSTED_TOPIC_TTL_SEC
            )
        return topic.lower().strip() in self._exhausted_cache

    def mark_topic_exhausted(self, topic: str) -> None:
        """Record a topic whose Wikipedia articles are all already fetched, so the
        suggester frees its EXPLORE slot for a fresh topic. Append-only + deduped;
        expires (EXHAUSTED_TOPIC_TTL_SEC) so the verdict is provisional."""
        t = (topic or "").lower().strip()
        if not t or self.is_topic_exhausted(t):
            return
        self._append_ttl_topic(self._exhausted_path, self._exhausted_cache, t)

    def register(
        self,
        url: str,
        title: str,
        source_type: str,
        output_file: str,
        char_count: int,
        topic: Optional[str] = None,
    ) -> None:
        """Record a successful fetch."""
        now = time.time()
        record = {
            "url": url,
            "title": title,
            "source_type": source_type,
            "topic": topic,
            "output_file": output_file,
            "char_count": char_count,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "ts": now,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.warning(f"Could not write fetch registry: {e}")

        # Invalidate caches
        self._cache = None
        self._topic_cache = None

    def get_stats(self) -> Dict[str, Any]:
        """Return fetch statistics."""
        data = self._load()
        sources = {}
        total_chars = 0
        for record in data.values():
            src = record.get("source_type", "unknown")
            sources[src] = sources.get(src, 0) + 1
            total_chars += record.get("char_count", 0)

        return {
            "total_fetched": len(data),
            "by_source": sources,
            "total_chars": total_chars,
        }

    def get_all(self) -> Dict[str, Dict]:
        """Return all records (keyed by URL)."""
        return dict(self._load())

    def _load(self) -> Dict[str, Dict]:
        """Load registry with MERGE semantics (last per URL wins)."""
        if self._cache is not None:
            return self._cache

        result: Dict[str, Dict] = {}
        if not self._path.exists():
            self._cache = result
            return result

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        url = record.get("url", "")
                        if url:
                            result[url] = record
                    except json.JSONDecodeError:
                        continue
        except IOError as e:
            logger.warning(f"Could not read fetch registry: {e}")

        if len(result) > MAX_ENTRIES:
            result = self._prune_to_latest(result, max_entries=MAX_ENTRIES)

        self._cache = result
        return result

    def _prune_to_latest(self, result: Dict[str, Dict], max_entries: int) -> Dict[str, Dict]:
        """Keep only latest max_entries records and rewrite JSONL."""
        sorted_items = sorted(
            result.items(),
            key=lambda item: item[1].get("ts", 0),
            reverse=True,
        )
        pruned = dict(sorted_items[:max_entries])
        self._rewrite_registry(pruned)
        return pruned

    def _rewrite_registry(self, data: Dict[str, Dict]) -> None:
        """Atomically rewrite registry file from merged in-memory data."""
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for record in data.values():
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            tmp_path.replace(self._path)
        except IOError as e:
            logger.warning(f"Could not prune fetch registry: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
