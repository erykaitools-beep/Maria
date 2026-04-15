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
