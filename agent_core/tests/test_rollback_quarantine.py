"""
Rollback / Quarantine (TIER 2: "Maria potrafi swiadomie zapomniec").

Conscious-unlearn for the belief layer (K6). The store was strictly append-only
with no by-id/by-source retract; this suite covers the new lifecycle, built one
PR at a time behind RETRACTION_ENABLED (off by default).

Design + adversarial critique: claude_notes/2026-06-14_rollback_quarantine_spec.md
(raw: 2026-06-14_rollback_design_raw.json).

PR1 (this file, initial): brick 1 schema (status/retraction additive +
carry-forward at every Belief(...) copy site) + brick 2 retraction_log ledger.
Zero behaviour change -- no reader filters on status yet, nothing mints a
non-active belief. Real ops, read-filters, denylist, vectors land in later PRs.

Tests use REAL BeliefStore / Belief with tmp_path-backed files (never live
meta_data/ -- the daemon rewrites it).
"""

import dataclasses
import json
from pathlib import Path

import pytest

from agent_core.world_model.belief_model import (
    Belief, BeliefType, BeliefSource, EntityType, create_belief,
)
from agent_core.world_model.belief_store import BeliefStore
from agent_core.world_model.belief_maintenance import merge_duplicate_pair
from agent_core.world_model import retraction_log


def _belief(entity="topic-x", source_id="file-1", conf=0.8, belief_id=None,
            status="active", retraction=None):
    b = create_belief(
        entity=entity,
        entity_type=EntityType.TOPIC,
        belief_type=BeliefType.OBSERVATION,
        content=f"a statement about {entity}",
        confidence=conf,
        source=BeliefSource.LEARNING,
        source_id=source_id,
        tags=["t1", "t2"],
        related_entities=["rel-a"],
        belief_id=belief_id,
    )
    if status != "active" or retraction is not None:
        b = dataclasses.replace(b, status=status, retraction=retraction)
    return b


# ============================================================
# Brick 1 -- schema: status + retraction additive fields
# ============================================================

class TestBeliefSchemaLifecycleFields:
    def test_defaults_active_none(self):
        b = create_belief(
            entity="x", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT, content="c", confidence=0.9,
            source=BeliefSource.SYSTEM,
        )
        assert b.status == "active"
        assert b.retraction is None

    def test_to_dict_omits_when_active(self):
        """On-disk shape unchanged for the common active case (mirrors evidence)."""
        d = _belief().to_dict()
        assert "status" not in d
        assert "retraction" not in d

    def test_to_dict_emits_when_non_active(self):
        ret = {"reason": "bad source", "actor": "operator", "ts": 1.0}
        d = _belief(status="quarantined", retraction=ret).to_dict()
        assert d["status"] == "quarantined"
        assert d["retraction"] == ret

    def test_roundtrip_with_fields(self):
        ret = {"reason": "hallucinated", "actor": "auto", "prev_status": "active"}
        b = _belief(status="retracted", retraction=ret, conf=0.0)
        b2 = Belief.from_dict(b.to_dict())
        assert b2.status == "retracted"
        assert b2.retraction == ret
        assert b2.confidence == 0.0

    def test_roundtrip_without_fields(self):
        b = _belief()
        b2 = Belief.from_dict(b.to_dict())
        assert b2.status == "active"
        assert b2.retraction is None

    def test_backward_compat_old_record_loads_active(self):
        """A pre-existing beliefs.jsonl line (no status key) loads as active."""
        legacy = {
            "belief_id": "belief-legacy01", "entity": "old", "entity_type": "topic",
            "belief_type": "fact", "content": "legacy", "confidence": 0.7,
            "source": "learning", "source_id": "f0", "tags": ["t"],
            "created_at": 1.0, "updated_at": 1.0, "revision": 1,
            "superseded_by": None, "related_entities": [],
        }
        b = Belief.from_dict(legacy)
        assert b.status == "active"
        assert b.retraction is None


# ============================================================
# Brick 1 -- carry-forward at every copy site (resurrection guard)
# The #1 corruption vector per the adversarial critique: a revise/decay/merge
# of a quarantined belief must NOT mint a fresh active record under a new id.
# ============================================================

