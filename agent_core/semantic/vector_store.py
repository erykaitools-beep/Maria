"""In-memory vector store with JSONL persistence.

Stores text -> embedding pairs, supports cosine similarity search.
Follows ADR-001: JSONL as source of truth.

Usage:
    store = VectorStore("meta_data/vectors.jsonl")
    store.add("id1", "fotosynteza u roslin", [0.1, 0.2, ...])
    results = store.search([0.1, 0.2, ...], top_k=5)
    store.save()  # Persist to JSONL
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_core.semantic.embedding_model import EmbeddingModel

logger = logging.getLogger(__name__)

# Caps
MAX_VECTORS = 10000  # Max stored vectors (cap to prevent OOM)

# Eviction priority per namespace: LOWEST number is evicted FIRST.
#
# Before 2026-07-31 eviction was blind -- purely globally-oldest by
# created_ts -- and the store had been sitting exactly at MAX_VECTORS.
# Measured on live data that day: 1150 new `summaries` vectors per day
# (chunk-level text of everything Maria reads) against 130 `beliefs` and
# 15 `knowledge`. Every summary chunk threw out whatever happened to be
# oldest, so 413 of 2000 current belief entities had no vector at all --
# invisible to semantic search -- and the whole store spanned just 4.9
# days. The boot indexer re-embedded the missing beliefs, the next day's
# reading evicted them again: a ping-pong. This is the same failure the
# 2026-06-10 audit found (see cleanup_stale_belief_vectors in indexer.py);
# back then the cap was eaten by ghost vectors, this time by the bulk
# recall corpus. Cleaning the filler does not fix it -- the eviction
# policy has to know what it is throwing away.
#
# `summaries` is a rolling corpus by design (working recall over what she
# has read) and is the one namespace that should absorb the pressure.
# Beliefs and knowledge are rebuilt only on boot, so losing them silently
# costs recall until the next restart.
EVICTION_PRIORITY: Dict[str, int] = {
    "summaries": 0,   # bulk recall corpus, rolling by design -- evict first
    "hints": 1,
    "beliefs": 3,
    "knowledge": 4,   # primary knowledge truth -- evict last
}
# Namespaces not listed above (legacy entries, namespaces added later)
# sit between the two groups: cheaper than beliefs/knowledge, but never
# evicted before the summaries that are meant to be recycled.
DEFAULT_EVICTION_PRIORITY = 2

# Namespaces whose eviction means the cap itself is too small, not that
# the recycling is working. Logged at INFO so it is visible in journalctl.
_PROTECTED_NAMESPACES = ("beliefs", "knowledge")


def _eviction_priority(entry: "VectorEntry") -> int:
    """Eviction rank of an entry; lower goes first.

    Entries without a namespace (legacy rows, ad-hoc adds) get
    DEFAULT_EVICTION_PRIORITY rather than being treated as the cheapest --
    an unlabelled vector is unknown, not worthless.
    """
    ns = entry.metadata.get("namespace")
    if ns is None:
        return DEFAULT_EVICTION_PRIORITY
    return EVICTION_PRIORITY.get(ns, DEFAULT_EVICTION_PRIORITY)


class VectorEntry:
    """Single entry in the vector store."""
    __slots__ = ("entry_id", "text", "vector", "metadata", "created_ts")

    def __init__(self, entry_id: str, text: str, vector: List[float],
                 metadata: Optional[Dict[str, Any]] = None,
                 created_ts: float = 0.0):
        self.entry_id = entry_id
        self.text = text
        self.vector = vector
        self.metadata = metadata or {}
        self.created_ts = created_ts or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.entry_id,
            "text": self.text,
            "vector": self.vector,
            "metadata": self.metadata,
            "created_ts": self.created_ts,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "VectorEntry":
        return VectorEntry(
            entry_id=d["id"],
            text=d.get("text", ""),
            vector=d.get("vector", []),
            metadata=d.get("metadata", {}),
            created_ts=d.get("created_ts", 0.0),
        )


class SearchResult:
    """Result from vector similarity search."""
    __slots__ = ("entry", "score")

    def __init__(self, entry: VectorEntry, score: float):
        self.entry = entry
        self.score = score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.entry.entry_id,
            "text": self.entry.text,
            "score": round(self.score, 4),
            "metadata": self.entry.metadata,
        }


class VectorStore:
    """In-memory vector store with JSONL persistence.

    Features:
    - Add/remove/update vectors
    - Cosine similarity search with threshold
    - JSONL persistence (MERGE semantics: last record per ID wins)
    - Namespace support (group vectors by source)
    - Cap at MAX_VECTORS to prevent OOM
    """

    def __init__(self, store_path: Optional[str] = None):
        self._path = Path(store_path) if store_path else None
        self._entries: Dict[str, VectorEntry] = {}
        self._dirty_ids: set = set()
        # When evictions or removals happen, append-only save() won't
        # reflect them. Set this flag so the next save() rewrites the
        # whole file instead. Prevents unbounded JSONL growth where
        # ghost entries linger on disk after being evicted from memory.
        self._needs_compaction: bool = False
        # Per-namespace eviction tally since process start. Surfaced in
        # stats() so the eviction policy can be verified on the live
        # store instead of inferred from what happens to be missing.
        self._evicted_by_namespace: Dict[str, int] = {}

    def load(self) -> int:
        """Load vectors from JSONL. Returns count loaded."""
        if not self._path or not self._path.exists():
            return 0

        line_count = 0
        count = 0
        # Vectors written by a PREVIOUS embedder have a different width. They do
        # not raise -- cosine_similarity returns 0.0 on a length mismatch -- so
        # without this guard they would linger forever as unfindable dead weight
        # and quietly eat the MAX_VECTORS budget. Dropping them here lets the
        # indexer re-add them with the current model.
        from agent_core.semantic.embedding_model import expected_dim
        want_dim = expected_dim()
        wrong_dim = 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    line_count += 1
                    try:
                        d = json.loads(line)
                        entry = VectorEntry.from_dict(d)
                        if not entry.vector:  # Skip entries without vectors
                            continue
                        if want_dim and len(entry.vector) != want_dim:
                            wrong_dim += 1
                            continue
                        self._entries[entry.entry_id] = entry
                        count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError as e:
            logger.warning(f"[SEMANTIC] Failed to load vectors: {e}")

        if wrong_dim:
            logger.warning(
                f"[SEMANTIC] Dropped {wrong_dim} vectors with stale width "
                f"(expected {want_dim}-dim) — left over from a previous "
                f"embedding model; re-index to restore them"
            )

        # Cap
        if len(self._entries) > MAX_VECTORS:
            self._evict_oldest(len(self._entries) - MAX_VECTORS)

        self._dirty_ids.clear()

        # Auto-compact if the file is significantly bloated — more than
        # 2x as many records as kept in memory (MERGE duplicates + ghost
        # entries from past evictions).
        kept = len(self._entries)
        if kept > 0 and line_count > 2 * kept:
            logger.info(
                f"[SEMANTIC] File bloated ({line_count} lines vs {kept} active) "
                f"— auto-compacting"
            )
            self.save_full()

        logger.info(f"[SEMANTIC] Loaded {count} vectors from {self._path}")
        return count

    def save(self) -> int:
        """Persist pending changes. Appends dirty entries normally.

        If evictions or removals have occurred (tracked via
        _needs_compaction), performs a full rewrite instead so the
        dropped entries actually disappear from disk.
        """
        if not self._path:
            return 0

        if self._needs_compaction:
            return self.save_full()

        if not self._dirty_ids:
            return 0

        self._path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                for eid in self._dirty_ids:
                    entry = self._entries.get(eid)
                    if entry:
                        line = json.dumps(entry.to_dict(), ensure_ascii=False)
                        f.write(line + "\n")
                        count += 1
            self._dirty_ids.clear()
        except OSError as e:
            logger.warning(f"[SEMANTIC] Failed to save vectors: {e}")

        return count

    def save_full(self) -> int:
        """Rewrite entire JSONL file with current in-memory state.

        Use after removals to persist deletions (normal save is append-only).
        Returns count of entries written.

        Uses a tmp file + atomic rename so a crash mid-write cannot corrupt
        the store.
        """
        if not self._path:
            return 0

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        count = 0
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                # list() snapshot -- concurrent add/remove from another
                # thread must not abort a multi-second 100MB+ rewrite.
                for entry in list(self._entries.values()):
                    line = json.dumps(entry.to_dict(), ensure_ascii=False)
                    f.write(line + "\n")
                    count += 1
            tmp_path.replace(self._path)
            self._dirty_ids.clear()
            self._needs_compaction = False
        except Exception as e:
            # Broad on purpose: whatever failed (OSError, RuntimeError from
            # a race, json error), the .tmp must not stay orphaned and
            # _needs_compaction stays True so a later save retries.
            logger.warning(f"[SEMANTIC] Failed to save_full vectors: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return 0

        return count

    def list_ids_by_namespace(self, namespace: str) -> List[str]:
        """Get all entry IDs in a given namespace."""
        return [
            eid for eid, entry in list(self._entries.items())
            if entry.metadata.get("namespace") == namespace
        ]

    def add(self, entry_id: str, text: str, vector: List[float],
            metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Add or update a vector entry."""
        if not vector:
            return False

        if len(self._entries) >= MAX_VECTORS and entry_id not in self._entries:
            self._evict_oldest(1)

        self._entries[entry_id] = VectorEntry(
            entry_id=entry_id,
            text=text,
            vector=vector,
            metadata=metadata,
        )
        self._dirty_ids.add(entry_id)
        return True

    def add_text(self, entry_id: str, text: str, embedding_model: EmbeddingModel,
                 metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Embed text and add to store in one call."""
        vector = embedding_model.embed(text)
        if not vector:
            return False
        return self.add(entry_id, text, vector, metadata)

    def add_texts_batch(self, entries: List[Tuple[str, str, Optional[Dict]]],
                        embedding_model: EmbeddingModel) -> int:
        """Batch embed and add multiple texts. Returns count added.

        Args:
            entries: List of (entry_id, text, metadata) tuples.
            embedding_model: EmbeddingModel instance.
        """
        # Filter out already-stored entries with same text. Same text means
        # the vector is still valid, but the METADATA may have changed (e.g.
        # the 2026-06-10 belief metadata contract added belief_id/entity to
        # entries indexed without them) -- refresh it in place: no re-embed,
        # created_ts preserved, only the metadata dict is replaced.
        to_embed = []
        for entry_id, text, meta in entries:
            existing = self._entries.get(entry_id)
            if existing and existing.text == text:
                if meta is not None and meta != existing.metadata:
                    existing.metadata = dict(meta)
                    self._dirty_ids.add(entry_id)
                continue  # Already embedded with same text
            to_embed.append((entry_id, text, meta))

        if not to_embed:
            return 0

        texts = [t for _, t, _ in to_embed]
        vectors = embedding_model.embed_batch(texts)

        count = 0
        for i, (entry_id, text, meta) in enumerate(to_embed):
            if vectors[i]:
                self.add(entry_id, text, vectors[i], meta)
                count += 1

        return count

    def remove(self, entry_id: str) -> bool:
        """Remove a vector entry.

        Marks the store for compaction so the next save() rewrites the
        file without this entry (append-only save would leave a ghost
        record on disk that would be reloaded on restart).
        """
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._dirty_ids.discard(entry_id)
            self._needs_compaction = True
            return True
        return False

    def get(self, entry_id: str) -> Optional[VectorEntry]:
        """Get entry by ID."""
        return self._entries.get(entry_id)

    def search(self, query_vector: List[float], top_k: int = 10,
               threshold: float = 0.3,
               namespace: Optional[str] = None) -> List[SearchResult]:
        """Find most similar vectors by cosine similarity.

        Args:
            query_vector: Query embedding.
            top_k: Max results.
            threshold: Minimum cosine similarity (0.0-1.0).
            namespace: Filter by metadata["namespace"] if provided.

        Returns:
            List of SearchResult sorted by score (highest first).
        """
        if not query_vector:
            return []

        results: List[SearchResult] = []
        # list() snapshot: the store is lock-free and the semantic-indexer
        # thread adds/removes entries (ghost cleanup, eviction) while other
        # threads search -- iterating the live view raises RuntimeError
        # (dict changed size). GIL makes the snapshot itself atomic.
        for entry in list(self._entries.values()):
            if not entry.vector:
                continue
            if namespace and entry.metadata.get("namespace") != namespace:
                continue

            score = EmbeddingModel.cosine_similarity(query_vector, entry.vector)
            if score >= threshold:
                results.append(SearchResult(entry, score))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def search_text(self, query: str, embedding_model: EmbeddingModel,
                    top_k: int = 10, threshold: float = 0.3,
                    namespace: Optional[str] = None) -> List[SearchResult]:
        """Embed query and search in one call."""
        query_vec = embedding_model.embed(query)
        return self.search(query_vec, top_k, threshold, namespace)

    def count(self) -> int:
        """Number of stored vectors."""
        return len(self._entries)

    def get_by_namespace(self, namespace: str) -> List[VectorEntry]:
        """Get all entries in a namespace."""
        return [
            e for e in list(self._entries.values())
            if e.metadata.get("namespace") == namespace
        ]

    def stats(self) -> Dict[str, Any]:
        """Store statistics."""
        namespaces: Dict[str, int] = {}
        for e in list(self._entries.values()):
            ns = e.metadata.get("namespace", "default")
            namespaces[ns] = namespaces.get(ns, 0) + 1
        return {
            "total_vectors": len(self._entries),
            "dirty_count": len(self._dirty_ids),
            "namespaces": namespaces,
            "evicted_by_namespace": dict(self._evicted_by_namespace),
        }

    # --- Internal ---

    def _evict_oldest(self, count: int) -> None:
        """Remove entries to make room, cheapest namespace first.

        Order is (EVICTION_PRIORITY[namespace], created_ts): the oldest
        entry of the cheapest non-empty namespace goes first, so the
        high-volume summaries corpus recycles itself instead of crowding
        out beliefs and knowledge (see EVICTION_PRIORITY for the
        measurement that motivated this).

        Always frees exactly `count` slots: when only protected
        namespaces remain there is nothing cheaper to take, and their
        oldest entries are evicted as before -- but that case is logged
        at INFO, because it means the cap itself is too small.

        Marks the store for compaction — next save() will rewrite the
        file so evicted entries actually disappear from disk.
        """
        if count <= 0:
            return
        sorted_entries = sorted(
            self._entries.values(),
            key=lambda e: (_eviction_priority(e), e.created_ts),
        )
        protected_hit: Dict[str, int] = {}
        for entry in sorted_entries[:count]:
            del self._entries[entry.entry_id]
            self._dirty_ids.discard(entry.entry_id)
            ns = entry.metadata.get("namespace", "default")
            self._evicted_by_namespace[ns] = (
                self._evicted_by_namespace.get(ns, 0) + 1
            )
            if ns in _PROTECTED_NAMESPACES:
                protected_hit[ns] = protected_hit.get(ns, 0) + 1
            logger.debug(f"[SEMANTIC] Evicted vector: {entry.entry_id} (ns={ns})")
        if protected_hit:
            logger.info(
                f"[SEMANTIC] Cap pressure: evicted protected vectors "
                f"{protected_hit} — nothing cheaper left at MAX_VECTORS="
                f"{MAX_VECTORS}; raise the cap or index less"
            )
        self._needs_compaction = True
