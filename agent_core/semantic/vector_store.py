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

    def load(self) -> int:
        """Load vectors from JSONL. Returns count loaded."""
        if not self._path or not self._path.exists():
            return 0

        count = 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        entry = VectorEntry.from_dict(d)
                        if entry.vector:  # Skip entries without vectors
                            self._entries[entry.entry_id] = entry
                            count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError as e:
            logger.warning(f"[SEMANTIC] Failed to load vectors: {e}")

        # Cap
        if len(self._entries) > MAX_VECTORS:
            self._evict_oldest(len(self._entries) - MAX_VECTORS)

        self._dirty_ids.clear()
        logger.info(f"[SEMANTIC] Loaded {count} vectors from {self._path}")
        return count

    def save(self) -> int:
        """Append dirty entries to JSONL. Returns count saved."""
        if not self._path or not self._dirty_ids:
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
        """
        if not self._path:
            return 0

        self._path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                for entry in self._entries.values():
                    line = json.dumps(entry.to_dict(), ensure_ascii=False)
                    f.write(line + "\n")
                    count += 1
            self._dirty_ids.clear()
        except OSError as e:
            logger.warning(f"[SEMANTIC] Failed to save_full vectors: {e}")

        return count

    def list_ids_by_namespace(self, namespace: str) -> List[str]:
        """Get all entry IDs in a given namespace."""
        return [
            eid for eid, entry in self._entries.items()
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
        # Filter out already-stored entries with same text
        to_embed = []
        for entry_id, text, meta in entries:
            existing = self._entries.get(entry_id)
            if existing and existing.text == text:
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
        """Remove a vector entry."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._dirty_ids.discard(entry_id)
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
        for entry in self._entries.values():
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
            e for e in self._entries.values()
            if e.metadata.get("namespace") == namespace
        ]

    def stats(self) -> Dict[str, Any]:
        """Store statistics."""
        namespaces: Dict[str, int] = {}
        for e in self._entries.values():
            ns = e.metadata.get("namespace", "default")
            namespaces[ns] = namespaces.get(ns, 0) + 1
        return {
            "total_vectors": len(self._entries),
            "dirty_count": len(self._dirty_ids),
            "namespaces": namespaces,
        }

    # --- Internal ---

    def _evict_oldest(self, count: int) -> None:
        """Remove oldest entries to make room."""
        if count <= 0:
            return
        sorted_entries = sorted(
            self._entries.values(), key=lambda e: e.created_ts
        )
        for entry in sorted_entries[:count]:
            del self._entries[entry.entry_id]
            logger.debug(f"[SEMANTIC] Evicted oldest vector: {entry.entry_id}")