class TestCarryForwardCopySites:
    def test_revise_carries_status_and_retraction(self, tmp_path):
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        b = _belief(belief_id="belief-q1")
        store.add(b)
        ret = {"reason": "poisoned", "actor": "operator", "prev_status": "active"}
        store._beliefs["belief-q1"] = dataclasses.replace(
            b, status="quarantined", retraction=ret)

        revised = store.revise("belief-q1", 0.5)

        assert revised is not None
        # The NEW current record (fresh belief_id) still carries the lifecycle.
        assert revised.status == "quarantined"
        assert revised.retraction == ret
        assert revised.belief_id != "belief-q1"  # id churns, status does not

    def test_revise_supersede_copy_carries_forward(self, tmp_path):
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        b = _belief(belief_id="belief-q2")
        store.add(b)
        ret = {"reason": "x"}
        store._beliefs["belief-q2"] = dataclasses.replace(
            b, status="retracted", retraction=ret)

        store.revise("belief-q2", 0.4)

        # The superseded (old-id) tombstone copy also keeps the lifecycle.
        old = store.get("belief-q2")
        assert old.superseded_by is not None
        assert old.status == "retracted"
        assert old.retraction == ret

    def test_merge_duplicate_pair_carries_forward(self, tmp_path):
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        keep = _belief(entity="dup", source_id="fa", belief_id="belief-keep")
        remove = _belief(entity="dup", source_id="fb", belief_id="belief-rm")
        store.add(keep)
        store.add(remove)
        ret = {"reason": "merge-guard"}
        store._beliefs["belief-keep"] = dataclasses.replace(
            keep, status="quarantined", retraction=ret)

        ok = merge_duplicate_pair(store, "belief-keep", "belief-rm")

        assert ok
        # The merged current belief inherits the kept belief's lifecycle, not a
        # fresh active state. It is quarantined, so get_current() now HIDES it
        # (PR2 filter) -- look at the raw non-superseded view to find it.
        merged = [b for b in store._beliefs.values()
                  if b.entity == "dup" and b.superseded_by is None]
        assert len(merged) == 1
        assert merged[0].status == "quarantined"
        assert merged[0].retraction == ret


# ============================================================
# Brick 2 -- retraction_log.jsonl durable audit ledger
# ============================================================

