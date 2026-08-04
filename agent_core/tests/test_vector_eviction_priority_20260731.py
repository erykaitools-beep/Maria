"""Regression: vector eviction must know WHAT it is throwing away (2026-07-31).

Measured on the live store that day: it sat exactly at MAX_VECTORS=10000
with 7507 `summaries` vectors (chunk-level text of everything Maria reads,
+1150/day) against 1587 `beliefs` (+130/day) and 809 `knowledge` (+15/day).
Eviction was blind -- globally oldest by created_ts -- so the reading
corpus steadily threw out beliefs: 413 of 2000 current belief entities had
no vector at all, and the whole store spanned 4.9 days. The boot indexer
re-embedded the missing beliefs and the next day's reading evicted them
again (ping-pong). Same shape as the 2026-06-10 audit, different filler.

Fix: evict by (EVICTION_PRIORITY[namespace], created_ts) -- the summaries
corpus recycles itself first. These tests pin that a belief survives
summary pressure REGARDLESS of age, which is the property the old policy
violated.
"""

import logging

import pytest

import agent_core.semantic.vector_store as vs
from agent_core.semantic.vector_store import VectorStore


# =========================================================================
# Helpers
# =========================================================================

@pytest.fixture
def cap3():
    """Lower MAX_VECTORS to 3 for the duration of a test."""
    old = vs.MAX_VECTORS
    vs.MAX_VECTORS = 3
    try:
        yield 3
    finally:
        vs.MAX_VECTORS = old


def _add(store, entry_id, namespace, created_ts):
    """Add one entry with an explicit age and namespace.

    created_ts is forced rather than slept for: the policy is about
    ORDERING, and wall-clock sleeps make ordering tests flaky on a loaded
    machine (this box runs the daemon during test runs).
    """
    meta = {"namespace": namespace} if namespace is not None else None
    store.add(entry_id, f"text-{entry_id}", [1.0, 0.0], meta)
    store._entries[entry_id].created_ts = created_ts


# =========================================================================
# The core property: age must not beat namespace
# =========================================================================

class TestEvictionPriority:

    def test_summary_evicted_before_older_belief(self, cap3):
        """THE regression. The belief is the OLDEST entry -- under the old
        globally-oldest policy it was the first to go."""
        store = VectorStore()
        _add(store, "belief:stara", "beliefs", created_ts=100.0)
        _add(store, "summary:a", "summaries", created_ts=200.0)
        _add(store, "summary:b", "summaries", created_ts=300.0)

        _add(store, "summary:c", "summaries", created_ts=400.0)

        assert store.count() == 3
        assert store.get("belief:stara") is not None, (
            "oldest belief must survive summary pressure"
        )
        assert store.get("summary:a") is None, "oldest summary goes first"

    def test_oldest_summary_goes_first_within_namespace(self, cap3):
        """Within one namespace the order is still age."""
        store = VectorStore()
        _add(store, "summary:mid", "summaries", created_ts=200.0)
        _add(store, "summary:old", "summaries", created_ts=100.0)
        _add(store, "summary:new", "summaries", created_ts=300.0)

        _add(store, "summary:newest", "summaries", created_ts=400.0)

        assert store.get("summary:old") is None
        assert store.get("summary:mid") is not None

    def test_belief_survives_sustained_summary_flood(self, cap3):
        """The live pattern: a trickle of beliefs under a flood of summaries.

        20 summaries into a 3-slot store, and the two beliefs must still be
        there -- that is the difference between a 5-day window and a memory.
        """
        store = VectorStore()
        _add(store, "belief:jeden", "beliefs", created_ts=10.0)
        _add(store, "knowledge:dwa", "knowledge", created_ts=11.0)

        for i in range(20):
            _add(store, f"summary:{i}", "summaries", created_ts=100.0 + i)

        assert store.count() == 3
        assert store.get("belief:jeden") is not None
        assert store.get("knowledge:dwa") is not None
        assert store.get("summary:19") is not None, "newest summary kept"

    def test_hints_evicted_before_beliefs(self, cap3):
        store = VectorStore()
        _add(store, "belief:x", "beliefs", created_ts=100.0)
        _add(store, "hint:y", "hints", created_ts=200.0)
        _add(store, "knowledge:z", "knowledge", created_ts=300.0)

        _add(store, "belief:new", "beliefs", created_ts=400.0)

        assert store.get("hint:y") is None
        assert store.get("belief:x") is not None
        assert store.get("knowledge:z") is not None

    def test_unlabelled_entry_sits_between_the_groups(self, cap3):
        """An entry with no namespace is unknown, not worthless: evicted
        after summaries but before beliefs."""
        store = VectorStore()
        _add(store, "belief:x", "beliefs", created_ts=100.0)
        _add(store, "nienazwany", None, created_ts=200.0)
        _add(store, "summary:s", "summaries", created_ts=300.0)

        # Summaries are cheaper, so they absorb the pressure first...
        _add(store, "summary:t", "summaries", created_ts=400.0)
        assert store.get("summary:s") is None, "summary is cheapest"
        assert store.get("nienazwany") is not None

        _add(store, "belief:new", "beliefs", created_ts=500.0)
        assert store.get("summary:t") is None, "last summary before unlabelled"
        assert store.get("nienazwany") is not None

        # ...and only once no summary is left does the unlabelled entry go --
        # still ahead of the belief, which is what DEFAULT_EVICTION_PRIORITY
        # sitting between the two groups means.
        _add(store, "belief:newer", "beliefs", created_ts=600.0)
        assert store.get("nienazwany") is None, "unlabelled goes before belief"
        assert store.get("belief:x") is not None


