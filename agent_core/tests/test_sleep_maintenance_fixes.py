"""
Regression tests for the 2026-06-10 sleep/maintenance fixes (consolidation
Etap 1 -- "sen, ktory naprawde porzadkuje").

Three silent defects were found and fixed:
1. Sleep wiring-order bug: core.set_belief_store() ran before
   ctx.world_model existed -> NREM2/NREM3 were a production no-op.
   (Wiring itself is verified live at restart via the boot log line;
   here we pin the BEHAVIORAL promise: a wired sleep does real work.)
2. compact_jsonl used a non-atomic truncate-and-write on beliefs.jsonl;
   now delegates to the atomic BeliefStore.compact() (tmp+os.replace)
   which also drops tombstones from memory.
3. find_semantic_duplicates called dict-style .get() on SearchResult
   (__slots__ object) -> AttributeError swallowed per belief -> always [].

Lesson applied (mock-hidden bugs): tests use REAL BeliefStore and the REAL
SearchResult/VectorEntry classes, with tmp_path-backed files (never the
live meta_data/ -- the daemon rewrites it hourly).
"""

import json
import threading
from pathlib import Path

import pytest

import agent_core.consciousness.sleep_processor as sleep_processor_module
from agent_core.consciousness.sleep_processor import SleepProcessor
from agent_core.llm.manager import LLMManager
from agent_core.memory.manager import MemoryManager
from agent_core.semantic.vector_store import SearchResult, VectorEntry
from agent_core.tests.spec_helpers import specced
from agent_core.world_model.belief_maintenance import (
    compact_jsonl,
    find_semantic_duplicates,
    run_maintenance,
)
from agent_core.world_model.belief_model import (
    BeliefSource,
    BeliefType,
    EntityType,
    create_belief,
)
from agent_core.world_model.belief_store import BeliefStore


def _belief(entity="topic", confidence=0.5, content=None, evidence=None):
    return create_belief(
        entity=entity,
        entity_type=EntityType.TOPIC,
        belief_type=BeliefType.OBSERVATION,
        content=content or f"About {entity}",
        confidence=confidence,
        source=BeliefSource.LEARNING,
        evidence=evidence,
    )


@pytest.fixture
def store(tmp_path):
    return BeliefStore(tmp_path / "beliefs.jsonl")


class TestAtomicCompact:
    """Fix 2: compact delegates to the atomic store.compact()."""

    def test_compact_drops_tombstones_from_memory_and_disk(self, store):
        # Two exact duplicates -> dedup merges them: a NEW merged belief is
        # added and BOTH originals become superseded_by tombstones in memory.
        a = _belief("python", 0.6, content="Python is a language")
        b = _belief("python", 0.4, content="Python is a language")
        store.add(a)
        store.add(b)
        store.save()

        from agent_core.world_model.belief_maintenance import deduplicate

        merged = deduplicate(store, None)
        assert merged == 1
        assert len(store._beliefs) > len(store.get_current())

        removed = compact_jsonl(store)

        # Return = disk lines minus current view (2 saved lines -> 1 merged).
        assert removed == 1
        # Memory shrunk too (old manual path left tombstones in memory).
        assert len(store._beliefs) == len(store.get_current()) == 1
        # Disk holds exactly the current (merged) view.
        lines = [
            json.loads(l)
            for l in store._path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert len(lines) == 1
        assert lines[0]["confidence"] == pytest.approx(0.6)  # max of pair

    def test_no_tmp_file_left_behind(self, store):
        store.add(_belief("ruby", 0.5))
        store.save()
        compact_jsonl(store)
        leftovers = list(store._path.parent.glob("*.tmp"))
        assert leftovers == []

    def test_run_maintenance_full_cycle_intact_file(self, store):
        for i in range(5):
            store.add(_belief(f"t{i}", 0.4 + i * 0.1))
        store.save()

        results = run_maintenance(store)

        assert set(results) == {"decayed", "deduped", "pruned", "compacted"}
        # The soul file parses cleanly line-by-line after the rewrite.
        for line in store._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)

    def test_fallback_path_is_atomic_for_ducktyped_store(self, tmp_path):
        """Stores without compact() (duck-typed) take the manual fallback --
        which must also leave no .tmp and a clean file."""

        class DuckStore:
            def __init__(self, path):
                self._path = path
                self._beliefs = {}
                self._dirty = set()

        duck = DuckStore(tmp_path / "duck.jsonl")
        b = _belief("duck", 0.5)
        duck._beliefs[b.belief_id] = b

        removed = compact_jsonl(duck)

        assert removed == 0  # nothing superseded
        assert duck._path.exists()
        assert list(tmp_path.glob("*.tmp")) == []


class _StubSemanticMemory:
    """Returns pre-baked REAL SearchResult objects (the API that broke)."""

    def __init__(self, results):
        self._results = results

    def search(self, query, namespace=None, top_k=3):
        return self._results