class TestRetractionLog:
    def test_append_then_read_newest_first(self, tmp_path):
        p = tmp_path / "retractions.jsonl"
        assert retraction_log.append_retraction(p, {"op": "quarantine", "reason": "a"}, now_ts=100.0)
        assert retraction_log.append_retraction(p, {"op": "retract", "reason": "b"}, now_ts=200.0)
        rows = retraction_log.read_retractions(p)
        assert [r["op"] for r in rows] == ["retract", "quarantine"]  # newest first
        assert rows[0]["reason"] == "b"

    def test_append_stamps_id_and_iso(self, tmp_path):
        p = tmp_path / "retractions.jsonl"
        retraction_log.append_retraction(p, {"op": "retract"}, now_ts=1700000000.0)
        row = retraction_log.read_retractions(p)[0]
        assert row["retraction_id"].startswith("ret-")
        assert row["timestamp"] == 1700000000.0
        assert row["iso"].endswith("Z")

    def test_caller_supplied_id_preserved(self, tmp_path):
        p = tmp_path / "retractions.jsonl"
        retraction_log.append_retraction(p, {"retraction_id": "ret-fixed00", "op": "retract"})
        assert retraction_log.read_retractions(p)[0]["retraction_id"] == "ret-fixed00"

    def test_malformed_line_skipped(self, tmp_path):
        p = tmp_path / "retractions.jsonl"
        retraction_log.append_retraction(p, {"op": "retract", "reason": "good"}, now_ts=5.0)
        with open(p, "a", encoding="utf-8") as f:
            f.write("{ this is not json\n")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n")  # blank line
        rows = retraction_log.read_retractions(p)
        assert len(rows) == 1
        assert rows[0]["reason"] == "good"

    def test_read_missing_file_is_empty(self, tmp_path):
        assert retraction_log.read_retractions(tmp_path / "nope.jsonl") == []

    def test_append_auto_creates_dir(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "retractions.jsonl"
        assert retraction_log.append_retraction(p, {"op": "quarantine"})
        assert p.is_file()

    def test_append_defensive_on_bad_path(self, tmp_path):
        """A write to an unwritable target returns False without raising."""
        # A directory path cannot be opened for append as a file.
        d = tmp_path / "is_a_dir"
        d.mkdir()
        assert retraction_log.append_retraction(d, {"op": "retract"}) is False

    def test_limit_respected(self, tmp_path):
        p = tmp_path / "retractions.jsonl"
        for i in range(5):
            retraction_log.append_retraction(p, {"op": "retract", "i": i}, now_ts=float(i))
        rows = retraction_log.read_retractions(p, limit=2)
        assert len(rows) == 2
        assert rows[0]["i"] == 4  # newest

    def test_new_retraction_id_format(self):
        rid = retraction_log.new_retraction_id()
        assert rid.startswith("ret-")
        assert len(rid) == len("ret-") + 12


# ============================================================
# Brick 4 (PR2) -- visibility cutover: a non-active belief vanishes from
# every reader. Still zero mutation -- we hand-craft quarantined records.
# ============================================================

def _write_beliefs_jsonl(path, beliefs):
    with open(path, "w", encoding="utf-8") as f:
        for b in beliefs:
            f.write(json.dumps(b.to_dict(), ensure_ascii=False) + "\n")


class TestStoreReadFiltersExcludeNonActive:
    def _store_with_quarantined(self, tmp_path):
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        active = _belief(entity="visible", source_id="fa", belief_id="belief-act")
        quar = _belief(entity="hidden", source_id="fb", belief_id="belief-quar",
                       status="quarantined", retraction={"reason": "test"})
        retr = _belief(entity="gone", source_id="fc", belief_id="belief-retr",
                       status="retracted", retraction={"reason": "x"}, conf=0.0)
        store.add(active)
        store.add(quar)
        store.add(retr)
        return store

    def test_get_by_entity_excludes(self, tmp_path):
        store = self._store_with_quarantined(tmp_path)
        assert store.get_by_entity("visible")
        assert store.get_by_entity("hidden") == []
        assert store.get_by_entity("gone") == []

    def test_get_by_entity_type_excludes(self, tmp_path):
        store = self._store_with_quarantined(tmp_path)
        entities = {b.entity for b in store.get_by_entity_type(EntityType.TOPIC)}
        assert entities == {"visible"}

    def test_get_by_tag_excludes(self, tmp_path):
        store = self._store_with_quarantined(tmp_path)
        entities = {b.entity for b in store.get_by_tag("t1")}
        assert entities == {"visible"}

    def test_get_current_excludes(self, tmp_path):
        store = self._store_with_quarantined(tmp_path)
        entities = {b.entity for b in store.get_current()}
        assert entities == {"visible"}

    def test_get_by_id_still_returns_non_active(self, tmp_path):
        """get(id) is the by-id lookup the ops themselves need -- NOT filtered."""
        store = self._store_with_quarantined(tmp_path)
        assert store.get("belief-quar") is not None
        assert store.get("belief-quar").status == "quarantined"

    def test_find_by_entity_and_source_excludes(self, tmp_path):
        store = self._store_with_quarantined(tmp_path)
        assert store.find_by_entity_and_source("hidden", "fb") is None
        assert store.find_by_entity_and_source("visible", "fa") is not None

    def test_stats_by_status_bucket(self, tmp_path):
        store = self._store_with_quarantined(tmp_path)
        st = store.stats()
        assert st["by_status"] == {"active": 1, "quarantined": 1, "retracted": 1}
        assert st["total"] == 1  # only active counts as current

    def test_reload_from_disk_preserves_hiding(self, tmp_path):
        """Round-trip through disk: status survives save/load and stays hidden."""
        store = self._store_with_quarantined(tmp_path)
        store.save()
        store2 = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        store2.load()
        assert {b.entity for b in store2.get_current()} == {"visible"}
        assert store2.get("belief-quar").status == "quarantined"


class TestMaintenanceSkipsNonActive:
    def test_compact_preserves_non_active(self, tmp_path):
        """The load-bearing test: compact() must NOT erase a retracted record
        (it stays CURRENT, superseded_by=None) -- the on-disk audit survives."""
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        store.add(_belief(entity="gone", belief_id="belief-r",
                          status="retracted", retraction={"reason": "x"}, conf=0.0))
        store.save()
        store.compact()
        # Still on disk + in memory after compaction.
        assert store.get("belief-r") is not None
        assert store.get("belief-r").status == "retracted"

    def test_smart_prune_ignores_quarantined(self, tmp_path):
        from agent_core.world_model.belief_maintenance import smart_prune
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        # 3 active + 1 quarantined; cap=2 -> prune over the ACTIVE set only.
        for i in range(3):
            store.add(_belief(entity=f"a{i}", belief_id=f"belief-a{i}"))
        store.add(_belief(entity="q", belief_id="belief-q",
                          status="quarantined", retraction={"reason": "x"}))
        smart_prune(store, cap=2)
        # The quarantined belief is never scored/dropped (excluded from get_current).
        assert store.get("belief-q") is not None
        assert store.get("belief-q").status == "quarantined"

    def test_apply_decay_skips_non_active(self, tmp_path):
        from agent_core.world_model.belief_maintenance import apply_decay
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        # Old quarantined belief that WOULD decay heavily if visible.
        old = _belief(entity="q", belief_id="belief-q", conf=0.9,
                      status="quarantined", retraction={"reason": "x"})
        old = dataclasses.replace(old, updated_at=1.0)  # ancient -> max decay
        store.add(old)
        revised = apply_decay(store, now=1.0 + 86400 * 365)
        assert revised == 0  # nothing decayed (the only belief is non-active)
        assert store.get("belief-q").confidence == 0.9  # untouched


class TestRawReadersExcludeNonActive:
    def test_memory_query_hides_quarantined(self, tmp_path):
        from agent_core.memory.query import MemoryQuery
        bp = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(bp, [
            _belief(entity="visible", belief_id="belief-v"),
            _belief(entity="hidden", belief_id="belief-h",
                    status="quarantined", retraction={"reason": "x"}),
        ])
        mq = MemoryQuery(beliefs_path=bp,
                         knowledge_path=tmp_path / "ki.jsonl",
                         exam_path=tmp_path / "ex.jsonl",
                         hints_path=tmp_path / "h.jsonl")
        mq._ensure_cache()
        assert "visible" in mq._beliefs_cache
        assert "hidden" not in mq._beliefs_cache

    def test_indexer_build_entries_omits_non_active(self, tmp_path):
        from agent_core.semantic.indexer import build_belief_entries, make_belief_entry_id
        bp = tmp_path / "beliefs.jsonl"
        _write_beliefs_jsonl(bp, [
            _belief(entity="visible", belief_id="belief-v"),
            _belief(entity="hidden", belief_id="belief-h",
                    status="retracted", retraction={"reason": "x"}, conf=0.0),
        ])
        entries = build_belief_entries(bp)
        ids = {e[0] for e in entries}
        assert make_belief_entry_id("visible") in ids
        assert make_belief_entry_id("hidden") not in ids

    def test_cleanup_current_set_excludes_fully_quarantined_entity(self, tmp_path):
        from agent_core.semantic import indexer
        bp = tmp_path / "beliefs.jsonl"
        # Entity 'mix' has BOTH an active and a quarantined belief -> stays current.
        # Entity 'gone' has only a quarantined belief -> drops out of current set.
        _write_beliefs_jsonl(bp, [
            _belief(entity="mix", source_id="fa", belief_id="belief-mix-a"),
            _belief(entity="mix", source_id="fb", belief_id="belief-mix-q",
                    status="quarantined", retraction={"reason": "x"}),
            _belief(entity="gone", source_id="fc", belief_id="belief-gone-q",
                    status="quarantined", retraction={"reason": "x"}),
        ])
        # Re-derive the same current-entity set cleanup uses (via build entries).
        entries = indexer.build_belief_entries(bp)
        entities = set()
        for eid, text, meta in entries:
            entities.add(meta["entity"])
        assert "mix" in entities
        assert "gone" not in entities


# ============================================================
# Brick 6 (PR3) -- source/entity denylist: the resurrection guard.
# build_all is a pure projection of the source JSONLs, so without this a
# store-only retract is undone within one learning cycle. Still no mutation of
# existing beliefs -- this is a build-time gate.
# ============================================================

class TestDenylistLedger:
    def test_append_load_source_and_entity(self, tmp_path):
        p = tmp_path / "denylist.jsonl"
        retraction_log.append_denylist_entry(p, "source", "synthesis_abc", reason="bad")
        retraction_log.append_denylist_entry(p, "entity", "uczenie maszynowe", reason="x")
        dl = retraction_log.load_denylist(p)
        assert dl["source"] == {"synthesis_abc"}
        assert dl["entity"] == {"uczenie maszynowe"}

    def test_lift_via_active_false(self, tmp_path):
        p = tmp_path / "denylist.jsonl"
        retraction_log.append_denylist_entry(p, "source", "s1", now_ts=1.0)
        retraction_log.append_denylist_entry(p, "source", "s1", active=False, now_ts=2.0)
        assert retraction_log.load_denylist(p)["source"] == set()

    def test_relist_after_lift(self, tmp_path):
        p = tmp_path / "denylist.jsonl"
        retraction_log.append_denylist_entry(p, "entity", "e1", now_ts=1.0)
        retraction_log.append_denylist_entry(p, "entity", "e1", active=False, now_ts=2.0)
        retraction_log.append_denylist_entry(p, "entity", "e1", active=True, now_ts=3.0)
        assert retraction_log.load_denylist(p)["entity"] == {"e1"}

    def test_invalid_scope_rejected(self, tmp_path):
        p = tmp_path / "denylist.jsonl"
        assert retraction_log.append_denylist_entry(p, "bogus", "x") is False
        assert retraction_log.append_denylist_entry(p, "source", "") is False

    def test_missing_file_empty_sets(self, tmp_path):
        dl = retraction_log.load_denylist(tmp_path / "nope.jsonl")
        assert dl == {"source": set(), "entity": set()}


class TestBuildAllResurrectionGuard:
    def _write_jsonl(self, path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _builder(self, tmp_path):
        from agent_core.world_model.belief_builder import BeliefBuilder
        return BeliefBuilder(
            knowledge_index_path=tmp_path / "knowledge_index.jsonl",
            longterm_memory_path=tmp_path / "longterm_memory.jsonl",
            exam_results_path=tmp_path / "exam_results.jsonl",
            denylist_path=tmp_path / "denylist.jsonl",
        )

    def test_file_belief_blocked_by_source_denylist(self, tmp_path):
        builder = self._builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "file1.txt", "status": "completed", "last_scores": [0.85]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "file1.txt", "score": 0.85, "grader_independent": True},
        ])
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")

        # Baseline: the belief builds without a denylist.
        assert builder.build_file_beliefs(store) == 1

        # Deny the source, rebuild into a fresh store -> zero re-mint.
        retraction_log.append_denylist_entry(
            tmp_path / "denylist.jsonl", "source", "file1.txt", reason="forget_source")
        store2 = BeliefStore(beliefs_path=tmp_path / "beliefs2.jsonl")
        assert builder.build_file_beliefs(store2) == 0

    def test_file_belief_blocked_by_entity_denylist(self, tmp_path):
        """A by-id /retract whose source still passes the gate is blocked by
        the per-ENTITY scope (the hole the adversarial review caught)."""
        builder = self._builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "file1.txt", "status": "completed", "last_scores": [0.85]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "file1.txt", "score": 0.85, "grader_independent": True},
        ])
        retraction_log.append_denylist_entry(
            tmp_path / "denylist.jsonl", "entity", "file1.txt", reason="retract")
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        assert builder.build_file_beliefs(store) == 0

    def test_concept_beliefs_blocked_by_source_denylist(self, tmp_path):
        builder = self._builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "synthesis_x", "chunk_id": "synthesis_x:0",
             "key_points": ["kp one", "kp two"], "tags": []},
        ])
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        assert builder.build_concept_beliefs(store) == 2  # baseline

        retraction_log.append_denylist_entry(
            tmp_path / "denylist.jsonl", "source", "synthesis_x", reason="forget_source")
        store2 = BeliefStore(beliefs_path=tmp_path / "beliefs2.jsonl")
        assert builder.build_concept_beliefs(store2) == 0  # root-and-branch cut

    def test_concept_belief_blocked_by_entity_denylist(self, tmp_path):
        builder = self._builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1", "chunk_id": "f1:0",
             "key_points": ["keep me", "retract me"], "tags": []},
        ])
        retraction_log.append_denylist_entry(
            tmp_path / "denylist.jsonl", "entity", "retract me", reason="retract")
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        # Only the non-denylisted key point becomes a belief.
        assert builder.build_concept_beliefs(store) == 1
        entities = {b.entity for b in store.get_current()}
        assert "keep me" in entities
        assert "retract me" not in entities

    def test_topic_belief_blocked_by_entity_denylist(self, tmp_path):
        builder = self._builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python", "math"], "key_points": []},
        ])
        retraction_log.append_denylist_entry(
            tmp_path / "denylist.jsonl", "entity", "python", reason="retract")
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        builder.build_topic_beliefs(store)
        entities = {b.entity for b in store.get_current()}
        assert "math" in entities
        assert "python" not in entities

    def test_lift_denylist_re_allows_rebuild(self, tmp_path):
        builder = self._builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": []},
        ])
        dl = tmp_path / "denylist.jsonl"
        retraction_log.append_denylist_entry(dl, "entity", "python", now_ts=1.0)
        store = BeliefStore(beliefs_path=tmp_path / "b1.jsonl")
        builder.build_topic_beliefs(store)
        assert "python" not in {b.entity for b in store.get_current()}

        # Lift the denial (un-quarantine) -> rebuild re-mints.
        retraction_log.append_denylist_entry(dl, "entity", "python", active=False, now_ts=2.0)
        store2 = BeliefStore(beliefs_path=tmp_path / "b2.jsonl")
        builder.build_topic_beliefs(store2)
        assert "python" in {b.entity for b in store2.get_current()}

    def test_no_denylist_path_blocks_nothing(self, tmp_path):
        from agent_core.world_model.belief_builder import BeliefBuilder
        builder = BeliefBuilder(
            knowledge_index_path=tmp_path / "knowledge_index.jsonl",
            longterm_memory_path=tmp_path / "longterm_memory.jsonl",
            exam_results_path=tmp_path / "exam_results.jsonl",
        )  # no denylist_path
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": []},
        ])
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        builder.build_topic_beliefs(store)
        assert "python" in {b.entity for b in store.get_current()}