# =========================================================================
# Never fail to make room
# =========================================================================

class TestEvictionAlwaysFreesRoom:

    def test_protected_only_store_still_evicts(self, cap3):
        """When nothing cheaper exists the cap still holds -- protection is a
        priority, not a veto (a veto would grow the store past MAX_VECTORS
        and reintroduce the OOM the cap exists to prevent)."""
        store = VectorStore()
        _add(store, "belief:a", "beliefs", created_ts=100.0)
        _add(store, "belief:b", "beliefs", created_ts=200.0)
        _add(store, "knowledge:c", "knowledge", created_ts=300.0)

        _add(store, "belief:d", "beliefs", created_ts=400.0)

        assert store.count() == 3
        assert store.get("belief:a") is None, "oldest of the cheapest tier"
        assert store.get("knowledge:c") is not None

    def test_evicting_many_at_once_frees_exact_count(self):
        """load() over cap calls _evict_oldest with a batch, not one at a
        time. Cap stays high here so only the explicit call evicts."""
        old = vs.MAX_VECTORS
        vs.MAX_VECTORS = 100
        try:
            store = VectorStore()
            for i in range(6):
                _add(store, f"summary:{i}", "summaries", created_ts=100.0 + i)
            _add(store, "belief:keep", "beliefs", created_ts=1.0)

            store._evict_oldest(3)

            assert store.count() == 4
            assert store.get("belief:keep") is not None, (
                "oldest entry in the store, but the cheapest three go first"
            )
            assert store.get("summary:0") is None
            assert store.get("summary:3") is not None
        finally:
            vs.MAX_VECTORS = old

    def test_no_namespaces_at_all_behaves_like_pure_age(self, cap3):
        """Backward compatibility: unlabelled-only stores keep the old
        globally-oldest behaviour."""
        store = VectorStore()
        _add(store, "id_old", None, created_ts=100.0)
        _add(store, "id_mid", None, created_ts=200.0)
        _add(store, "id_new", None, created_ts=300.0)

        _add(store, "id_newest", None, created_ts=400.0)

        assert store.get("id_old") is None
        assert store.get("id_mid") is not None


# =========================================================================
# Visibility -- so the policy can be checked on the live store
# =========================================================================

class TestEvictionVisibility:

    def test_stats_tally_evictions_per_namespace(self, cap3):
        store = VectorStore()
        _add(store, "belief:x", "beliefs", created_ts=100.0)
        for i in range(4):
            _add(store, f"summary:{i}", "summaries", created_ts=200.0 + i)

        stats = store.stats()
        assert stats["evicted_by_namespace"] == {"summaries": 2}
        assert stats["namespaces"]["beliefs"] == 1

    def test_protected_eviction_is_logged_at_info(self, cap3, caplog):
        """Evicting a belief is not routine -- it means the cap is too small,
        so it must be visible in journalctl, not hidden at DEBUG."""
        store = VectorStore()
        _add(store, "belief:a", "beliefs", created_ts=100.0)
        _add(store, "belief:b", "beliefs", created_ts=200.0)
        _add(store, "belief:c", "beliefs", created_ts=300.0)

        with caplog.at_level(logging.INFO, logger="agent_core.semantic.vector_store"):
            _add(store, "belief:d", "beliefs", created_ts=400.0)

        assert any("Cap pressure" in r.message for r in caplog.records)

    def test_summary_eviction_is_not_logged_at_info(self, cap3, caplog):
        """The routine case must stay quiet -- 1150 INFO lines a day would
        drown the log it is supposed to be visible in."""
        store = VectorStore()
        _add(store, "summary:a", "summaries", created_ts=100.0)
        _add(store, "summary:b", "summaries", created_ts=200.0)
        _add(store, "summary:c", "summaries", created_ts=300.0)

        with caplog.at_level(logging.INFO, logger="agent_core.semantic.vector_store"):
            _add(store, "summary:d", "summaries", created_ts=400.0)

        assert not any("Cap pressure" in r.message for r in caplog.records)
