"""Embedding model wrapper for nomic-embed-text via Ollama.

Provides text-to-vector conversion using Ollama's /api/embed endpoint.
Designed for MODEL-05 (MEMORY) in the model registry.

Usage:
    model = EmbeddingModel()
    vec = model.embed("fotosynteza to proces biologiczny")
    vecs = model.embed_batch(["tekst 1", "tekst 2"])
"""

import hashlib
import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Ollama API
DEFAULT_OLLAMA_URL = "http://localhost:11434"
EMBED_ENDPOINT = "/api/embed"

# Model
DEFAULT_MODEL = "nomic-embed-text"
VECTOR_DIM = 768

# Limits
MAX_BATCH_SIZE = 50       # Max texts per batch call
MAX_TEXT_LENGTH = 8192    # nomic-embed-text context window
REQUEST_TIMEOUT = (5, 30)  # (connect, read) seconds


class EmbeddingModel:
    """Wrapper for nomic-embed-text via Ollama /api/embed.

    Features:
    - Single and batch embedding
    - In-memory cache (text hash -> vector)
    - Cosine similarity helper
    - Health tracking (latency, errors)
    """

    def __init__(self, ollama_url: str = "", model: str = DEFAULT_MODEL):
        import os
        self._url = ollama_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL)
        self._model = model
        self._cache: Dict[str, List[float]] = {}

        # Health stats
        self._total_requests: int = 0
        self._total_errors: int = 0
        self._total_latency_ms: float = 0.0

    def embed(self, text: str) -> List[float]:
        """Embed a single text. Returns 768-dim vector or empty list on error."""
        if not text or not text.strip():
            return []

        text = text[:MAX_TEXT_LENGTH]
        cache_key = self._cache_key(text)

        if cache_key in self._cache:
            return self._cache[cache_key]

        result = self._call_ollama([text])
        if result and len(result) > 0:
            vec = result[0]
            self._cache[cache_key] = vec
            return vec
        return []

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts. Returns list of vectors (same order as input).

        Texts already in cache are served from cache. Only uncached texts
        are sent to Ollama.
        """
        if not texts:
            return []

        # Separate cached vs uncached
        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                results[i] = []
                continue
            text = text[:MAX_TEXT_LENGTH]
            key = self._cache_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Batch embed uncached texts
        if uncached_texts:
            for batch_start in range(0, len(uncached_texts), MAX_BATCH_SIZE):
                batch = uncached_texts[batch_start:batch_start + MAX_BATCH_SIZE]
                batch_indices = uncached_indices[batch_start:batch_start + MAX_BATCH_SIZE]
                embeddings = self._call_ollama(batch)

                for j, vec in enumerate(embeddings):
                    idx = batch_indices[j]
                    results[idx] = vec
                    key = self._cache_key(batch[j])
                    self._cache[key] = vec

        # Fill any remaining None with empty
        return [r if r is not None else [] for r in results]

    def is_available(self) -> bool:
        """Check if embedding model is loaded in Ollama."""
        try:
            resp = requests.get(
                f"{self._url}/api/tags",
                timeout=(3, 5),
            )
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return any(self._model in m.get("name", "") for m in models)
        except Exception:
            pass
        return False

    def get_stats(self) -> Dict:
        """Return health/usage statistics."""
        avg_latency = (
            self._total_latency_ms / self._total_requests
            if self._total_requests > 0 else 0
        )
        return {
            "model": self._model,
            "cached_vectors": len(self._cache),
            "total_requests": self._total_requests,
            "total_errors": self._total_errors,
            "avg_latency_ms": round(avg_latency, 1),
        }

    def clear_cache(self) -> int:
        """Clear embedding cache. Returns number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    # --- Static helpers ---

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # --- Internal ---

    def _call_ollama(self, texts: List[str]) -> List[List[float]]:
        """Call Ollama /api/embed endpoint."""
        self._total_requests += 1
        start = time.time()

        try:
            resp = requests.post(
                f"{self._url}{EMBED_ENDPOINT}",
                json={"model": self._model, "input": texts},
                timeout=REQUEST_TIMEOUT,
            )
            elapsed_ms = (time.time() - start) * 1000
            self._total_latency_ms += elapsed_ms

            if resp.status_code != 200:
                self._total_errors += 1
                logger.warning(
                    f"[SEMANTIC] Ollama embed error {resp.status_code}: {resp.text[:200]}"
                )
                return [[] for _ in texts]

            data = resp.json()
            embeddings = data.get("embeddings", [])

            if len(embeddings) != len(texts):
                logger.warning(
                    f"[SEMANTIC] Expected {len(texts)} embeddings, got {len(embeddings)}"
                )
                # Pad with empty
                while len(embeddings) < len(texts):
                    embeddings.append([])

            logger.debug(
                f"[SEMANTIC] Embedded {len(texts)} texts in {elapsed_ms:.0f}ms"
            )
            return embeddings

        except requests.exceptions.ConnectionError:
            self._total_errors += 1
            logger.warning("[SEMANTIC] Ollama not reachable for embeddings")
            return [[] for _ in texts]
        except Exception as e:
            self._total_errors += 1
            logger.warning(f"[SEMANTIC] Embed error: {e}")
            return [[] for _ in texts]

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()