# ============================================================
# Brick 3 (PR4) -- BeliefStore quarantine / retract / unquarantine ops.
# Same-id in-place status flip; the record stays CURRENT so compact preserves it.
# ============================================================

class TestStoreOps:
    def _store(self, tmp_path):
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        store.add(_belief(entity="e1", belief_id="belief-1", conf=0.8))
        return store

    def test_quarantine_flips_status_same_id(self, tmp_path):
        store = self._store(tmp_path)
        new = store.quarantine("belief-1", reason="bad", actor_detail="eryk")
        assert new is not None
        assert new.belief_id == "belief-1"  # same id, in place
        assert new.status == "quarantined"
        assert new.superseded_by is None    # stays CURRENT -> compact preserves
        assert new.retraction["reason"] == "bad"
        assert new.retraction["prev_status"] == "active"
        assert new.retraction["prev_confidence"] == 0.8
        # Hidden from current view, present by-id.
        assert store.get_current() == []
        assert store.get("belief-1").status == "quarantined"

    def test_quarantine_guards_non_active(self, tmp_path):
        store = self._store(tmp_path)
        store.quarantine("belief-1")
        assert store.quarantine("belief-1") is None  # already quarantined
        assert store.quarantine("nope") is None       # missing

    def test_retract_forces_zero_confidence_kept_current(self, tmp_path):
        store = self._store(tmp_path)
        new = store.retract("belief-1", reason="hallucination")
        assert new.status == "retracted"
        assert new.confidence == 0.0
        assert new.superseded_by is None
        # compact() must preserve the retracted record (the audit tombstone).
        store.save()
        store.compact()
        assert store.get("belief-1").status == "retracted"

    def test_retract_from_quarantined(self, tmp_path):
        store = self._store(tmp_path)
        store.quarantine("belief-1")
        new = store.retract("belief-1", reason="escalate")
        assert new.status == "retracted"
        # prev_status snapshot reflects the quarantined state it came from.
        assert new.retraction["prev_status"] == "quarantined"

    def test_retract_idempotent(self, tmp_path):
        store = self._store(tmp_path)
        store.retract("belief-1")
        assert store.retract("belief-1") is None

    def test_unquarantine_restores_prior_state(self, tmp_path):
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        b = _belief(entity="e1", belief_id="belief-1", conf=0.75)
        b = dataclasses.replace(b, belief_type=BeliefType.FACT)
        store.add(b)
        store.quarantine("belief-1")
        restored = store.unquarantine("belief-1")
        assert restored.status == "active"
        assert restored.belief_type == BeliefType.FACT  # restored from snapshot
        assert restored.confidence == 0.75
        assert restored.retraction is None
        assert {x.entity for x in store.get_current()} == {"e1"}

    def test_unquarantine_guards_non_quarantined(self, tmp_path):
        store = self._store(tmp_path)
        assert store.unquarantine("belief-1") is None  # active, not quarantined

    def test_get_current_by_source_matches_file_and_concept(self, tmp_path):
        store = BeliefStore(beliefs_path=tmp_path / "beliefs.jsonl")
        # File belief: entity == source value.
        store.add(create_belief(entity="synthesis_x", entity_type=EntityType.FILE,
                                belief_type=BeliefType.OBSERVATION, content="c",
                                confidence=0.5, source=BeliefSource.LEARNING,
                                source_id="file:synthesis_x", belief_id="belief-file"))
        # Concept belief derived from the same source.
        store.add(create_belief(entity="some key point", entity_type=EntityType.CONCEPT,
                                belief_type=BeliefType.OBSERVATION, content="c",
                                confidence=0.5, source=BeliefSource.LEARNING,
                                source_id="concept:synthesis_x:0", belief_id="belief-concept"))
        # Unrelated belief.
        store.add(_belief(entity="other", belief_id="belief-other"))
        matched = {b.belief_id for b in store.get_current_by_source("synthesis_x")}
        assert matched == {"belief-file", "belief-concept"}


