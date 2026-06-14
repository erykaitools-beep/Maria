"""
Regression tests for the 2026-06-10 (evening #3) semantic-dedup chain fixes.

The Etap 2 recon found semantic belief dedup was DOUBLY dead in production
despite a populated "beliefs" namespace (6522 vectors since 2026-05-01):

1. Metadata contract: the startup indexer wrote only {"namespace": "beliefs"}
   while find_semantic_duplicates required metadata["belief_id"] -> every hit
   unresolvable, [] forever. Worse, belief_id CHURNS (revise() mints a new id
   on every boost/decay/exam revision) while entity+content are revise-stable,
   so the contract is now entity-first with belief_id as legacy fallback.
2. Wiring: no production caller ever passed semantic_memory into maintain()
   (planner called it bare), so the semantic phase was skipped outright.

Plus two safety rails (flag-gated rollout, merge/scan caps) and a ghost
cleanup: 6522 belief vectors vs 1997 current beliefs with the store AT its
MAX_VECTORS=10000 cap meant new vectors evicted live summaries.

Tests use REAL BeliefStore / VectorStore / SearchResult / VectorEntry with
tmp_path-backed files (never live meta_data/ -- the daemon rewrites it).
Embeddings are stubbed at the EmbeddingModel boundary (no live Ollama).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.semantic import SemanticMemory
from agent_core.semantic.embedding_model import EmbeddingModel
from agent_core.semantic.indexer import (
    build_belief_entries,
    cleanup_stale_belief_vectors,
    make_belief_entry_id,
)
from agent_core.semantic.vector_store import SearchResult, VectorEntry
from agent_core.world_model import WorldModel
from agent_core.world_model.belief_maintenance import (
    MAX_SEMANTIC_MERGES_PER_RUN,
    SEMANTIC_DEDUP_FLAG,
    deduplicate,
    find_semantic_duplicates,
)
from agent_core.world_model.belief_model import (
    BeliefSource,
    BeliefType,
    EntityType,
    create_belief,
)
from agent_core.world_model.belief_store import BeliefStore


def _belief(entity="topic", confidence=0.5, content=None):
    return create_belief(
        entity=entity,
        entity_type=EntityType.TOPIC,
        belief_type=BeliefType.OBSERVATION,
        content=content or f"About {entity}",
        confidence=confidence,
        source=BeliefSource.LEARNING,
    )


def _fake_vector(dim=8, seed=1.0):
    import math
    return [math.sin(i * seed) for i in range(dim)]


def _mock_embedding_model():
    model = MagicMock(spec=EmbeddingModel)

    def fake_embed(text):
        seed = sum(ord(c) for c in text) / 100.0
        return _fake_vector(seed=seed)

    model.embed = MagicMock(side_effect=fake_embed)
    model.embed_batch = MagicMock(
        side_effect=lambda texts: [fake_embed(t) for t in texts]
    )
    return model


def _semantic_memory(tmp_path):
    sm = SemanticMemory(data_dir=str(tmp_path))
    sm._model = _mock_embedding_model()
    sm._initialized = True
    return sm


def _write_beliefs_jsonl(path: Path, records):
    lines = [json.dumps(rec, ensure_ascii=False) for rec in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    return BeliefStore(tmp_path / "beliefs.jsonl")


@pytest.fixture(autouse=True)
def clean_dedup_env(monkeypatch):
    """.env leaks via load_dotenv at import -- pin the flag-reading env."""
    monkeypatch.delenv(SEMANTIC_DEDUP_FLAG, raising=False)
    monkeypatch.delenv("SEMANTIC_DEDUP_SCAN_LIMIT", raising=False)
    monkeypatch.delenv("SEMANTIC_DEDUP_THRESHOLD", raising=False)


# ===================================================================
# Fix 1a: indexer emits the entity/belief_id metadata contract
# ===================================================================


class TestBuildBeliefEntriesMetadata:
    """build_belief_entries must emit (id, text, metadata) triples with the
    entity-first dedup-resolution contract and skip tombstones."""

    def test_triples_carry_entity_only(self, tmp_path):
        # belief_id is deliberately ABSENT: it churns on every revision,
        # so storing it would re-dirty ~2000 vectors per restart.
        path = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(path, [
            {"belief_id": "belief-aaa", "entity": "fotowoltaika",
             "content": "Panele zamieniaja swiatlo w prad",
             "tags": ["energia"], "superseded_by": None},
        ])

        entries = build_belief_entries(path)

        assert len(entries) == 1
        entry_id, text, meta = entries[0]
        assert entry_id == "belief:fotowoltaika"
        assert "Panele zamieniaja swiatlo w prad" in text
        assert meta == {"entity": "fotowoltaika"}

    def test_superseded_records_skipped(self, tmp_path):
        path = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(path, [
            {"belief_id": "belief-old", "entity": "fizyka",
             "content": "Old", "superseded_by": "belief-new"},
            {"belief_id": "belief-new", "entity": "chemia",
             "content": "Current", "superseded_by": None},
        ])

        entries = build_belief_entries(path)

        assert [e[0] for e in entries] == ["belief:chemia"]

    def test_last_current_record_per_entity_wins(self, tmp_path):
        path = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(path, [
            {"belief_id": "belief-v1", "entity": "fizyka",
             "content": "v1", "superseded_by": None},
            {"belief_id": "belief-v2", "entity": "fizyka",
             "content": "v2", "superseded_by": None},
        ])

        entries = build_belief_entries(path)

        assert len(entries) == 1
        assert entries[0][1] == "v2"

    def test_tombstone_does_not_shadow_earlier_current_record(self, tmp_path):
        # Raw-file order: current record first, tombstone of an OLDER
        # revision later. The tombstone must not erase the current one.
        path = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(path, [
            {"belief_id": "belief-cur", "entity": "fizyka",
             "content": "Current", "superseded_by": None},
            {"belief_id": "belief-old", "entity": "fizyka",
             "content": "Old", "superseded_by": "belief-cur"},
        ])

        entries = build_belief_entries(path)

        assert len(entries) == 1
        assert entries[0][1] == "Current"

    def test_long_entity_id_hashed_metadata_keeps_full(self, tmp_path):
        long_entity = "x" * 80
        path = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(path, [
            {"belief_id": "belief-l", "entity": long_entity,
             "content": "Long", "superseded_by": None},
        ])

        entries = build_belief_entries(path)

        assert entries[0][0] == make_belief_entry_id(long_entity)
        assert entries[0][0].startswith(f"belief:{'x' * 40}~")
        assert entries[0][2]["entity"] == long_entity

    def test_long_entities_sharing_prefix_get_distinct_ids(self):
        # The live store had a REAL pair of distinct current beliefs
        # sharing a 50-char prefix -- bare truncation collided them onto
        # one entry_id (one belief invisible + re-embed ping-pong).
        a = "Wartosc literatury jest ksztaltowana przez zmieniajace sie normy"
        b = "Wartosc literatury jest ksztaltowana przez zmieniajace sie gusta"
        assert a[:50] == b[:50]
        assert make_belief_entry_id(a) != make_belief_entry_id(b)
        # Short entities keep the readable 1:1 mapping.
        assert make_belief_entry_id("fizyka") == "belief:fizyka"


class TestIndexBatchPerEntryMetadata:
    """SemanticMemory.index_batch accepts 2-tuples (back-compat) and
    3-tuples with per-entry metadata; namespace always forced."""

    def test_two_tuples_still_work(self, tmp_path):
        sm = _semantic_memory(tmp_path)
        count = sm.index_batch("hints", [("hint:a", "text a")])

        assert count == 1
        assert sm.store.get("hint:a").metadata == {"namespace": "hints"}

    def test_triples_store_per_entry_metadata(self, tmp_path):
        sm = _semantic_memory(tmp_path)
        count = sm.index_batch("beliefs", [
            ("belief:a", "text a", {"entity": "a", "belief_id": "belief-1"}),
            ("belief:b", "text b", {"entity": "b", "belief_id": "belief-2"}),
        ])

        assert count == 2
        meta = sm.store.get("belief:a").metadata
        assert meta == {
            "entity": "a", "belief_id": "belief-1", "namespace": "beliefs",
        }


# ===================================================================
# Fix 1b: metadata refresh without re-embed (legacy entries get the
# contract on the next startup index even though their text is unchanged)
# ===================================================================


class TestMetadataRefreshWithoutReembed:
    def test_same_text_new_metadata_updates_in_place(self, tmp_path):
        sm = _semantic_memory(tmp_path)
        sm.store.add("belief:a", "text a", [0.1, 0.2], {"namespace": "beliefs"})
        before = sm.store.get("belief:a")
        original_ts = before.created_ts
        original_vec = list(before.vector)
        sm._model.embed_batch.reset_mock()

        count = sm.index_batch("beliefs", [
            ("belief:a", "text a", {"entity": "a", "belief_id": "belief-1"}),
        ])

        # Not re-embedded (count reports newly-embedded entries only)...
        assert count == 0
        sm._model.embed_batch.assert_not_called()
        entry = sm.store.get("belief:a")
        assert entry.vector == original_vec
        assert entry.created_ts == original_ts
        # ...but the metadata contract landed.
        assert entry.metadata == {
            "entity": "a", "belief_id": "belief-1", "namespace": "beliefs",
        }

    def test_refreshed_metadata_is_persisted(self, tmp_path):
        sm = _semantic_memory(tmp_path)
        sm.store.add("belief:a", "text a", [0.1, 0.2], {"namespace": "beliefs"})
        sm.store.save()

        sm.index_batch("beliefs", [
            ("belief:a", "text a", {"entity": "a", "belief_id": "belief-1"}),
        ])
        sm.store.save()

        reloaded = SemanticMemory(data_dir=str(tmp_path))
        reloaded._model = _mock_embedding_model()
        reloaded._initialized = True
        reloaded.store.load()
        assert reloaded.store.get("belief:a").metadata["entity"] == "a"

    def test_same_text_same_metadata_not_marked_dirty(self, tmp_path):
        sm = _semantic_memory(tmp_path)
        meta = {"entity": "a", "belief_id": "belief-1", "namespace": "beliefs"}
        sm.store.add("belief:a", "text a", [0.1, 0.2], dict(meta))
        sm.store.save()
        assert not sm.store._dirty_ids

        sm.index_batch("beliefs", [
            ("belief:a", "text a", {"entity": "a", "belief_id": "belief-1"}),
        ])

        assert not sm.store._dirty_ids


# ===================================================================
# Fix 1c: ghost cleanup for the beliefs namespace
# ===================================================================


class TestCleanupStaleBeliefVectors:
    def test_removes_ghosts_keeps_current(self, tmp_path):
        sm = _semantic_memory(tmp_path)
        sm.store.add("belief:alive", "t", [0.1],
                     {"namespace": "beliefs", "entity": "alive"})
        sm.store.add("belief:ghost", "t", [0.1],
                     {"namespace": "beliefs", "entity": "ghost"})
        sm.store.add("summary:keep", "t", [0.1], {"namespace": "summaries"})
        beliefs_path = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(beliefs_path, [
            {"belief_id": "belief-1", "entity": "alive",
             "content": "x", "superseded_by": None},
        ])

        removed = cleanup_stale_belief_vectors(sm, str(beliefs_path))

        assert removed == 1
        assert sm.store.get("belief:alive") is not None
        assert sm.store.get("belief:ghost") is None
        assert sm.store.get("summary:keep") is not None

    def test_legacy_entries_matched_against_current_id_scheme(self, tmp_path):
        # Pre-contract entries carry no metadata entity; they survive only
        # if their id matches what make_belief_entry_id would produce now.
        # Old-format truncated ids of LONG entities deliberately do NOT
        # match -- the migration boot replaces them with hash-suffixed ids.
        sm = _semantic_memory(tmp_path)
        long_entity = "y" * 80
        sm.store.add("belief:krotki", "t", [0.1], {"namespace": "beliefs"})
        sm.store.add(f"belief:{long_entity[:50]}", "t", [0.1],
                     {"namespace": "beliefs"})
        sm.store.add("belief:legacy-ghost", "t", [0.1],
                     {"namespace": "beliefs"})
        beliefs_path = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(beliefs_path, [
            {"belief_id": "belief-1", "entity": "krotki",
             "content": "x", "superseded_by": None},
            {"belief_id": "belief-2", "entity": long_entity,
             "content": "x", "superseded_by": None},
        ])

        removed = cleanup_stale_belief_vectors(sm, str(beliefs_path))

        assert removed == 2  # old-format long id + true ghost
        assert sm.store.get("belief:krotki") is not None
        assert sm.store.get(f"belief:{long_entity[:50]}") is None
        assert sm.store.get("belief:legacy-ghost") is None

    def test_missing_or_empty_beliefs_file_never_wipes(self, tmp_path):
        sm = _semantic_memory(tmp_path)
        sm.store.add("belief:a", "t", [0.1], {"namespace": "beliefs"})

        assert cleanup_stale_belief_vectors(
            sm, str(tmp_path / "missing.jsonl")) == 0

        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        assert cleanup_stale_belief_vectors(sm, str(empty)) == 0
        assert sm.store.get("belief:a") is not None


# ===================================================================
# Fix 2a: entity-first hit resolution (belief_id churn survival)
# ===================================================================


class _StubSemanticMemory:
    """Returns pre-baked REAL SearchResult objects; counts queries."""

    def __init__(self, results):
        self._results = results
        self.search_calls = 0

    def search(self, query, namespace=None, top_k=3):
        self.search_calls += 1
        return self._results


def _hit(metadata, text="dup", score=0.97):
    # Default 0.97: above the production threshold (0.95 -- measured live,
    # p99 of ARBITRARY belief-pair cosine is 0.875, so 0.85 would have
    # paired 97.8% of the store).
    return SearchResult(
        VectorEntry(
            entry_id="vec-1",
            text=text,
            vector=[0.0],
            metadata=metadata,
        ),
        score=score,
    )


class TestFindSemanticDuplicatesEntityResolution:
    def test_resolves_via_entity_even_after_revision_churn(self, store):
        """THE churn case: the belief was revised after indexing (boost/
        decay mint a new belief_id) but entity is revise-stable -- the
        pair must still be found via entity resolution."""
        a = _belief(entity="topic-a", confidence=0.8, content="Solar power")
        b = _belief(entity="topic-b", confidence=0.5, content="Sun energy")
        store.add(a)
        store.add(b)
        revised_b = store.revise(b.belief_id, 0.55)  # mints a NEW belief_id
        assert revised_b.belief_id != b.belief_id
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}),
        ])

        pairs = find_semantic_duplicates(store, sem)

        assert len(pairs) == 1
        keep_id, remove_id, sim = pairs[0]
        assert keep_id == a.belief_id  # higher confidence wins
        assert remove_id == revised_b.belief_id
        assert sim == pytest.approx(0.97)

    def test_unresolvable_hits_yield_no_pairs(self, store):
        # belief_id-only metadata is deliberately NOT resolvable: the key
        # churns every revision, so the contract is entity-only.
        b = _belief(entity="topic-b")
        store.add(b)
        store.add(_belief(entity="topic-a"))
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs"}),  # pre-contract entry
            _hit({"namespace": "beliefs", "belief_id": b.belief_id}),
            _hit({"namespace": "beliefs", "entity": "pruned-away"}),
        ])

        assert find_semantic_duplicates(store, sem) == []

    def test_same_entity_hit_never_pairs(self, store):
        """Same-entity collision: the shared vector carries only ONE of
        the contents, so the similarity never compared the two texts --
        merging on it would destroy an uncompared belief."""
        a = _belief(entity="topic-a", confidence=0.9, content="Version one")
        b = _belief(entity="topic-a", confidence=0.4, content="Version two")
        store.add(a)
        store.add(b)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-a"}, score=1.0),
        ])

        assert find_semantic_duplicates(store, sem) == []

    def test_own_vector_hit_is_not_a_pair(self, store):
        a = _belief(entity="topic-a")
        store.add(a)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-a"}, score=1.0),
        ])

        assert find_semantic_duplicates(store, sem) == []

    def test_below_threshold_not_paired(self, store):
        a = _belief(entity="topic-a", confidence=0.8)
        b = _belief(entity="topic-b", confidence=0.5)
        store.add(a)
        store.add(b)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}, score=0.6),
        ])

        assert find_semantic_duplicates(store, sem) == []

    def test_scan_limit_caps_queries(self, store):
        beliefs = [_belief(entity=f"topic-{i}") for i in range(5)]
        for b in beliefs:
            store.add(b)
        sem = _StubSemanticMemory([])

        find_semantic_duplicates(store, sem, scan_limit=2)

        assert sem.search_calls == 2

    def test_scan_limit_zero_disables_sweep(self, store):
        store.add(_belief(entity="topic-a"))
        sem = _StubSemanticMemory([])

        assert find_semantic_duplicates(store, sem, scan_limit=0) == []
        assert sem.search_calls == 0


# ===================================================================
# Template pair guard (first live OBSERVE batch, 2026-06-11)
# ===================================================================


class TestTemplatePairGuard:
    """All 5 candidate pairs in the first live OBSERVE batch were builder
    stat records whose contents differ only by the entity name (and digit
    runs) -- template-driven similarity, not duplicate knowledge. The
    guard must drop those pairs and ONLY those pairs."""

    def test_topic_stat_template_pair_skipped(self, store):
        # Live case 2026-06-11: 'modularnosc' vs 'pewnosc', sim=0.951.
        # File counts differ too -- digit normalization must absorb them.
        a = _belief(
            entity="modularnosc", confidence=0.74,
            content="Temat 'modularnosc' wystepuje w 15 plikach",
        )
        b = _belief(
            entity="pewnosc", confidence=0.74,
            content="Temat 'pewnosc' wystepuje w 4 plikach",
        )
        store.add(a)
        store.add(b)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "pewnosc"}, score=0.96),
        ])

        assert find_semantic_duplicates(store, sem) == []

    def test_file_mastery_template_pair_skipped(self, store):
        # Live case 2026-06-11: two DIFFERENT corpus files with separate
        # mastery scores ('relacja' vs 'relacje'), sim=0.962 -- merging
        # would delete one file's mastery record.
        a = _belief(
            entity="expert_relacja.txt", confidence=0.93,
            content="Plik 'expert_relacja.txt' opanowany (score 91%)",
        )
        b = _belief(
            entity="expert_relacje.txt", confidence=0.885,
            content="Plik 'expert_relacje.txt' opanowany (score 86%)",
        )
        store.add(a)
        store.add(b)
        sem = _StubSemanticMemory([
            _hit(
                {"namespace": "beliefs", "entity": "expert_relacje.txt"},
                score=0.96,
            ),
        ])

        assert find_semantic_duplicates(store, sem) == []

    def test_identical_content_without_self_mention_still_pairs(self, store):
        # Same knowledge filed under two entities, entities NOT in the
        # text: signatures collapse to the same string, but that means a
        # GENUINE duplicate -- the guard must not block it.
        a = _belief(
            entity="topic-a", confidence=0.8,
            content="Woda wrze w 100 stopniach Celsjusza",
        )
        b = _belief(
            entity="topic-b", confidence=0.5,
            content="Woda wrze w 100 stopniach Celsjusza",
        )
        store.add(a)
        store.add(b)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}, score=0.99),
        ])

        pairs = find_semantic_duplicates(store, sem)

        assert len(pairs) == 1
        assert pairs[0][0] == a.belief_id  # higher confidence kept

    def test_self_mentioning_contents_differing_beyond_entity_still_pair(
        self, store
    ):
        # Entities occur in their texts but the sentences differ beyond
        # the entity -- real paraphrase candidates, not a template.
        a = _belief(
            entity="grawitacja", confidence=0.8,
            content="grawitacja przyciaga male obiekty do duzych",
        )
        b = _belief(
            entity="ciazenie", confidence=0.5,
            content="ciazenie sprawia ze cialo spada na ziemie",
        )
        store.add(a)
        store.add(b)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "ciazenie"}, score=0.97),
        ])

        assert len(find_semantic_duplicates(store, sem)) == 1

    def test_guard_requires_entity_in_both_contents(self):
        # Direct unit check of the asymmetric / empty-entity edges.
        from types import SimpleNamespace

        from agent_core.world_model.belief_maintenance import (
            _is_template_pair,
        )

        tpl = SimpleNamespace(
            entity="abc", content="Temat 'abc' wystepuje w 3 plikach"
        )
        free = SimpleNamespace(entity="xyz", content="Zdanie bez podmiotu")
        empty = SimpleNamespace(entity="", content="Temat '' wystepuje")

        assert _is_template_pair(
            tpl,
            SimpleNamespace(
                entity="def", content="Temat 'def' wystepuje w 9 plikach"
            ),
        )
        assert not _is_template_pair(tpl, free)  # entity not in content
        assert not _is_template_pair(tpl, empty)  # empty entity
        assert not _is_template_pair(empty, tpl)


# ===================================================================
# Fix 2b: flag gate + merge cap in deduplicate()
# ===================================================================


class TestDeduplicateFlagGate:
    def _dup_pair(self, store):
        a = _belief(entity="topic-a", confidence=0.8, content="Solar power")
        b = _belief(entity="topic-b", confidence=0.5, content="Sun energy")
        store.add(a)
        store.add(b)
        return a, b

    def test_flag_off_skips_semantic_phase(self, store):
        self._dup_pair(store)
        sem = _StubSemanticMemory([])

        merged = deduplicate(store, sem)

        assert merged == 0
        assert sem.search_calls == 0  # semantic phase never ran

    @pytest.mark.parametrize("flag_value", ["1", "true", "YES", "on"])
    def test_flag_truthy_values_merge(self, store, monkeypatch, flag_value):
        # House flag idiom: every sibling flag accepts {'1','true','yes',
        # 'on'} case-insensitive -- '=true' silently staying OFF would
        # reproduce the wired-but-dead failure mode this change kills.
        monkeypatch.setenv(SEMANTIC_DEDUP_FLAG, flag_value)
        a, b = self._dup_pair(store)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}),
        ])

        merged = deduplicate(store, sem)

        assert merged == 1
        # Both originals superseded, one merged survivor with max confidence.
        assert store.get(a.belief_id).superseded_by is not None
        assert store.get(b.belief_id).superseded_by is not None
        survivors = [x for x in store.get_current()
                     if x.entity in ("topic-a", "topic-b")]
        assert len(survivors) == 1
        assert survivors[0].confidence == pytest.approx(0.8)

    def test_observe_mode_finds_but_never_merges(self, store, monkeypatch):
        # OBSERVE rollout step: calibration data without mutation -- the
        # first signal must NOT cost 20 irreversible merges.
        monkeypatch.setenv(SEMANTIC_DEDUP_FLAG, "observe")
        a, b = self._dup_pair(store)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}),
        ])

        merged = deduplicate(store, sem)

        assert merged == 0
        assert sem.search_calls > 0  # the sweep DID run
        assert store.get(a.belief_id).superseded_by is None
        assert store.get(b.belief_id).superseded_by is None

    def test_default_threshold_rejects_low_similarity(self, store,
                                                      monkeypatch):
        # Measured live: p99 of arbitrary belief-pair cosine is 0.875 --
        # a 0.93 hit must NOT merge under the 0.95 default.
        monkeypatch.setenv(SEMANTIC_DEDUP_FLAG, "1")
        self._dup_pair(store)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}, score=0.93),
        ])

        assert deduplicate(store, sem) == 0

    def test_threshold_env_override(self, store, monkeypatch):
        monkeypatch.setenv(SEMANTIC_DEDUP_FLAG, "1")
        monkeypatch.setenv("SEMANTIC_DEDUP_THRESHOLD", "0.9")
        self._dup_pair(store)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}, score=0.93),
        ])

        assert deduplicate(store, sem) == 1

    def test_negative_scan_limit_clamped_to_disabled(self, store,
                                                     monkeypatch):
        # -1 is a common 'disable' convention; here it would mean an
        # UNBOUNDED sweep (tens of minutes in the planner thread) -- it
        # must clamp to 0 (sweep disabled), never to unlimited.
        monkeypatch.setenv(SEMANTIC_DEDUP_FLAG, "1")
        monkeypatch.setenv("SEMANTIC_DEDUP_SCAN_LIMIT", "-1")
        self._dup_pair(store)
        sem = _StubSemanticMemory([
            _hit({"namespace": "beliefs", "entity": "topic-b"}),
        ])

        assert deduplicate(store, sem) == 0
        assert sem.search_calls == 0

    def test_merge_cap_bounds_a_run(self, store, monkeypatch):
        monkeypatch.setenv(SEMANTIC_DEDUP_FLAG, "1")
        n_pairs = MAX_SEMANTIC_MERGES_PER_RUN + 5
        pairs = []
        for i in range(n_pairs):
            a = _belief(entity=f"keep-{i}", confidence=0.8,
                        content=f"Content keep {i}")
            b = _belief(entity=f"drop-{i}", confidence=0.5,
                        content=f"Content drop {i}")
            store.add(a)
            store.add(b)
            pairs.append((a.belief_id, b.belief_id, 0.9))
        monkeypatch.setattr(
            "agent_core.world_model.belief_maintenance."
            "find_semantic_duplicates",
            lambda *args, **kwargs: pairs,
        )

        merged = deduplicate(store, object())

        assert merged == MAX_SEMANTIC_MERGES_PER_RUN

    def test_scan_limit_env_override(self, store, monkeypatch):
        monkeypatch.setenv(SEMANTIC_DEDUP_FLAG, "1")
        monkeypatch.setenv("SEMANTIC_DEDUP_SCAN_LIMIT", "1")
        for i in range(4):
            store.add(_belief(entity=f"topic-{i}"))
        sem = _StubSemanticMemory([])

        deduplicate(store, sem)

        assert sem.search_calls == 1


# ===================================================================
# Fix 2c: production wiring (source locks, doc_lint spirit -- a full
# planner/module init is too heavy and flaky for a unit suite)
# ===================================================================


class TestMaintainLock:
    """WorldModel.maintain() serializes its callers (planner thread vs
    Telegram /beliefs maintain): the lock-free store cannot survive two
    concurrent maintenance passes (compact() swaps the dict from a stale
    snapshot -> lost merges). Loser skips, never queues."""

    def test_concurrent_maintain_skips(self, tmp_path):
        import threading

        wm = WorldModel(beliefs_path=tmp_path / "beliefs.jsonl")
        entered = threading.Event()
        release = threading.Event()

        def slow_maintenance(store, semantic_memory=None, cap=2000):
            entered.set()
            release.wait(timeout=5)
            return {"decayed": 0}

        import agent_core.world_model.belief_maintenance as bm
        original = bm.run_maintenance
        bm.run_maintenance = slow_maintenance
        try:
            results = {}
            t = threading.Thread(
                target=lambda: results.update(first=wm.maintain()),
                daemon=True,
            )
            t.start()
            assert entered.wait(timeout=5)

            second = wm.maintain()  # while the first still holds the lock
            release.set()
            t.join(timeout=5)
        finally:
            bm.run_maintenance = original

        assert second == {"skipped": "maintenance_in_progress"}
        assert results["first"] == {"decayed": 0}

    def test_lock_released_after_run(self, tmp_path):
        wm = WorldModel(beliefs_path=tmp_path / "beliefs.jsonl")
        first = wm.maintain()
        second = wm.maintain()
        assert "skipped" not in first
        assert "skipped" not in second


class TestProductionWiringSourceLock:
    def test_planner_maintain_passes_semantic_memory(self):
        import agent_core.planner.planner_core as pc

        source = Path(pc.__file__).read_text(encoding="utf-8")
        assert "def set_semantic_memory(self, semantic_memory)" in source
        assert "maintain(semantic_memory=self._semantic_memory)" in source
        # The old bare call must not come back on the EVALUATE path.
        assert "self._world_model.maintain()" not in source

    def test_module_wires_planner_from_semantic_search(self):
        import agent_core.modules.homeostasis_module as hm

        source = Path(hm.__file__).read_text(encoding="utf-8")
        # ctx.semantic_search is the LIVE instance (ctx.semantic_memory is
        # never assigned anywhere -- verified 2026-06-10).
        assert "planner.set_semantic_memory(ctx.semantic_search)" in source

    def test_telegram_maintain_passes_semantic_memory(self):
        # Telegram /maintain command extracted to homeostasis_telegram_commands
        # (2026-06-13 god-file split) -- source-lock now reads its new home.
        import agent_core.modules.homeostasis_telegram_commands as tc

        source = Path(tc.__file__).read_text(encoding="utf-8")
        # The operator's manual verification path must exercise the same
        # semantic phase as the planner -- a bare wm.maintain() here made
        # the feature look dead from the phone.
        assert 'semantic_memory=getattr(ctx, "semantic_search", None)' in source
