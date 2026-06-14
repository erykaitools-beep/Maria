"""Semantic Memory module for M.A.R.I.A.

Provides embedding-based similarity search using nomic-embed-text via Ollama.
Replaces keyword-based retrieval with vector similarity.

Components:
    EmbeddingModel - Ollama wrapper for nomic-embed-text
    VectorStore    - In-memory vector store with JSONL persistence
    SemanticMemory - Facade combining model + store + namespaces

Namespaces:
    "knowledge"  - Learning material topics (from knowledge_index.jsonl)
    "hints"      - Topic hints from K12 Self-Analysis
    "memories"   - Operator dialogue memories (from creative conversation_memory)
    "beliefs"    - World model beliefs (from K6)

Usage:
    from agent_core.semantic import SemanticMemory

    sm = SemanticMemory(data_dir="meta_data")
    sm.index_text("knowledge", "bio_01", "Fotosynteza u roslin")
    results = sm.search("procesy biologiczne roslin", namespace="knowledge")
    for r in results:
        print(f"{r.score:.2f} {r.entry.text}")
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from agent_core.semantic.embedding_model import EmbeddingModel
from agent_core.semantic.vector_store import VectorStore, SearchResult, VectorEntry

__all__ = [
    "EmbeddingModel", "VectorStore", "VectorEntry", "SearchResult",
    "SemanticMemory",
]

logger = logging.getLogger(__name__)


class SemanticMemory:
    """Facade for semantic memory operations.

    Combines EmbeddingModel + VectorStore with namespace-aware indexing.
    Designed for late-wiring (model can be set after init).
    """

    def __init__(self, data_dir: str = "meta_data", ollama_url: str = ""):
        self._model = EmbeddingModel(ollama_url=ollama_url)
        self._store = VectorStore(f"{data_dir}/semantic_vectors.jsonl")
        self._initialized = False

    def initialize(self) -> bool:
        """Load persisted vectors. Call once at startup.

        Returns True if model is available and vectors loaded.
        """
        loaded = self._store.load()
        available = self._model.is_available()
        self._initialized = True
        logger.info(
            f"[SEMANTIC] Initialized: {loaded} vectors loaded, "
            f"model available={available}"
        )
        return available

    # --- Indexing ---

    def index_text(self, namespace: str, entry_id: str, text: str,
                   metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Embed and store a single text.

        Args:
            namespace: Category (knowledge, hints, memories, beliefs).
            entry_id: Unique ID for this entry.
            text: Text to embed.
            metadata: Extra data stored alongside the vector.
        """
        meta = metadata or {}
        meta["namespace"] = namespace
        return self._store.add_text(entry_id, text, self._model, meta)

    def index_batch(self, namespace: str,
                    entries: List[Tuple],
                    extra_metadata: Optional[Dict[str, Any]] = None) -> int:
        """Embed and store multiple texts. Returns count indexed.

        Args:
            namespace: Category for all entries.
            entries: List of (entry_id, text) tuples, or (entry_id, text,
                metadata) triples for per-entry metadata (e.g. the belief
                indexer attaching belief_id/entity for dedup resolution).
            extra_metadata: Shared metadata for all entries.
        """
        batch = []
        for item in entries:
            entry_id, text = item[0], item[1]
            per_entry = item[2] if len(item) > 2 and item[2] else {}
            meta = dict(extra_metadata) if extra_metadata else {}
            meta.update(per_entry)
            meta["namespace"] = namespace
            batch.append((entry_id, text, meta))

        count = self._store.add_texts_batch(batch, self._model)
        if count > 0:
            logger.info(
                f"[SEMANTIC] Indexed {count}/{len(entries)} texts "
                f"in namespace '{namespace}'"
            )
        return count

    # --- Search ---

    def search(self, query: str, namespace: Optional[str] = None,
               top_k: int = 10, threshold: float = 0.3) -> List[SearchResult]:
        """Search for similar texts by meaning.

        Args:
            query: Search query text.
            namespace: Filter by namespace (None = search all).
            top_k: Max results.
            threshold: Min cosine similarity (0.0-1.0).

        Returns:
            List of SearchResult sorted by similarity score.
        """
        return self._store.search_text(
            query, self._model, top_k, threshold, namespace
        )

    def find_similar(self, entry_id: str, namespace: Optional[str] = None,
                     top_k: int = 5, threshold: float = 0.5) -> List[SearchResult]:
        """Find entries similar to an existing entry.

        Args:
            entry_id: ID of the reference entry.
            namespace: Filter results by namespace.
            top_k: Max results (excludes the reference entry).
            threshold: Min cosine similarity.
        """
        entry = self._store.get(entry_id)
        if not entry or not entry.vector:
            return []

        results = self._store.search(
            entry.vector, top_k + 1, threshold, namespace
        )
        # Exclude the reference entry itself
        return [r for r in results if r.entry.entry_id != entry_id][:top_k]

    # --- Management ---

    def remove(self, entry_id: str) -> bool:
        """Remove an entry from the store."""
        return self._store.remove(entry_id)

    def save(self) -> int:
        """Persist dirty entries to JSONL."""
        return self._store.save()

    def get_stats(self) -> Dict[str, Any]:
        """Combined stats from model + store."""
        return {
            "model": self._model.get_stats(),
            "store": self._store.stats(),
            "initialized": self._initialized,
        }

    @property
    def model(self) -> EmbeddingModel:
        """Direct access to embedding model (for advanced use)."""
        return self._model

    @property
    def store(self) -> VectorStore:
        """Direct access to vector store (for advanced use)."""
        return self._store

    @property
    def available(self) -> bool:
        """Check if semantic memory is usable."""
        return self._initialized and self._model.is_available()