class TestSemanticDedupRealApi:
    """Fix 3: find_semantic_duplicates speaks the real SearchResult API."""

    def test_finds_pair_via_real_searchresult_objects(self, store):
        # Distinct entities: the metadata contract is entity-keyed (round 2,
        # same evening -- belief_id churns every revision) and same-entity
        # pairs are deliberately exact-dedup's job.
        keep = _belief("fotowoltaika", 0.9, content="Panele PV zamieniaja...")
        dup = _belief("energia PV", 0.4, content="PV to zamiana slonca...")
        store.add(keep)
        store.add(dup)

        hit = SearchResult(
            VectorEntry(
                entry_id="vec-1",
                text=dup.content,
                vector=[0.0],
                metadata={"entity": dup.entity},
            ),
            score=0.96,
        )
        sem = _StubSemanticMemory([hit])

        pairs = find_semantic_duplicates(store, sem, similarity_threshold=0.95)

        # Pre-fix this was always [] (AttributeError swallowed per belief).
        assert pairs, "real SearchResult objects must yield a pair"
        keep_id, remove_id, sim = pairs[0]
        assert {keep_id, remove_id} == {keep.belief_id, dup.belief_id}
        assert keep_id == keep.belief_id  # higher confidence wins
        assert sim == pytest.approx(0.96)

    def test_tolerates_entry_without_entity_metadata(self, store):
        store.add(_belief("x", 0.5))
        hit = SearchResult(
            VectorEntry("vec-2", "text", [0.0], metadata={}), score=0.99
        )
        pairs = find_semantic_duplicates(store, _StubSemanticMemory([hit]))
        assert pairs == []

    def test_empty_namespace_returns_empty(self, store):
        store.add(_belief("y", 0.5))
        pairs = find_semantic_duplicates(store, _StubSemanticMemory([]))
        assert pairs == []


@pytest.fixture
def no_archiver(monkeypatch):
    """Keep tests OFF the real LogArchiver: with /mnt/storage mounted the
    archival phase would rewrite LIVE meta_data logs while the daemon runs
    (adversarial review, blocker #2). Also resets the module-global cache."""
    monkeypatch.setattr(sleep_processor_module, "_log_archiver", None)
    monkeypatch.setattr(sleep_processor_module, "_get_archiver", lambda: None)


class TestSleepDoesRealWorkWhenWired:
    """Fix 1 behavioral promise: a SleepProcessor WITH a store acts on it."""

    def test_nrem2_boosts_evidenced_beliefs(self, store, tmp_path, no_archiver):
        evidenced = _belief(
            "evidenced",
            0.5,
            evidence=[("doc", "a.txt", 0.8), ("web", "b.html", 0.7)],
        )
        bare = _belief("bare", 0.5)
        store.add(evidenced)
        store.add(bare)

        proc = SleepProcessor(
            belief_store=store,
            session_id=1,
            dream_log_path=tmp_path / "dreams.jsonl",
            knowledge_index_path=tmp_path / "ki.jsonl",
        )
        report = proc.process_sleep_cycle()

        nrem2 = report["phases"]["nrem2"]
        assert nrem2["beliefs_boosted"] == 1
        current = {b.entity: b for b in store.get_current()}
        assert current["evidenced"].confidence == pytest.approx(0.52)
        assert current["bare"].confidence == pytest.approx(0.5)
        nrem3 = report["phases"]["nrem3"]
        assert nrem3["beliefs_before"] >= 2
        # The archiver fixture really took: archival must be the skipped stub.
        assert report["phases"]["archival"].get("skipped") is True

    def test_unwired_sleep_reports_zeros(self, tmp_path, no_archiver):
        """The no-op signature we can now spot in homeostasis events."""
        proc = SleepProcessor(
            belief_store=None,
            session_id=1,
            dream_log_path=tmp_path / "dreams.jsonl",
            knowledge_index_path=tmp_path / "ki.jsonl",
        )
        report = proc.process_sleep_cycle()
        assert report["phases"]["nrem2"]["beliefs_boosted"] == 0
        assert report["phases"]["nrem3"]["beliefs_before"] == 0
        assert report["phases"]["archival"].get("skipped") is True


class _SpyProcessor:
    """Records the belief_store + mutate flag the core handed over; no files."""

    last_store = "UNSET"
    last_mutate = "UNSET"

    def __init__(self, belief_store=None, session_id=0, mutate_beliefs=True, **kwargs):
        _SpyProcessor.last_store = belief_store
        _SpyProcessor.last_mutate = mutate_beliefs

    def process_sleep_cycle(self):
        return {"phases": {}, "phases_completed": 5, "dreams": []}