# ============================================================
# Brick 5 + 7 (PR4) -- WorldModel facade ops: blocking lock, ledger, denylist,
# vector consistency, query-cache invalidation, boot replay.
# ============================================================

class _FakeSemantic:
    def __init__(self):
        self.removed = []
        self.added = []
        self.saved = 0

    def remove(self, entry_id):
        self.removed.append(entry_id)
        return True

    def index_text(self, ns, entry_id, text, meta=None):
        self.added.append((ns, entry_id, text, meta))
        return True

    def save(self):
        self.saved += 1
        return 1


class _FakeMQ:
    def __init__(self):
        self.invalidated = 0

    def _invalidate_cache(self):
        self.invalidated += 1


def _wm(tmp_path):
    from agent_core.world_model import WorldModel
    return WorldModel(
        beliefs_path=tmp_path / "beliefs.jsonl",
        knowledge_index_path=tmp_path / "ki.jsonl",
        longterm_memory_path=tmp_path / "lt.jsonl",
        exam_results_path=tmp_path / "ex.jsonl",
        retractions_path=tmp_path / "retractions.jsonl",
        denylist_path=tmp_path / "denylist.jsonl",
    )


class TestFacadeOps:
    def test_quarantine_belief_hides_and_logs(self, tmp_path):
        wm = _wm(tmp_path)
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))
        res = wm.quarantine_belief("belief-1", reason="bad", actor_detail="eryk")
        assert res["ok"] and res["count"] == 1
        assert wm.store.get_current() == []          # hidden
        assert wm.store.get("belief-1").status == "quarantined"
        rows = wm.list_retractions()
        assert rows[0]["op"] == "quarantine"
        assert rows[0]["target_entities"] == ["e1"]
        assert rows[0]["actor_detail"] == "eryk"
        # quarantine does NOT denylist (reversible).
        assert retraction_log.load_denylist(tmp_path / "denylist.jsonl")["entity"] == set()

    def test_retract_belief_denylists_entity(self, tmp_path):
        wm = _wm(tmp_path)
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))
        res = wm.retract_belief("e1", reason="hallucination")  # by entity
        assert res["ok"] and res["count"] == 1
        assert wm.store.get("belief-1").status == "retracted"
        assert wm.store.get("belief-1").confidence == 0.0
        dl = retraction_log.load_denylist(tmp_path / "denylist.jsonl")
        assert dl["entity"] == {"e1"}                 # resurrection guard armed
        assert wm.list_retractions()[0]["op"] == "retract"

    def test_no_matching_target_returns_not_ok(self, tmp_path):
        wm = _wm(tmp_path)
        res = wm.retract_belief("ghost")
        assert res["ok"] is False and res["count"] == 0

    def test_forget_source_root_and_branch(self, tmp_path):
        wm = _wm(tmp_path)
        wm.store.add(create_belief(entity="synthesis_x", entity_type=EntityType.FILE,
                                   belief_type=BeliefType.OBSERVATION, content="c",
                                   confidence=0.5, source=BeliefSource.LEARNING,
                                   source_id="file:synthesis_x", belief_id="bf"))
        wm.store.add(create_belief(entity="kp one", entity_type=EntityType.CONCEPT,
                                   belief_type=BeliefType.OBSERVATION, content="c",
                                   confidence=0.5, source=BeliefSource.LEARNING,
                                   source_id="concept:synthesis_x:0", belief_id="bc"))
        wm.store.add(_belief(entity="unrelated", belief_id="bu"))
        res = wm.forget_source("synthesis_x", reason="bad synthesis")
        assert res["ok"] and res["count"] == 2
        assert wm.store.get("bf").status == "retracted"
        assert wm.store.get("bc").status == "retracted"
        assert wm.store.get("bu").status == "active"   # untouched
        dl = retraction_log.load_denylist(tmp_path / "denylist.jsonl")
        assert dl["source"] == {"synthesis_x"}
        assert wm.list_retractions()[0]["source_scope"] == {"kind": "by_source", "value": "synthesis_x"}

    def test_unquarantine_restores_and_lifts_denylist(self, tmp_path):
        wm = _wm(tmp_path)
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))
        wm.retract_belief("e1", reason="x")            # denylists entity e1
        assert retraction_log.load_denylist(tmp_path / "denylist.jsonl")["entity"] == {"e1"}
        # Now quarantine a different belief and unquarantine it.
        wm.store.add(_belief(entity="e2", belief_id="belief-2"))
        wm.quarantine_belief("belief-2")
        res = wm.unquarantine_belief("belief-2")
        assert res["ok"]
        assert wm.store.get("belief-2").status == "active"
        # Unquarantine lifts e2's entity denylist (active=False appended).
        dl = retraction_log.load_denylist(tmp_path / "denylist.jsonl")
        assert "e2" not in dl["entity"]

    def test_vector_evicted_on_retract(self, tmp_path):
        wm = _wm(tmp_path)
        fake = _FakeSemantic()
        mq = _FakeMQ()
        wm.set_unlearn_handles(semantic_memory=fake, memory_query=mq)
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))
        wm.retract_belief("belief-1", reason="x")
        from agent_core.semantic.indexer import make_belief_entry_id
        assert make_belief_entry_id("e1") in fake.removed
        assert fake.saved >= 1
        assert mq.invalidated >= 1

    def test_vector_kept_when_active_belief_remains(self, tmp_path):
        wm = _wm(tmp_path)
        fake = _FakeSemantic()
        wm.set_unlearn_handles(semantic_memory=fake)
        # Two beliefs for the same entity; retract one -> vector stays.
        wm.store.add(_belief(entity="e1", source_id="fa", belief_id="belief-1"))
        wm.store.add(_belief(entity="e1", source_id="fb", belief_id="belief-2"))
        wm.retract_belief("belief-1", reason="x")
        from agent_core.semantic.indexer import make_belief_entry_id
        assert make_belief_entry_id("e1") not in fake.removed  # active sibling keeps it

    def test_vector_readded_from_winner_on_unquarantine(self, tmp_path):
        wm = _wm(tmp_path)
        fake = _FakeSemantic()
        wm.set_unlearn_handles(semantic_memory=fake)
        wm.store.add(_belief(entity="e1", belief_id="belief-1", conf=0.8))
        wm.quarantine_belief("belief-1")
        wm.unquarantine_belief("belief-1")
        # Re-add happened (entity restored to active).
        assert any(entry_id.endswith("e1") or "e1" in entry_id
                   for (_, entry_id, _, _) in fake.added)

    def test_ops_work_without_semantic_handle(self, tmp_path):
        wm = _wm(tmp_path)  # no handles set
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))
        res = wm.retract_belief("belief-1", reason="x")
        assert res["ok"]  # vector ops gracefully skipped

    def test_lock_busy_returns_explicit_error(self, tmp_path, monkeypatch):
        import agent_core.world_model as wmmod
        monkeypatch.setattr(wmmod, "_UNLEARN_LOCK_TIMEOUT", 0.05)
        wm = _wm(tmp_path)
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))
        wm._maintenance_lock.acquire()  # hold the lock
        try:
            res = wm.retract_belief("belief-1", reason="x")
        finally:
            wm._maintenance_lock.release()
        assert res["ok"] is False
        assert "busy" in res["message"]
        assert wm.store.get("belief-1").status == "active"  # NOT dropped

    def test_reapply_pending_retractions_on_boot(self, tmp_path):
        # Simulate a crash: ledger has a retract, but beliefs.jsonl still shows
        # the belief active (the save was lost).
        wm = _wm(tmp_path)
        retraction_log.append_retraction(tmp_path / "retractions.jsonl", {
            "op": "retract", "actor": "operator", "reason": "crash-case",
            "target_entities": ["e1"], "target_belief_ids": ["belief-1"],
        })
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))  # still active
        n = wm.reapply_pending_retractions()
        assert n == 1
        assert wm.store.get("belief-1").status == "retracted"

    def test_reapply_skips_when_unquarantine_is_latest(self, tmp_path):
        wm = _wm(tmp_path)
        p = tmp_path / "retractions.jsonl"
        retraction_log.append_retraction(p, {"op": "quarantine", "target_entities": ["e1"]}, now_ts=1.0)
        retraction_log.append_retraction(p, {"op": "unquarantine", "target_entities": ["e1"]}, now_ts=2.0)
        wm.store.add(_belief(entity="e1", belief_id="belief-1"))  # active
        n = wm.reapply_pending_retractions()
        assert n == 0  # latest op is unquarantine -> stays active
        assert wm.store.get("belief-1").status == "active"

    def test_forget_source_denylists_with_zero_live_beliefs(self, tmp_path):
        wm = _wm(tmp_path)
        res = wm.forget_source("ghost_source", reason="preempt")
        assert res["ok"] and res["count"] == 0 and res["source_denylisted"]
        assert retraction_log.load_denylist(tmp_path / "denylist.jsonl")["source"] == {"ghost_source"}
        # A ledger record was still written (audit of the denylist-only action).
        assert wm.list_retractions()[0]["source_scope"]["value"] == "ghost_source"


