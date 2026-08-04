"""Embedding model wrapper for the configured embedder via Ollama.

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
import os
import time
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Ollama API
DEFAULT_OLLAMA_URL = "http://localhost:11434"
EMBED_ENDPOINT = "/api/embed"

# Model.
#
# Switched nomic-embed-text -> bge-m3 on 2026-07-25 after measuring retrieval on
# 1500 real Polish entries from this store (28 probe questions, paired):
#   nomic  top-5 hit 42.9%, median rank 42/1500
#   bge-m3 top-5 hit  100%, median rank  1     (21 wins / 0 losses)
# Controls ruled out a measurement artifact: nomic scores 100% R@1 when a
# document searches for ITSELF, so it is called correctly -- it simply cannot
# bridge question -> answer in Polish, which is the only thing this store is
# used for. Hand-written probes agree ("Do czego sluzy RSS?" returned
# linguistics). Cost: bge-m3 is ~2.6x slower per text on this CPU.
#
# Rollback: SEMANTIC_EMBED_MODEL=nomic-embed-text + restart, then re-run the
# re-embed (dimensions differ, so the store must be rebuilt either way).
DEFAULT_MODEL = os.environ.get("SEMANTIC_EMBED_MODEL", "bge-m3")

# Vector width per model. Used by VectorStore to drop entries left over from a
# previous embedder -- a stale-width vector does NOT crash, cosine_similarity
# just returns 0.0, so without this guard old entries survive as permanently
# unfindable dead weight.
_MODEL_DIMS = {
    "bge-m3": 1024,
    "nomic-embed-text": 768,
}


def expected_dim(model: str = "") -> Optional[int]:
    """Vector width for a model, or None if unknown (guard disabled)."""
    name = (model or DEFAULT_MODEL).split(":")[0]
    return _MODEL_DIMS.get(name)


VECTOR_DIM = expected_dim() or 1024

# Mean cosine between two UNRELATED texts, i.e. what a score of "no relationship
# at all" actually looks like for each model. Measured 2026-07-25 over 20k random
# pairs from this project's own store (1500 real Polish entries):
#     nomic-embed-text  mean 0.754, p95 0.817   <- everything crammed high
#     bge-m3            mean 0.401, p95 0.580
# Raw cosine is therefore NOT comparable across models: 0.70 is below chance for
# nomic and well above chance for bge-m3. Anything that compares a similarity
# against a fixed number, or mixes it with weights from other sources, must go
# through relevance_from_cosine() instead of using the raw value.
_MODEL_CHANCE_SIM = {
    "bge-m3": 0.40,
    "nomic-embed-text": 0.75,
}


def chance_similarity(model: str = "") -> float:
    """Cosine expected between unrelated texts for a model (0.0 if unknown)."""
    name = (model or DEFAULT_MODEL).split(":")[0]
    return _MODEL_CHANCE_SIM.get(name, 0.0)


def relevance_from_cosine(score: float, model: str = "") -> float:
    """Rescale a raw cosine to a model-independent 0..1 relevance.

    0.0 means "no better than two unrelated texts", 1.0 means identical. This is
    what callers want when they compare a similarity against a constant or blend
    it with relevance weights from non-semantic sources.
    """
    floor = chance_similarity(model)
    if floor >= 1.0:
        return max(0.0, min(1.0, score))
    return max(0.0, min(1.0, (score - floor) / (1.0 - floor)))

# Limits.
#
# Batch size and read timeout must be sized TOGETHER against measured
# throughput, or the timeout is unreachable by construction. Measured on this
# CPU 2026-07-25: bge-m3 embeds 16 texts of ~800 chars in 33.8s (~2.1 s/text),
# nomic ~0.8 s/text. The old pairing (batch 50, read 30s) needed ~105s of work
# to fit in a 30s budget -- it could only ever time out, and _call_ollama
# swallows that into empty vectors plus a warning, so indexing would silently
# report "0 vectors" instead of failing loudly.
MAX_BATCH_SIZE = 8        # ~17s of work for bge-m3, comfortably inside the read budget
MAX_TEXT_LENGTH = 8192    # context window (nomic and bge-m3 both 8192)
REQUEST_TIMEOUT = (5, 180)  # (connect, read) seconds; read covers a cold model load


class EmbeddingModel:
    """Wrapper for the configured embedding model via Ollama /api/embed.

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
        vec = result[0] if result else []
        # NEVER cache a failure. _call_ollama returns [[]] on timeout/error, and
        # [[]] is truthy with len 1 -- the old code stored that [] under the
        # text's hash, so one timeout permanently blinded every later caller
        # (indexing, dedup, search) for that text: they got [] straight from
        # cache without ever retrying Ollama, and get_stats() counted it as a
        # cached vector, i.e. as success.
        if self._is_usable(vec):
            self._cache[cache_key] = vec
        return vec

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
                    # Same rule as embed(): a failed/short vector must not be
                    # cached, or the whole batch's texts stay poisoned for the
                    # lifetime of the process.
                    if self._is_usable(vec):
                        self._cache[self._cache_key(batch[j])] = vec

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

    def _is_usable(self, vec: List[float]) -> bool:
        """True if a vector is worth caching: non-empty and the right width.

        Width matters because a model swap (SEMANTIC_EMBED_MODEL) must not leave
        vectors of the previous width in the cache -- VectorStore.load() drops
        those on disk, so caching them in memory would just reintroduce them.
        """
        if not vec:
            return False
        want = expected_dim(self._model)
        return want is None or len(vec) == want

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()