class TestSleepCycleGuards:
    """Blocker fixes: the core throttles belief phases to ~1/20h and skips
    them while a planner thread (the other lock-free-store mutator) lives."""

    @pytest.fixture
    def core(self, tmp_path, monkeypatch, store):
        from agent_core.homeostasis.core import HomeostasisCore
        from agent_core.homeostasis.event_logger import (
            HomeostasisEventLogger,
        )

        monkeypatch.setattr(
            sleep_processor_module, "SleepProcessor", _SpyProcessor
        )
        _SpyProcessor.last_store = "UNSET"
        _SpyProcessor.last_mutate = "UNSET"
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
            event_logger=HomeostasisEventLogger(
                log_path=tmp_path / "events.jsonl", log_startup=False
            ),
        )
        core.set_belief_store(store)
        return core

    def _last_event(self, core) -> dict:
        # The logger buffers events (flush on size/interval) -- read the
        # buffer first, fall back to the file if a flush already happened.
        buffer = list(core.event_logger._buffer)
        if buffer:
            return buffer[-1]
        path = Path(core.event_logger.log_path)
        lines = [
            l for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        return json.loads(lines[-1])

    def test_first_sleep_runs_belief_phases(self, core, store):
        core._run_sleep_cycle()
        assert _SpyProcessor.last_store is store
        assert _SpyProcessor.last_mutate is True
        event = self._last_event(core)
        assert event["belief_phases_ran"] is True
        assert event["belief_skip_reason"] is None
        assert core._last_belief_sleep_ts > 0

    def test_second_sleep_within_gap_is_throttled(self, core, store):
        core._run_sleep_cycle()
        core._run_sleep_cycle()
        # REM still gets the store to read (dreams fire on throttled sleeps),
        # but belief MUTATION (NREM2/3) is throttled off.
        assert _SpyProcessor.last_store is store
        assert _SpyProcessor.last_mutate is False
        event = self._last_event(core)
        assert event["belief_phases_ran"] is False
        assert event["belief_skip_reason"] == "throttled"

    def test_alive_planner_thread_skips_belief_phases(self, core):
        release = threading.Event()
        t = threading.Thread(target=release.wait, daemon=True)
        t.start()
        core._planner_thread = t
        try:
            core._run_sleep_cycle()
        finally:
            release.set()
            t.join(timeout=2)
        assert _SpyProcessor.last_store is None
        event = self._last_event(core)
        assert event["belief_skip_reason"] == "planner_alive"
        # A skipped pass must NOT consume the 20h budget.
        assert core._last_belief_sleep_ts == 0.0

    def _make_core(self, tmp_path, store):
        """Mirror of the fixture: a core on the SAME event-log directory."""
        from agent_core.homeostasis.core import HomeostasisCore
        from agent_core.homeostasis.event_logger import (
            HomeostasisEventLogger,
        )

        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
            event_logger=HomeostasisEventLogger(
                log_path=tmp_path / "events.jsonl", log_startup=False
            ),
        )
        core.set_belief_store(store)
        return core

    def test_throttle_stamp_survives_restart(self, core, store, tmp_path):
        """Audyt 2026-06-12: licznik byl in-memory -- kazdy restart zerowal
        bramke 20h (3 boost-passy w 21h na deploy-day). Stempel na dysku
        obok event-logu musi zdlawic boost po 'restarcie'."""
        core._run_sleep_cycle()
        assert _SpyProcessor.last_store is store
        assert core._belief_sleep_throttle_path.exists()

        # "Restart": swiezy core na tym samym katalogu event-logu.
        core2 = self._make_core(tmp_path, store)
        assert core2._last_belief_sleep_ts == core._last_belief_sleep_ts

        core2._run_sleep_cycle()
        # Throttled after restart: store still handed over for REM reads, but
        # mutation stays off so the stamp keeps dampening the boost.
        assert _SpyProcessor.last_store is store
        assert _SpyProcessor.last_mutate is False
        event = self._last_event(core2)
        assert event["belief_skip_reason"] == "throttled"

    def test_corrupt_stamp_falls_back_to_zero(self, core, store, tmp_path):
        """Uszkodzony/smieciowy stempel = 0.0 (boost wolny), nie wyjatek."""
        (tmp_path / "belief_sleep_throttle.json").write_text("nie-json{")
        core2 = self._make_core(tmp_path, store)
        assert core2._last_belief_sleep_ts == 0.0


class TestWiringOrderSourceLock:
    """Regression lock for the headline bug: set_belief_store must come
    AFTER ctx.world_model assignment in HomeostasisModule.init. A full
    module-init integration test is too heavy/flaky (live stores, Telegram,
    NIM), so this locks the source order -- same spirit as doc_lint."""

    def test_wiring_follows_world_model_assignment(self):
        import agent_core.modules.homeostasis_module as hm

        source = Path(hm.__file__).read_text(encoding="utf-8")
        assignment = source.index("ctx.world_model = world_model")
        wiring = source.index("core.set_belief_store(world_model.store)")
        assert wiring > assignment, (
            "set_belief_store must run AFTER ctx.world_model is assigned "
            "(the pre-2026-06-10 order made sleep consolidation a no-op)"
        )
        # The old dead pattern must not come back.
        assert "core.set_belief_store(ctx.world_model.store)" not in source