class TestCensusAndFlag:
    def test_census_counts_and_clean_desync(self, tmp_path):
        wm = _wm(tmp_path)
        wm.store.add(_belief(entity="a", belief_id="b1"))
        wm.store.add(_belief(entity="b", belief_id="b2"))
        wm.quarantine_belief("b1")
        c = wm.census_unlearn()
        assert c["by_status"]["active"] == 1
        assert c["by_status"]["quarantined"] == 1
        assert c["desync_count"] == 0  # quarantine evicts via build gate, no desync

    def test_census_detects_entity_desync(self, tmp_path):
        wm = _wm(tmp_path)
        # An ACTIVE belief whose entity is on the denylist = the guard half-failed.
        wm.store.add(_belief(entity="leaked", belief_id="b1"))
        retraction_log.append_denylist_entry(
            tmp_path / "denylist.jsonl", "entity", "leaked", reason="should be gone")
        c = wm.census_unlearn()
        assert c["desync_count"] == 1
        assert c["desync"][0]["entity"] == "leaked"
        assert c["desync"][0]["scope"] == "entity"

    def test_census_detects_source_desync(self, tmp_path):
        wm = _wm(tmp_path)
        wm.store.add(create_belief(
            entity="synthesis_z", entity_type=EntityType.FILE,
            belief_type=BeliefType.OBSERVATION, content="c", confidence=0.5,
            source=BeliefSource.LEARNING, source_id="file:synthesis_z", belief_id="bf"))
        retraction_log.append_denylist_entry(
            tmp_path / "denylist.jsonl", "source", "synthesis_z", reason="bad")
        c = wm.census_unlearn()
        assert c["desync_count"] == 1
        assert c["desync"][0]["scope"] == "source"

    def test_retraction_mode_resolver(self, monkeypatch):
        monkeypatch.delenv("RETRACTION_ENABLED", raising=False)
        assert retraction_log.retraction_mode() == "off"
        monkeypatch.setenv("RETRACTION_ENABLED", "observe")
        assert retraction_log.retraction_mode() == "observe"
        monkeypatch.setenv("RETRACTION_ENABLED", "armed")
        assert retraction_log.retraction_mode() == "armed"
        monkeypatch.setenv("RETRACTION_ENABLED", "garbage")
        assert retraction_log.retraction_mode() == "off"
