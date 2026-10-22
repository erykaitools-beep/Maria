"""Bounded embedding reuse; no Ollama, network or production memory writes."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_core.semantic.embedding_model import (
    MAX_CACHE_ENTRIES, EmbeddingModel, expected_dim,
)
from agent_core.semantic.vector_store import VectorStore


def _vector():
    return [1.0] + [0.0] * (expected_dim() - 1)


def _provider(monkeypatch, model):
    calls = []
    vector = _vector()

    def embed(texts, cancel_event=None):
        calls.append(list(texts))
        return [vector for _ in texts]

    monkeypatch.setattr(model, "_call_ollama", embed)
    return calls, vector


def test_default_cache_is_bounded_after_more_unique_texts(monkeypatch):
    model = EmbeddingModel()
    _, vector = _provider(monkeypatch, model)
    texts = [f"text {i}" for i in range(MAX_CACHE_ENTRIES + 3)]
    assert model.embed_batch(texts) == [vector] * len(texts)
    stats = model.get_stats()
    assert stats["cached_vectors"] == MAX_CACHE_ENTRIES
    assert stats["cache_evictions"] == 3


def test_single_hit_keeps_recent_text_and_evicted_text_can_be_recomputed(monkeypatch):
    model = EmbeddingModel(max_cache_entries=2)
    calls, vector = _provider(monkeypatch, model)
    model.embed("a")
    model.embed("b")
    model.embed("a")  # Reuse a; b is now the least recently used entry.
    model.embed("c")
    assert model.embed("a") == vector
    assert calls == [["a"], ["b"], ["c"]]
    assert model.embed("b") == vector
    assert calls[-1] == ["b"]
    assert model.get_stats()["cached_vectors"] == 2


def test_batch_hit_refreshes_reuse_priority(monkeypatch):
    model = EmbeddingModel(max_cache_entries=2)
    calls, vector = _provider(monkeypatch, model)
    model.embed_batch(["a", "b"])
    assert model.embed_batch(["a", "c"]) == [vector, vector]
    assert model.embed("a") == vector
    assert calls == [["a", "b"], ["c"]]
    model.embed("b")
    assert calls[-1] == ["b"]


def test_batch_larger_than_cache_preserves_result_order(monkeypatch):
    model = EmbeddingModel(max_cache_entries=1)
    vectors = [[float(i), 1.0] + [0.0] * (expected_dim() - 2)
               for i in range(12)]
    by_text = {f"t{i}": v for i, v in enumerate(vectors)}

    def embed(texts, cancel_event=None):
        return [by_text[t] for t in texts]

    monkeypatch.setattr(model, "_call_ollama", embed)
    assert model.embed_batch(list(by_text)) == vectors
    assert model.get_stats()["cached_vectors"] == 1
    assert model.get_stats()["cache_evictions"] == 11


@pytest.mark.parametrize("batch", [False, True])
def test_failed_embedding_does_not_evict_a_valid_cached_entry(monkeypatch, batch):
    model = EmbeddingModel(max_cache_entries=1)
    calls, vector = _provider(monkeypatch, model)
    model.embed("valid")

    def failed(texts, cancel_event=None):
        return [[] for _ in texts]

    monkeypatch.setattr(model, "_call_ollama", failed)
    result = model.embed_batch(["failed"]) if batch else model.embed("failed")
    assert result == ([[]] if batch else [])
    assert model.embed("valid") == vector
    assert calls == [["valid"]]
    assert model.get_stats()["cache_evictions"] == 0


def test_cache_eviction_preserves_stored_memory_and_reload(monkeypatch, tmp_path):
    model = EmbeddingModel(max_cache_entries=1)
    _, vector = _provider(monkeypatch, model)
    path = tmp_path / "vectors.jsonl"
    store = VectorStore(str(path))
    assert store.add_text("knowledge:room", "room", model, {"namespace": "knowledge"})
    assert store.save() == 1
    original_bytes = path.read_bytes()
    model.embed("another text")  # Evicts only the cache reference to room.
    assert model.get_stats()["cache_evictions"] == 1
    assert store.get("knowledge:room").vector == vector
    assert store.search(vector, namespace="knowledge")[0].entry.entry_id == "knowledge:room"
    assert path.read_bytes() == original_bytes
    restored = VectorStore(str(path))
    assert restored.load() == 1
    assert restored.search(vector)[0].entry.entry_id == "knowledge:room"


def test_parallel_users_keep_cache_bounded_without_locking_inference(monkeypatch):
    model = EmbeddingModel(max_cache_entries=2)
    barrier = threading.Barrier(8)
    vector = _vector()

    def embed(texts, cancel_event=None):
        barrier.wait(timeout=3)
        return [vector for _ in texts]

    monkeypatch.setattr(model, "_call_ollama", embed)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(model.embed, [f"parallel {i}" for i in range(8)]))
    assert results == [vector] * 8
    assert model.get_stats()["cached_vectors"] == 2
    assert model.get_stats()["cache_evictions"] == 6
    assert model.clear_cache() == 2


@pytest.mark.parametrize("limit", [0, -1, 1.5])
def test_invalid_cache_limit_is_reported(limit):
    with pytest.raises(ValueError, match="positive integer"):
        EmbeddingModel(max_cache_entries=limit)
