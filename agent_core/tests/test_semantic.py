"""Tests for Semantic Memory module (nomic-embed-text).

Covers:
1. EmbeddingModel - embed, batch, cache, similarity
2. VectorStore - add, search, persist, eviction
3. SemanticMemory facade - index, search, namespaces
4. TopicSuggester semantic reranking
5. MemoryRetriever semantic retrieval
"""

import json
import math
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.semantic.embedding_model import EmbeddingModel
from agent_core.semantic.vector_store import VectorStore, VectorEntry, SearchResult
from agent_core.semantic import SemanticMemory
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.creative.creative_store import CreativeStore
from agent_core.creative.conversation_memory import CreativeConversationMemory
from agent_core.tests.spec_helpers import specced


# =========================================================================
# Test helpers
# =========================================================================

def _fake_vector(dim=768, seed=1.0):
    """Generate a deterministic fake vector."""
    import math
    return [math.sin(i * seed) for i in range(dim)]


def _mock_embedding_model(vectors=None):
    """Create a mock EmbeddingModel that returns predictable vectors."""
    model = specced(EmbeddingModel)
    call_count = [0]

    def fake_embed(text):
        call_count[0] += 1
        if vectors and text in vectors:
            return vectors[text]
        # Generate deterministic vector from text hash
        seed = sum(ord(c) for c in text) / 100.0
        return _fake_vector(seed=seed)

    def fake_embed_batch(texts):
        return [fake_embed(t) for t in texts]

    model.embed = MagicMock(side_effect=fake_embed)
    model.embed_batch = MagicMock(side_effect=fake_embed_batch)
    model.is_available = MagicMock(return_value=True)
    model.cosine_similarity = EmbeddingModel.cosine_similarity
    model.get_stats = MagicMock(return_value={"cached_vectors": 0})
    return model


# =========================================================================
# 1. EmbeddingModel
# =========================================================================

