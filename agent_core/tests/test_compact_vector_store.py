import json
import random
import sys

from agent_core.semantic.embedding_model import EmbeddingModel
from agent_core.semantic.vector_store import VectorEntry, VectorStore


def reference(store, query, threshold, namespace=None, top_k=10):
    results = []
    for entry in store._entries.values():
        if not entry.vector or namespace and entry.metadata.get("namespace") != namespace:
            continue
        score = EmbeddingModel.cosine_similarity(query, entry.vector)
        if score >= threshold:
            results.append((entry.entry_id, score))
    return sorted(results, key=lambda row: row[1], reverse=True)[:top_k]


def test_compact_storage_preserves_every_float_and_copies_input():
    values = [0.1, -1e-250, 1.0000000000000002] * 342
    original = list(values)
    entry = VectorEntry("id", "text", values)
    values[0] = 999
    returned = entry.vector
    returned[1] = 999
    assert entry.vector == original
    assert json.loads(json.dumps(entry.to_dict()))["vector"] == original
    old_bytes = sys.getsizeof(original) + sum(sys.getsizeof(v) for v in original)
    assert sys.getsizeof(entry._vector) < old_bytes / 3


def test_paired_search_exact_scores_top_k_threshold_namespace_and_ties():
    rng = random.Random(23)
    store = VectorStore()
    for i in range(120):
        store.add(str(i), "tekst", [rng.uniform(-1, 1) for _ in range(32)],
                  {"namespace": "beliefs" if i % 2 else "summaries"})
    store.add("zero", "zero", [0.0] * 32)
    store.add("wrong_width", "old", [1.0])
    tied = store.get("3").vector
    store.add("tie", "same", tied, {"namespace": "beliefs"})
    queries = [tied, [0.0] * 32] + [[rng.uniform(-1, 1) for _ in range(32)] for _ in range(8)]
    for query in queries:
        for namespace in (None, "beliefs", "summaries", "missing"):
            scores = reference(store, query, -1, namespace, 200)
            thresholds = [-1, 0, 0.3, 1] + [s for _, s in scores[:4]]
            for threshold in thresholds:
                expected = reference(store, query, threshold, namespace)
                actual = [(r.entry.entry_id, r.score) for r in store.search(
                    query, threshold=threshold, namespace=namespace)]
                assert actual == expected


def test_update_remove_save_and_reload_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_core.semantic.embedding_model.expected_dim", lambda: 2)
    path = tmp_path / "vectors.jsonl"
    store = VectorStore(str(path))
    store.add("person", "osoba", [0.1, 0.2], {"namespace": "beliefs"})
    store.add("old", "stare", [1, 0])
    store.save()
    store.add("person", "osoba przy biurku", [0.2, 0.1], {"namespace": "beliefs"})
    store.remove("old")
    store.save()
    restored = VectorStore(str(path))
    assert restored.load() == 1
    assert restored.get("person").vector == [0.2, 0.1]
    assert restored.search([0.2, 0.1])[0].entry.text == "osoba przy biurku"
    assert restored.stats()["vector_payload_bytes"] == 16