class TestEmbeddingModel:
    def test_cosine_similarity_identical(self):
        v = [1.0, 2.0, 3.0]
        assert abs(EmbeddingModel.cosine_similarity(v, v) - 1.0) < 0.001

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(EmbeddingModel.cosine_similarity(a, b)) < 0.001

    def test_cosine_similarity_opposite(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(EmbeddingModel.cosine_similarity(a, b) + 1.0) < 0.001

    def test_cosine_similarity_empty(self):
        assert EmbeddingModel.cosine_similarity([], [1.0]) == 0.0
        assert EmbeddingModel.cosine_similarity([1.0], []) == 0.0

    def test_cache_key_deterministic(self):
        k1 = EmbeddingModel._cache_key("hello")
        k2 = EmbeddingModel._cache_key("hello")
        k3 = EmbeddingModel._cache_key("world")
        assert k1 == k2
        assert k1 != k3

    def test_embed_caches_result(self):
        model = EmbeddingModel()
        vec = _fake_vector(seed=1.0)

        with patch.object(model, '_call_ollama', return_value=[vec]) as mock_call:
            result1 = model.embed("test text")
            result2 = model.embed("test text")

            assert result1 == vec
            assert result2 == vec
            assert mock_call.call_count == 1  # Second call served from cache

    def test_embed_empty_text(self):
        model = EmbeddingModel()
        assert model.embed("") == []
        assert model.embed("   ") == []

    def test_embed_batch_uses_cache(self):
        model = EmbeddingModel()
        v1 = _fake_vector(seed=1.0)
        v2 = _fake_vector(seed=2.0)

        with patch.object(model, '_call_ollama') as mock_call:
            # First call: both uncached
            mock_call.return_value = [v1, v2]
            results = model.embed_batch(["text1", "text2"])
            assert len(results) == 2
            assert mock_call.call_count == 1

            # Second call: both cached
            results2 = model.embed_batch(["text1", "text2"])
            assert results2 == results
            assert mock_call.call_count == 1  # No new call

    def test_clear_cache(self):
        model = EmbeddingModel()
        model._cache["key1"] = [1.0]
        model._cache["key2"] = [2.0]
        assert model.clear_cache() == 2
        assert len(model._cache) == 0

    def test_get_stats(self):
        model = EmbeddingModel()
        stats = model.get_stats()
        assert stats["model"] == "nomic-embed-text"
        assert stats["cached_vectors"] == 0
        assert stats["total_requests"] == 0


# =========================================================================
# 2. VectorStore
# =========================================================================

class TestVectorStore:
    def test_add_and_get(self):
        store = VectorStore()
        vec = _fake_vector()
        assert store.add("id1", "test text", vec) is True
        entry = store.get("id1")
        assert entry is not None
        assert entry.text == "test text"
        assert entry.vector == vec

    def test_add_empty_vector_rejected(self):
        store = VectorStore()
        assert store.add("id1", "test", []) is False

    def test_search_finds_similar(self):
        store = VectorStore()
        v1 = _fake_vector(seed=1.0)
        v2 = _fake_vector(seed=1.01)  # Very similar to v1
        v3 = _fake_vector(seed=5.0)   # Different

        store.add("id1", "text1", v1)
        store.add("id2", "text2", v2)
        store.add("id3", "text3", v3)

        results = store.search(v1, top_k=3, threshold=0.0)
        assert len(results) == 3
        # id1 should be most similar (exact match)
        assert results[0].entry.entry_id == "id1"
        assert results[0].score > 0.99

    def test_search_threshold(self):
        store = VectorStore()
        store.add("id1", "text1", [1.0, 0.0])
        store.add("id2", "text2", [0.0, 1.0])

        # High threshold should exclude orthogonal vectors
        results = store.search([1.0, 0.0], threshold=0.9)
        assert len(results) == 1
        assert results[0].entry.entry_id == "id1"

    def test_search_namespace(self):
        store = VectorStore()
        v = _fake_vector()
        store.add("k1", "knowledge", v, {"namespace": "knowledge"})
        store.add("m1", "memory", v, {"namespace": "memories"})

        results = store.search(v, namespace="knowledge")
        assert len(results) == 1
        assert results[0].entry.entry_id == "k1"

    def test_count(self):
        store = VectorStore()
        assert store.count() == 0
        store.add("id1", "t", [1.0])
        assert store.count() == 1

    def test_remove(self):
        store = VectorStore()
        store.add("id1", "t", [1.0])
        assert store.remove("id1") is True
        assert store.get("id1") is None
        assert store.remove("nonexistent") is False

    def test_persistence_save_load(self, tmp_path):
        path = str(tmp_path / "vectors.jsonl")
        store = VectorStore(path)
        v = _fake_vector()
        store.add("id1", "text1", v, {"namespace": "test"})
        store.save()

        # Load in new store instance
        store2 = VectorStore(path)
        count = store2.load()
        assert count == 1
        entry = store2.get("id1")
        assert entry.text == "text1"
        assert entry.metadata["namespace"] == "test"

    def test_persistence_merge_semantics(self, tmp_path):
        path = str(tmp_path / "vectors.jsonl")
        store = VectorStore(path)
        store.add("id1", "v1", [1.0])
        store.save()
        store.add("id1", "v1_updated", [2.0])  # Update same ID
        store.save()

        store2 = VectorStore(path)
        store2.load()
        # Last record wins
        assert store2.get("id1").text == "v1_updated"

    def test_add_text_delegates_to_model(self):
        store = VectorStore()
        model = _mock_embedding_model()
        assert store.add_text("id1", "some text", model) is True
        model.embed.assert_called_once_with("some text")
        assert store.count() == 1

    def test_add_texts_batch(self):
        store = VectorStore()
        model = _mock_embedding_model()
        entries = [
            ("id1", "text one", None),
            ("id2", "text two", None),
        ]
        count = store.add_texts_batch(entries, model)
        assert count == 2
        model.embed_batch.assert_called_once()

    def test_add_texts_batch_skips_existing(self):
        store = VectorStore()
        model = _mock_embedding_model()
        store.add("id1", "text one", _fake_vector())

        entries = [
            ("id1", "text one", None),  # Already exists with same text
            ("id2", "text two", None),
        ]
        count = store.add_texts_batch(entries, model)
        assert count == 1  # Only id2 embedded

    def test_search_text(self):
        store = VectorStore()
        model = _mock_embedding_model()

        # Add via model
        store.add_text("id1", "fotosynteza", model)

        # Search via model
        results = store.search_text("fotosynteza", model, threshold=0.0)
        assert len(results) >= 1

    def test_eviction_on_cap(self):
        store = VectorStore()
        # Temporarily lower cap for testing
        import agent_core.semantic.vector_store as vs
        old_cap = vs.MAX_VECTORS
        vs.MAX_VECTORS = 3

        try:
            for i in range(5):
                store.add(f"id{i}", f"text{i}", [float(i)])
                time.sleep(0.01)  # Ensure different timestamps
            assert store.count() == 3
        finally:
            vs.MAX_VECTORS = old_cap

    def test_stats(self):
        store = VectorStore()
        store.add("k1", "t", [1.0], {"namespace": "knowledge"})
        store.add("m1", "t", [1.0], {"namespace": "memories"})
        stats = store.stats()
        assert stats["total_vectors"] == 2
        assert stats["namespaces"]["knowledge"] == 1
        assert stats["namespaces"]["memories"] == 1

    # --- 2026-04-17 regression: ghost entries on disk after eviction/removal ---

    def test_remove_rewrites_file_on_save(self, tmp_path):
        """remove() + save() must drop the record from disk, not leave a ghost."""
        path = str(tmp_path / "vectors.jsonl")
        store = VectorStore(path)
        store.add("id1", "keep", _fake_vector())
        store.add("id2", "drop", _fake_vector())
        store.save()
        assert store.remove("id2") is True
        store.save()

        store2 = VectorStore(path)
        count = store2.load()
        assert count == 1
        assert store2.get("id1") is not None
        assert store2.get("id2") is None

    def test_eviction_rewrites_file_on_save(self, tmp_path):
        """When _evict_oldest fires, next save() must rewrite the file so the
        evicted entries don't come back on restart."""
        path = str(tmp_path / "vectors.jsonl")
        import agent_core.semantic.vector_store as vs
        old_cap = vs.MAX_VECTORS
        vs.MAX_VECTORS = 3
        try:
            store = VectorStore(path)
            for i in range(3):
                store.add(f"id{i}", f"text{i}", [float(i)])
                time.sleep(0.01)
            store.save()
            # Fourth add triggers eviction of oldest (id0)
            store.add("id3", "text3", [3.0])
            store.save()

            store2 = VectorStore(path)
            count = store2.load()
            assert count == 3
            ids = {e.entry_id for e in store2._entries.values()}
            assert "id0" not in ids, "Evicted entry should not be on disk"
            assert "id3" in ids
        finally:
            vs.MAX_VECTORS = old_cap

    def test_load_autocompacts_bloated_file(self, tmp_path):
        """If the JSONL has many duplicates/ghosts relative to active count,
        load() should auto-compact the file to match memory state."""
        path = tmp_path / "vectors.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            # One active entry repeated 100 times (MERGE keeps last)
            for i in range(100):
                f.write(json.dumps({
                    "id": "x",
                    "text": f"rev{i}",
                    "vector": [float(i)],
                    "metadata": {},
                    "created_ts": float(i),
                }) + "\n")

        size_before = path.stat().st_size
        store = VectorStore(str(path))
        store.load()
        size_after = path.stat().st_size

        # MERGE semantics: 100 lines of same ID collapse to 1 entry
        assert store.count() == 1
        assert store.get("x").text == "rev99"  # last record wins
        # File shrunk significantly — auto-compact fired
        lines_after = sum(1 for line in path.read_text().splitlines() if line.strip())
        assert lines_after == 1
        assert size_after < size_before // 10

    def test_save_full_uses_atomic_rename(self, tmp_path):
        """save_full() should write via tmp + rename to survive crashes."""
        path = tmp_path / "vectors.jsonl"
        store = VectorStore(str(path))
        store.add("id1", "t", _fake_vector())
        store.save_full()
        assert path.exists()
        # No leftover tmp file
        tmp = path.with_suffix(path.suffix + ".tmp")
        assert not tmp.exists()


# =========================================================================
# 3. SemanticMemory facade
# =========================================================================

class TestSemanticMemory:
    def test_index_and_search(self, tmp_path):
        sm = SemanticMemory(data_dir=str(tmp_path))
        # Replace model with mock
        sm._model = _mock_embedding_model()
        sm._initialized = True

        sm.index_text("knowledge", "bio1", "fotosynteza u roslin")
        sm.index_text("knowledge", "bio2", "chemia organiczna")
        sm.index_text("memories", "mem1", "operator mowil o fizyce")

        # Search all namespaces
        results = sm.search("biologia roslin", threshold=0.0)
        assert len(results) >= 1

        # Search knowledge only
        results_k = sm.search("biologia", namespace="knowledge", threshold=0.0)
        assert all(r.entry.metadata.get("namespace") == "knowledge" for r in results_k)

    def test_index_batch(self, tmp_path):
        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = _mock_embedding_model()
        sm._initialized = True

        entries = [
            ("t1", "temat jeden"),
            ("t2", "temat dwa"),
            ("t3", "temat trzy"),
        ]
        count = sm.index_batch("knowledge", entries)
        assert count == 3
        assert sm.store.count() == 3

    def test_find_similar(self, tmp_path):
        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = _mock_embedding_model()
        sm._initialized = True

        sm.index_text("knowledge", "bio1", "fotosynteza")
        sm.index_text("knowledge", "bio2", "fotosynteza u roslin")

        results = sm.find_similar("bio1", threshold=0.0)
        # Should find bio2 but not bio1 itself
        assert all(r.entry.entry_id != "bio1" for r in results)

    def test_save_and_reload(self, tmp_path):
        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = _mock_embedding_model()
        sm.index_text("knowledge", "id1", "test text")
        sm.save()

        sm2 = SemanticMemory(data_dir=str(tmp_path))
        sm2._model = _mock_embedding_model()
        sm2.initialize()
        assert sm2.store.count() == 1

    def test_get_stats(self, tmp_path):
        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = _mock_embedding_model()
        stats = sm.get_stats()
        assert "model" in stats
        assert "store" in stats

    def test_remove(self, tmp_path):
        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = _mock_embedding_model()
        sm.index_text("knowledge", "id1", "test")
        assert sm.remove("id1") is True
        assert sm.store.count() == 0


# =========================================================================
# 4. TopicSuggester with semantic reranking
# =========================================================================

class TestTopicSuggesterSemantic:
    def _make_suggester(self, topics=None, tags=None):
        from agent_core.web_source.topic_suggester import TopicSuggester
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_topic_file_map.return_value = topics or {"fizyka": ["f1", "f2"]}
        analyzer.get_tag_frequency_map.return_value = tags or {}
        return TopicSuggester(analyzer, project_root="/tmp/nonexistent")

    def test_without_semantic_returns_normal_order(self):
        suggester = self._make_suggester(
            topics={"fizyka": ["f1", "f2"], "biologia": ["b1"]}
        )
        results = suggester.suggest_topics()
        assert len(results) > 0
        # No novelty/rank_score fields without semantic
        assert "novelty" not in results[0]

    def test_with_semantic_adds_novelty_scores(self, tmp_path):
        suggester = self._make_suggester(
            topics={"fizyka": ["f1", "f2"], "biologia": ["b1"]}
        )
        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = _mock_embedding_model()
        sm._initialized = True
        # Index some knowledge so search returns results
        sm.index_text("knowledge", "k1", "fizyka kwantowa")

        suggester.set_semantic_memory(sm)
        results = suggester.suggest_topics()
        assert len(results) > 0
        # Should have novelty scores
        assert "novelty" in results[0]
        assert "rank_score" in results[0]

    def test_semantic_rerank_graceful_on_error(self):
        """Semantic rerank should not crash suggest_topics on error."""
        suggester = self._make_suggester(topics={"fizyka": ["f1"]})
        # Mock semantic_memory that raises
        sm = specced(SemanticMemory)
        sm.search = MagicMock(side_effect=RuntimeError("model unavailable"))
        suggester.set_semantic_memory(sm)

        results = suggester.suggest_topics()
        assert len(results) > 0  # Fallback to original order


# =========================================================================
# 5. MemoryRetriever with semantic retrieval
# =========================================================================

class TestMemoryRetrieverSemantic:
    def test_without_semantic_uses_keywords(self):
        from agent_core.creative.memory_retriever import MemoryRetriever
        from agent_core.creative.creative_model import DetectedTension, TensionCategory
        store = specced(CreativeStore)
        retriever = MemoryRetriever(store)
        # Replace conv_memory with mock to verify it's called
        mock_conv = specced(CreativeConversationMemory)
        mock_conv.retrieve_relevant = MagicMock(return_value=[])
        retriever._conv_memory = mock_conv

        tension = DetectedTension.create(
            category=TensionCategory.REPETITION,
            description="System jest w petli NOOP",
            severity=0.9,
            evidence_refs=["e1"],
        )
        # Should use keyword retrieval (no semantic)
        retriever.retrieve_for_session([tension], {})
        mock_conv.retrieve_relevant.assert_called_once()

    def test_with_semantic_uses_embedding_search(self, tmp_path):
        from agent_core.creative.memory_retriever import MemoryRetriever
        from agent_core.creative.creative_model import DetectedTension, TensionCategory
        store = specced(CreativeStore)
        retriever = MemoryRetriever(store)

        # Use consistent vectors so search actually finds results
        same_vec = _fake_vector(seed=1.0)
        model = _mock_embedding_model(vectors={
            "operator mowil o stagnacji systemu": same_vec,
            "System jest w petli NOOP": same_vec,  # Same vector = high similarity
        })

        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = model
        sm._initialized = True
        sm.index_text("memories", "mem1", "operator mowil o stagnacji systemu")

        retriever.set_semantic_memory(sm)

        tension = DetectedTension.create(
            category=TensionCategory.REPETITION,
            description="System jest w petli NOOP",
            severity=0.9,
            evidence_refs=["e1"],
        )
        results = retriever.retrieve_for_session([tension], {})
        assert len(results) >= 1
        assert results[0]["source"] == "semantic"

    def test_semantic_fallback_on_empty_results(self, tmp_path):
        from agent_core.creative.memory_retriever import MemoryRetriever
        from agent_core.creative.creative_model import DetectedTension, TensionCategory
        store = specced(CreativeStore)
        retriever = MemoryRetriever(store)

        sm = SemanticMemory(data_dir=str(tmp_path))
        sm._model = _mock_embedding_model()
        sm._initialized = True
        # Empty store -> no results -> fallback to keywords

        retriever.set_semantic_memory(sm)

        tension = DetectedTension.create(
            category=TensionCategory.STAGNATION,
            description="Zero progress",
            severity=0.7,
            evidence_refs=["e1"],
        )
        # Will try semantic (empty), then fall back to keyword
        retriever.retrieve_for_session([tension], {})


# =========================================================================
# 6. VectorEntry serialization
# =========================================================================

class TestVectorEntry:
    def test_to_dict_roundtrip(self):
        entry = VectorEntry("id1", "test", [1.0, 2.0], {"ns": "k"}, 12345.0)
        d = entry.to_dict()
        restored = VectorEntry.from_dict(d)
        assert restored.entry_id == "id1"
        assert restored.text == "test"
        assert restored.vector == [1.0, 2.0]
        assert restored.metadata == {"ns": "k"}
        assert restored.created_ts == 12345.0

    def test_search_result_to_dict(self):
        entry = VectorEntry("id1", "test text", [1.0])
        result = SearchResult(entry, 0.95)
        d = result.to_dict()
        assert d["id"] == "id1"
        assert d["score"] == 0.95
        assert d["text"] == "test text"
