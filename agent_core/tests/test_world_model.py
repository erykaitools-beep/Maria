"""
Tests for K6 World Model / Belief System.

Covers:
- belief_model.py: enums, Belief dataclass, create_belief, serialization
- belief_store.py: load/save JSONL, MERGE, revise, indexes, cap
- belief_builder.py: build_topic/file/concept_beliefs, update_from_exam
- query.py: 5 query methods
- __init__.py: WorldModel facade
- Planner integration: context includes world_summary, exam triggers revision
"""

import json
import time
from pathlib import Path

import pytest

from agent_core.world_model.belief_model import (
    Belief, BeliefType, BeliefSource, EntityType, create_belief,
)
from agent_core.world_model.belief_store import BeliefStore, MAX_CURRENT_BELIEFS
from agent_core.world_model.belief_builder import BeliefBuilder, _normalize_tag
from agent_core.world_model.query import WorldModelQuery
from agent_core.world_model import WorldModel
from agent_core.tests.spec_helpers import specced
from agent_core.goals.store import GoalStore
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import SystemState
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.planner.action_executor import ActionExecutor


# ============================================================
# belief_model.py
# ============================================================

class TestEntityType:
    def test_all_values(self):
        assert EntityType.TOPIC.value == "topic"
        assert EntityType.FILE.value == "file"
        assert EntityType.CONCEPT.value == "concept"
        assert EntityType.MODULE.value == "module"
        assert EntityType.PERSON.value == "person"
        assert EntityType.PLACE.value == "place"

    def test_from_string(self):
        assert EntityType("topic") == EntityType.TOPIC
        assert EntityType("file") == EntityType.FILE


class TestBeliefType:
    def test_all_values(self):
        assert BeliefType.FACT.value == "fact"
        assert BeliefType.OBSERVATION.value == "observation"
        assert BeliefType.HYPOTHESIS.value == "hypothesis"


class TestBeliefSource:
    def test_all_values(self):
        assert BeliefSource.LEARNING.value == "learning"
        assert BeliefSource.EXAM.value == "exam"
        assert BeliefSource.MEMORY_FACT.value == "memory_fact"
        assert BeliefSource.SYSTEM.value == "system"
        assert BeliefSource.USER.value == "user"


class TestCreateBelief:
    def test_basic_creation(self):
        b = create_belief(
            entity="python",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION,
            content="Temat python",
            confidence=0.7,
            source=BeliefSource.LEARNING,
        )
        assert b.entity == "python"
        assert b.entity_type == EntityType.TOPIC
        assert b.belief_type == BeliefType.OBSERVATION
        assert b.confidence == 0.7
        assert b.revision == 1
        assert b.superseded_by is None
        assert b.belief_id.startswith("belief-")

    def test_tags_as_tuple(self):
        b = create_belief(
            entity="python",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT,
            content="test",
            confidence=0.5,
            source=BeliefSource.LEARNING,
            tags=["python", "programming"],
        )
        assert isinstance(b.tags, tuple)
        assert b.tags == ("python", "programming")

    def test_related_entities_as_tuple(self):
        b = create_belief(
            entity="x",
            entity_type=EntityType.CONCEPT,
            belief_type=BeliefType.OBSERVATION,
            content="test",
            confidence=0.5,
            source=BeliefSource.LEARNING,
            related_entities=["file1.txt", "file2.txt"],
        )
        assert isinstance(b.related_entities, tuple)
        assert len(b.related_entities) == 2

    def test_confidence_clamped_high(self):
        b = create_belief(
            entity="x", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT, content="t",
            confidence=1.5, source=BeliefSource.LEARNING,
        )
        assert b.confidence == 1.0

    def test_confidence_clamped_low(self):
        b = create_belief(
            entity="x", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT, content="t",
            confidence=-0.3, source=BeliefSource.LEARNING,
        )
        assert b.confidence == 0.0

    def test_custom_belief_id(self):
        b = create_belief(
            entity="x", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT, content="t",
            confidence=0.5, source=BeliefSource.LEARNING,
            belief_id="my-custom-id",
        )
        assert b.belief_id == "my-custom-id"

    def test_frozen(self):
        b = create_belief(
            entity="x", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT, content="t",
            confidence=0.5, source=BeliefSource.LEARNING,
        )
        with pytest.raises(AttributeError):
            b.confidence = 0.9


class TestBeliefSerialization:
    def test_to_dict(self):
        b = create_belief(
            entity="python",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT,
            content="Python is great",
            confidence=0.8,
            source=BeliefSource.EXAM,
            source_id="exam:123",
            tags=["python"],
        )
        d = b.to_dict()
        assert d["entity"] == "python"
        assert d["entity_type"] == "topic"
        assert d["belief_type"] == "fact"
        assert d["confidence"] == 0.8
        assert d["source"] == "exam"
        assert d["tags"] == ["python"]
        assert isinstance(d["tags"], list)  # Not tuple

    def test_from_dict(self):
        d = {
            "belief_id": "test-001",
            "entity": "math",
            "entity_type": "topic",
            "belief_type": "observation",
            "content": "Math topic",
            "confidence": 0.6,
            "source": "learning",
            "source_id": "src:1",
            "tags": ["math", "science"],
            "created_at": 100.0,
            "updated_at": 200.0,
            "revision": 2,
            "superseded_by": None,
            "related_entities": ["file1.txt"],
        }
        b = Belief.from_dict(d)
        assert b.belief_id == "test-001"
        assert b.entity_type == EntityType.TOPIC
        assert b.belief_type == BeliefType.OBSERVATION
        assert b.tags == ("math", "science")
        assert b.related_entities == ("file1.txt",)
        assert b.revision == 2

    def test_roundtrip(self):
        original = create_belief(
            entity="test",
            entity_type=EntityType.CONCEPT,
            belief_type=BeliefType.HYPOTHESIS,
            content="A hypothesis",
            confidence=0.3,
            source=BeliefSource.SYSTEM,
            tags=["a", "b"],
            related_entities=["c"],
        )
        d = original.to_dict()
        restored = Belief.from_dict(d)
        assert restored.entity == original.entity
        assert restored.entity_type == original.entity_type
        assert restored.belief_type == original.belief_type
        assert restored.confidence == original.confidence
        assert restored.tags == original.tags


# ============================================================
# belief_store.py
# ============================================================

class TestBeliefStore:
    def _make_store(self, tmp_path):
        return BeliefStore(tmp_path / "beliefs.jsonl")

    def _make_belief(self, entity="test", confidence=0.5, **kwargs):
        return create_belief(
            entity=entity,
            entity_type=kwargs.get("entity_type", EntityType.TOPIC),
            belief_type=kwargs.get("belief_type", BeliefType.OBSERVATION),
            content=kwargs.get("content", f"About {entity}"),
            confidence=confidence,
            source=kwargs.get("source", BeliefSource.LEARNING),
            source_id=kwargs.get("source_id", ""),
            tags=kwargs.get("tags", [entity]),
            related_entities=kwargs.get("related_entities", []),
        )

    def test_empty_load(self, tmp_path):
        store = self._make_store(tmp_path)
        count = store.load()
        assert count == 0

    def test_add_and_get(self, tmp_path):
        store = self._make_store(tmp_path)
        b = self._make_belief("python")
        store.add(b)
        retrieved = store.get(b.belief_id)
        assert retrieved is not None
        assert retrieved.entity == "python"

    def test_save_and_load(self, tmp_path):
        store = self._make_store(tmp_path)
        b = self._make_belief("python", confidence=0.8)
        store.add(b)
        store.save()

        store2 = self._make_store(tmp_path)
        count = store2.load()
        assert count == 1
        loaded = store2.get(b.belief_id)
        assert loaded.entity == "python"
        assert loaded.confidence == 0.8

    def test_merge_semantics(self, tmp_path):
        """Last record per belief_id wins on load."""
        path = tmp_path / "beliefs.jsonl"
        b1 = self._make_belief("python", confidence=0.5, belief_type=BeliefType.OBSERVATION)
        # Write two versions with same belief_id (simulate append)
        with open(path, "w", encoding="utf-8") as f:
            d1 = b1.to_dict()
            f.write(json.dumps(d1) + "\n")
            d2 = d1.copy()
            d2["confidence"] = 0.9
            d2["belief_type"] = "fact"
            f.write(json.dumps(d2) + "\n")

        store = BeliefStore(path)
        store.load()
        loaded = store.get(b1.belief_id)
        assert loaded.confidence == 0.9
        assert loaded.belief_type == BeliefType.FACT

    def test_compact_beliefs(self, tmp_path):
        path = tmp_path / "beliefs.jsonl"
        store = BeliefStore(path)

        beliefs = [
            self._make_belief("topic-a", confidence=0.5),
            self._make_belief("topic-b", confidence=0.6),
            self._make_belief("topic-c", confidence=0.7),
        ]
        for belief in beliefs:
            store.add(belief)
        store.save()

        current_ids = [belief.belief_id for belief in beliefs]
        for i in range(10):
            next_ids = []
            for belief_id in current_ids:
                revised = store.revise(
                    belief_id,
                    min(1.0, 0.1 + i * 0.05),
                    BeliefType.FACT,
                )
                if revised is not None:
                    next_ids.append(revised.belief_id)
                else:
                    next_ids.append(belief_id)
                store.save()
            current_ids = next_ids

        # Final state: file and memory both hold only the 3 active revised
        # beliefs — _compact_if_needed keeps them in sync during save().
        # An explicit compact() is a no-op at this point.
        store.compact()
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        current_count = sum(1 for b in store._beliefs.values() if b.superseded_by is None)
        assert len(lines) == current_count
        assert current_count == 3

    def test_load_corrupted_jsonl_line(self, tmp_path):
        path = tmp_path / "beliefs.jsonl"
        good = self._make_belief("good-topic", confidence=0.8)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(good.to_dict()) + "\n")
            f.write("{bad json\n")
            f.write(json.dumps(good.to_dict()) + "\n")

        store = BeliefStore(path)
        count = store.load()
        assert count == 1
        assert store.get(good.belief_id) is not None

    def test_get_by_entity(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add(self._make_belief("python"))
        store.add(self._make_belief("python", source_id="s2"))
        store.add(self._make_belief("math"))
        results = store.get_by_entity("python")
        assert len(results) == 2

    def test_get_by_entity_type(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add(self._make_belief("python", entity_type=EntityType.TOPIC))
        store.add(self._make_belief("file1", entity_type=EntityType.FILE))
        topics = store.get_by_entity_type(EntityType.TOPIC)
        assert len(topics) == 1
        assert topics[0].entity == "python"

    def test_get_by_tag(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add(self._make_belief("a", tags=["python", "programming"]))
        store.add(self._make_belief("b", tags=["math"]))
        store.add(self._make_belief("c", tags=["python"]))
        results = store.get_by_tag("python")
        assert len(results) == 2

    def test_get_current_excludes_superseded(self, tmp_path):
        store = self._make_store(tmp_path)
        b = self._make_belief("python")
        store.add(b)
        store.revise(b.belief_id, 0.9)
        current = store.get_current()
        # Only the revised version should be current
        assert len(current) == 1
        assert current[0].revision == 2

    def test_revise(self, tmp_path):
        store = self._make_store(tmp_path)
        b = self._make_belief("python", confidence=0.5)
        store.add(b)
        revised = store.revise(b.belief_id, 0.9, BeliefType.FACT)
        assert revised is not None
        assert revised.confidence == 0.9
        assert revised.belief_type == BeliefType.FACT
        assert revised.revision == 2
        # Old one is superseded
        old = store.get(b.belief_id)
        assert old.superseded_by == revised.belief_id

    def test_revise_nonexistent(self, tmp_path):
        store = self._make_store(tmp_path)
        result = store.revise("nonexistent", 0.5)
        assert result is None

    def test_revise_already_superseded(self, tmp_path):
        store = self._make_store(tmp_path)
        b = self._make_belief("python")
        store.add(b)
        store.revise(b.belief_id, 0.8)
        # Try to revise again - should fail (already superseded)
        result = store.revise(b.belief_id, 0.9)
        assert result is None

    def test_find_by_entity_and_source(self, tmp_path):
        store = self._make_store(tmp_path)
        b = self._make_belief("python", source_id="topic:python")
        store.add(b)
        found = store.find_by_entity_and_source("python", "topic:python")
        assert found is not None
        assert found.belief_id == b.belief_id

    def test_find_by_entity_and_source_not_found(self, tmp_path):
        store = self._make_store(tmp_path)
        found = store.find_by_entity_and_source("nonexistent", "src:1")
        assert found is None

    def test_stats(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add(self._make_belief("a", belief_type=BeliefType.FACT))
        store.add(self._make_belief("b", belief_type=BeliefType.OBSERVATION))
        store.add(self._make_belief("c", belief_type=BeliefType.OBSERVATION))
        s = store.stats()
        assert s["total"] == 3
        assert s["by_belief_type"]["fact"] == 1
        assert s["by_belief_type"]["observation"] == 2

    def test_enforce_cap(self, tmp_path):
        store = self._make_store(tmp_path)
        # Add MAX + 5 beliefs
        for i in range(MAX_CURRENT_BELIEFS + 5):
            store.add(self._make_belief(
                f"entity_{i}",
                confidence=i / (MAX_CURRENT_BELIEFS + 5),
                source_id=f"src:{i}",
            ))
        current = store.get_current()
        assert len(current) <= MAX_CURRENT_BELIEFS

    def test_append_only_save(self, tmp_path):
        """Save appends, doesn't rewrite."""
        store = self._make_store(tmp_path)
        store.add(self._make_belief("a"))
        store.save()
        store.add(self._make_belief("b"))
        store.save()

        path = tmp_path / "beliefs.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_bulk_mode_defers_enforce_cap(self, tmp_path):
        """In bulk_mode, add() does not trigger _enforce_cap per call.

        Regression guard: before this, BeliefBuilder.build_all() hung for
        minutes on a cold rebuild (~22k concept beliefs) because each add()
        ran an O(n) cap check — O(n²) overall.
        """
        store = self._make_store(tmp_path)
        call_count = {"enforce": 0}
        original_enforce = store._enforce_cap

        def counting_enforce():
            call_count["enforce"] += 1
            original_enforce()

        store._enforce_cap = counting_enforce

        with store.bulk_mode():
            for i in range(50):
                store.add(self._make_belief(f"e_{i}", source_id=f"s:{i}"))
            # Inside bulk_mode: no enforce calls
            assert call_count["enforce"] == 0

        # Exiting bulk_mode: exactly one enforce call
        assert call_count["enforce"] == 1

    def test_bulk_mode_restores_normal_behavior_on_exit(self, tmp_path):
        """After bulk_mode exits, add() resumes per-call cap enforcement."""
        store = self._make_store(tmp_path)
        with store.bulk_mode():
            store.add(self._make_belief("x", source_id="s:x"))

        # After exit, subsequent add should enforce normally
        count_before = {"enforce": 0}
        original = store._enforce_cap
        def counting():
            count_before["enforce"] += 1
            original()
        store._enforce_cap = counting

        store.add(self._make_belief("y", source_id="s:y"))
        assert count_before["enforce"] == 1

    def test_bulk_mode_cold_rebuild_is_fast(self, tmp_path):
        """A mass insert that exceeds the cap should complete in bounded time.

        Without bulk_mode: O(n²) prune-per-add makes this multi-second even
        for small N. With bulk_mode: O(n) + one prune at exit.
        """
        import time as _time
        store = self._make_store(tmp_path)
        # Insert 2x the cap to force pruning on exit
        n = MAX_CURRENT_BELIEFS * 2
        t0 = _time.time()
        with store.bulk_mode():
            for i in range(n):
                store.add(self._make_belief(
                    f"e_{i}",
                    confidence=i / n,
                    source_id=f"s:{i}",
                ))
        elapsed = _time.time() - t0
        # Generous bound — test environments vary. Without bulk_mode this
        # would take tens of seconds or minutes.
        assert elapsed < 10.0, f"Bulk insert of {n} too slow: {elapsed:.1f}s"
        # Cap enforced exactly once at exit — count must not exceed limit
        assert len(store.get_current()) <= MAX_CURRENT_BELIEFS

    # --- 2026-04-17 regression: unbounded JSONL growth via prune tombstones ---

    def test_enforce_cap_drops_from_memory(self, tmp_path):
        """Pruned beliefs must be dropped from memory, not kept as tombstones.

        Before fix: _enforce_cap marked excess beliefs with superseded_by="pruned"
        and kept them in _beliefs. After N prune cycles, _beliefs grew unboundedly.
        """
        store = self._make_store(tmp_path)
        for i in range(MAX_CURRENT_BELIEFS + 20):
            store.add(self._make_belief(
                f"e_{i}",
                confidence=i / (MAX_CURRENT_BELIEFS + 20),
                source_id=f"s:{i}",
            ))

        # After cap enforcement, in-memory dict must not contain tombstones.
        tombstones = [b for b in store._beliefs.values() if b.superseded_by == "pruned"]
        assert len(tombstones) == 0, f"Found {len(tombstones)} pruned tombstones in memory"
        assert len(store._beliefs) <= MAX_CURRENT_BELIEFS

    def test_enforce_cap_shrinks_jsonl(self, tmp_path):
        """After cap enforcement, the JSONL file must not keep dropped records.

        Regression: on restart, load() would read back all the pruned records
        as "current" (no superseded marker was ever written for drops) → memory
        bloat returns.
        """
        path = tmp_path / "beliefs.jsonl"
        store = BeliefStore(path)
        for i in range(MAX_CURRENT_BELIEFS + 50):
            store.add(self._make_belief(
                f"e_{i}",
                confidence=i / (MAX_CURRENT_BELIEFS + 50),
                source_id=f"s:{i}",
            ))
        store.save()

        # On cold reload, memory matches disk and stays within cap.
        store2 = BeliefStore(path)
        count = store2.load()
        assert count <= MAX_CURRENT_BELIEFS
        assert len(store2._beliefs) <= MAX_CURRENT_BELIEFS

    def test_repeated_prune_cycles_do_not_leak(self, tmp_path):
        """Simulate the real-world failure mode: repeated build→prune cycles
        must not cause unbounded in-memory or on-disk growth.

        Reproduces the bug from 2026-04-17 where 1.58M tombstone records
        accumulated in beliefs.jsonl over a single day of operation.
        """
        path = tmp_path / "beliefs.jsonl"
        store = BeliefStore(path)

        # 5 build cycles, each adding 2x cap worth of new concept beliefs.
        for cycle in range(5):
            with store.bulk_mode():
                for i in range(MAX_CURRENT_BELIEFS * 2):
                    store.add(self._make_belief(
                        f"cycle{cycle}_e_{i}",
                        confidence=i / (MAX_CURRENT_BELIEFS * 2),
                        source_id=f"cycle{cycle}:s:{i}",
                    ))
            store.save()

        # In-memory: bounded by cap.
        current = store.get_current()
        assert len(current) <= MAX_CURRENT_BELIEFS
        # No tombstones accumulated.
        tombstones = [b for b in store._beliefs.values() if b.superseded_by == "pruned"]
        assert len(tombstones) == 0, f"Tombstone leak: {len(tombstones)} found"
        # File must not hold 10x cap worth of records.
        lines = sum(1 for line in path.read_text().splitlines() if line.strip())
        assert lines <= MAX_CURRENT_BELIEFS * 3, \
            f"JSONL leak: {lines} lines for cap={MAX_CURRENT_BELIEFS}"

    def test_load_skips_pruned_tombstones(self, tmp_path):
        """load() must skip records with superseded_by='pruned' to avoid
        reloading forgotten beliefs into memory.

        Defense-in-depth: even if a file is authored with pruned records
        (e.g. pre-fix beliefs.jsonl from production), load stays clean.
        """
        path = tmp_path / "beliefs.jsonl"
        active = self._make_belief("active", source_id="s:active")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(active.to_dict()) + "\n")
            # 100 fake pruned tombstones
            for i in range(100):
                f.write(json.dumps({
                    "belief_id": f"belief-fake{i}",
                    "entity": f"entity_{i}",
                    "entity_type": "concept",
                    "belief_type": "observation",
                    "content": "pruned content",
                    "confidence": 0.1,
                    "source": "learning",
                    "source_id": f"s:{i}",
                    "tags": [],
                    "created_at": 0,
                    "updated_at": 0,
                    "revision": 1,
                    "superseded_by": "pruned",
                    "related_entities": [],
                    "evidence": [],
                }) + "\n")

        store = BeliefStore(path)
        count = store.load()
        assert count == 1
        assert store.get(active.belief_id) is not None
        assert len(store._beliefs) == 1  # all 100 tombstones skipped

    def test_compact_drops_all_superseded(self, tmp_path):
        """compact() must write only non-superseded beliefs to disk
        AND drop tombstones from memory (file and memory stay in sync).
        """
        store = self._make_store(tmp_path)
        for name in ("a", "b", "c"):
            store.add(self._make_belief(name, source_id=f"s:{name}"))
        store.save()

        # Revise "a" several times to accumulate superseded markers.
        a_id = store.get_by_entity("a")[0].belief_id
        for _ in range(5):
            revised = store.revise(a_id, 0.9)
            if revised is not None:
                a_id = revised.belief_id
            store.save()

        # Before compact: memory holds superseded markers.
        superseded_before = [b for b in store._beliefs.values() if b.superseded_by is not None]
        assert len(superseded_before) > 0

        removed = store.compact()
        assert removed > 0

        # After compact: no superseded in memory.
        superseded_after = [b for b in store._beliefs.values() if b.superseded_by is not None]
        assert len(superseded_after) == 0

        # File line count matches in-memory non-superseded count.
        path = tmp_path / "beliefs.jsonl"
        lines = sum(1 for line in path.read_text().splitlines() if line.strip())
        current_count = sum(1 for b in store._beliefs.values() if b.superseded_by is None)
        assert lines == current_count

    def test_drop_belief_removes_from_indexes(self, tmp_path):
        """drop_belief must remove from _beliefs and all three indexes."""
        store = self._make_store(tmp_path)
        b = self._make_belief("python", entity_type=EntityType.TOPIC, tags=["lang", "py"])
        store.add(b)

        assert store.get(b.belief_id) is not None
        assert b.belief_id in store._by_entity.get("python", [])
        assert b.belief_id in store._by_entity_type.get(EntityType.TOPIC, [])
        assert b.belief_id in store._by_tag.get("lang", [])

        assert store.drop_belief(b.belief_id) is True
        assert store.get(b.belief_id) is None
        assert b.belief_id not in store._by_entity.get("python", [])
        assert b.belief_id not in store._by_entity_type.get(EntityType.TOPIC, [])
        assert b.belief_id not in store._by_tag.get("lang", [])

        # Returning False for unknown id.
        assert store.drop_belief("does-not-exist") is False

    def test_load_autocompacts_when_heavily_pruned(self, tmp_path):
        """If a loaded file is dominated by pruned tombstones, load() auto-compacts."""
        path = tmp_path / "beliefs.jsonl"
        active = self._make_belief("active", source_id="s:active")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(active.to_dict()) + "\n")
            # Need > max(10*active, 1000) pruned to trigger auto-compact.
            for i in range(1500):
                f.write(json.dumps({
                    "belief_id": f"belief-old{i}",
                    "entity": "x",
                    "entity_type": "concept",
                    "belief_type": "observation",
                    "content": "old",
                    "confidence": 0.1,
                    "source": "learning",
                    "source_id": f"s:{i}",
                    "tags": [],
                    "created_at": 0,
                    "updated_at": 0,
                    "revision": 1,
                    "superseded_by": "pruned",
                    "related_entities": [],
                    "evidence": [],
                }) + "\n")

        size_before = path.stat().st_size
        store = BeliefStore(path)
        store.load()
        size_after = path.stat().st_size

        assert size_after < size_before // 10, \
            f"Auto-compact did not shrink file: {size_before} -> {size_after}"
        lines_after = sum(1 for line in path.read_text().splitlines() if line.strip())
        assert lines_after == 1


# ============================================================
# belief_builder.py
# ============================================================

class TestNormalizeTag:
    def test_basic(self):
        assert _normalize_tag("Python") == "python"

    def test_strip(self):
        assert _normalize_tag("  math  ") == "math"

    def test_too_short(self):
        assert _normalize_tag("x") is None

    def test_too_long(self):
        assert _normalize_tag("a" * 50) is None

    def test_stop_word(self):
        assert _normalize_tag("inne") is None
        assert _normalize_tag("ogolne") is None


class TestBeliefBuilder:
    def _write_jsonl(self, path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _make_builder(self, tmp_path):
        return BeliefBuilder(
            knowledge_index_path=tmp_path / "knowledge_index.jsonl",
            longterm_memory_path=tmp_path / "longterm_memory.jsonl",
            exam_results_path=tmp_path / "exam_results.jsonl",
        )

    def test_build_topic_beliefs(self, tmp_path):
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python", "programming"], "key_points": []},
            {"source_file": "f2.txt", "tags": ["python", "math"], "key_points": []},
            {"source_file": "f3.txt", "tags": ["math"], "key_points": []},
        ])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        count = builder.build_topic_beliefs(store)
        assert count == 3  # python, programming, math

        topics = store.get_by_entity_type(EntityType.TOPIC)
        names = {t.entity for t in topics}
        assert "python" in names
        assert "math" in names
        assert "programming" in names

    def test_topic_confidence_by_file_count(self, tmp_path):
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": f"f{i}.txt", "tags": ["popular"], "key_points": []}
            for i in range(5)
        ])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        builder.build_topic_beliefs(store)
        b = store.find_by_entity_and_source("popular", "topic:popular")
        assert b.confidence == 1.0  # 5/5 = 1.0

    def test_build_file_beliefs_completed(self, tmp_path):
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "file1.txt", "status": "completed", "last_scores": [0.8, 0.9]},
        ])
        # Trust gate (#2, hardened 2026-06-01): a belief is created only for a
        # 'completed' file that an INDEPENDENT examiner also verified.
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "file1.txt", "score": 0.85, "grader_independent": True},
        ])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        count = builder.build_file_beliefs(store)
        assert count == 1
        b = store.find_by_entity_and_source("file1.txt", "file:file1.txt")
        assert b.belief_type == BeliefType.FACT
        assert b.confidence == pytest.approx(0.85)

    def test_build_file_beliefs_completed_weak(self, tmp_path):
        """Completed but low score -> OBSERVATION belief (not FACT)."""
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "weak.txt", "status": "completed", "last_scores": [0.5]},
        ])
        # Independently verified (cleared the 0.6 bar) -> passes the trust gate;
        # the OBSERVATION/weak-confidence comes from the low knowledge_index
        # last_scores, not the gate.
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "weak.txt", "score": 0.6, "grader_independent": True},
        ])
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        builder.build_file_beliefs(store)
        b = store.find_by_entity_and_source("weak.txt", "file:weak.txt")
        assert b.belief_type == BeliefType.OBSERVATION
        assert b.confidence == pytest.approx(0.5)

    def test_build_file_beliefs_gated_non_completed(self, tmp_path):
        """Sandbox-first gate (#2, 2026-05-30): only exam-passed ('completed')
        knowledge becomes a canonical belief. Un-examined statuses (new /
        learning / learned / exam_failed) produce NO belief."""
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "f_new.txt", "status": "new"},
            {"id": "f_learning.txt", "status": "learning",
             "chunks_learned": 3, "total_chunks": 10},
            {"id": "f_learned.txt", "status": "learned"},
            {"id": "f_failed.txt", "status": "exam_failed"},
        ])
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        count = builder.build_file_beliefs(store)
        assert count == 0  # none are 'completed' -> no canonical belief
        for fid in ("f_new.txt", "f_learning.txt", "f_learned.txt", "f_failed.txt"):
            assert store.find_by_entity_and_source(fid, f"file:{fid}") is None

    def test_build_file_beliefs_gated_self_graded(self, tmp_path):
        """Audit 2026-06-01 #2: a 'completed' file with only a SELF-graded exam
        (no independent pass) must NOT become a canonical belief -- self-assessed
        knowledge stays provisional, out of the world model."""
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "selfgraded.txt", "status": "completed", "last_scores": [0.99]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "selfgraded.txt", "score": 0.99,
             "grader_independent": False, "grader_model": "llama3.1:8b"},
        ])
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        count = builder.build_file_beliefs(store)
        assert count == 0
        assert store.find_by_entity_and_source(
            "selfgraded.txt", "file:selfgraded.txt") is None

    def test_prune_unverified_file_beliefs(self, tmp_path):
        """Self-healing trust gate (#2, 2026-06-01): a file belief whose file
        is no longer independently verified is dropped on prune -- the
        existing-data half of the gate (build only stops NEW ones)."""
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "f.txt", "status": "completed", "last_scores": [0.9]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f.txt", "score": 0.9, "grader_independent": True},
        ])
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        assert builder.build_file_beliefs(store) == 1
        assert store.find_by_entity_and_source("f.txt", "file:f.txt") is not None

        # f.txt loses independent verification (latest record now self-graded)
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f.txt", "score": 0.99, "grader_independent": False,
             "grader_model": "llama3.1:8b"},
        ])
        dropped = builder.prune_unverified_file_beliefs(store)
        assert dropped == 1
        assert store.find_by_entity_and_source("f.txt", "file:f.txt") is None

    def test_prune_guard_skips_on_missing_results(self, tmp_path):
        """Guard: if exam_results is missing the verified set is untrusted, so
        prune is SKIPPED -- a transient read failure must never wipe the store."""
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "f.txt", "status": "completed", "last_scores": [0.9]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f.txt", "score": 0.9, "grader_independent": True},
        ])
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        builder.build_file_beliefs(store)
        (tmp_path / "exam_results.jsonl").unlink()   # results vanish
        dropped = builder.prune_unverified_file_beliefs(store)
        assert dropped == 0
        assert store.find_by_entity_and_source("f.txt", "file:f.txt") is not None

    def test_build_file_beliefs_merge_semantics(self, tmp_path):
        """Last record per id wins."""
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "file1.txt", "status": "new"},
            {"id": "file1.txt", "status": "completed", "last_scores": [0.9]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "file1.txt", "score": 0.9, "grader_independent": True},
        ])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        count = builder.build_file_beliefs(store)
        assert count == 1  # Only one belief for file1.txt
        b = store.find_by_entity_and_source("file1.txt", "file:file1.txt")
        assert b.belief_type == BeliefType.FACT

    def test_build_concept_beliefs(self, tmp_path):
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {
                "source_file": "f1.txt",
                "chunk_id": "chunk_001",
                "tags": ["python"],
                "key_points": ["Python uses indentation", "Python is interpreted"],
            },
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        count = builder.build_concept_beliefs(store)
        assert count == 2

        concepts = store.get_by_entity_type(EntityType.CONCEPT)
        assert len(concepts) == 2

    def test_concept_confidence_boosted_by_exam(self, tmp_path):
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {
                "source_file": "f1.txt",
                "chunk_id": "chunk_001",
                "tags": ["python"],
                "key_points": ["Python uses indentation"],
            },
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f1.txt", "score": 0.85},
        ])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        builder.build_concept_beliefs(store)
        concepts = store.get_by_entity_type(EntityType.CONCEPT)
        assert len(concepts) == 1
        assert concepts[0].confidence == 0.7  # 0.5 + 0.2
        assert concepts[0].belief_type == BeliefType.FACT

    def test_build_all(self, tmp_path):
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": ["KP1"]},
        ])
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "f1.txt", "status": "completed", "last_scores": [0.8]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f1.txt", "score": 0.8, "grader_independent": True},
        ])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        stats = builder.build_all(store)
        assert stats["topics"] >= 1
        assert stats["files"] >= 1
        assert stats["concepts"] >= 1

    def test_idempotent(self, tmp_path):
        """Building twice produces same count (dedup)."""
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": ["KP1"]},
        ])
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "f1.txt", "status": "new"},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [])

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        stats1 = builder.build_all(store)
        total1 = sum(stats1.values())

        # force=True bypasses the source watermark so this exercises the
        # entity+source existence dedup, not the cheap skip path.
        stats2 = builder.build_all(store, force=True)
        total2 = sum(stats2.values())
        assert total2 == 0  # All already exist

        assert store.stats()["total"] == total1

    # -- build_all source watermark (anti-washing-machine, 2026-06-11) --
    #
    # The hourly post-EVALUATE rebuild re-created ~32k cap-pruned beliefs
    # 24/7 with byte-identical sources ("Built beliefs: 11612 topics, 0
    # files, 20342 concepts" every hour, all night). Unchanged sources =>
    # identical candidate set => the only effect is resurrecting what the
    # cap pruned an hour earlier.

    def _watermark_fixture(self, tmp_path):
        builder = self._make_builder(tmp_path)
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": ["KP1"]},
        ])
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [])
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        return builder, store

    def test_build_all_skips_when_sources_unchanged(self, tmp_path):
        builder, store = self._watermark_fixture(tmp_path)
        builder.build_all(store)

        # Simulate the cap pruning a belief between builds.
        pruned = store.find_by_entity_and_source("python", "topic:python")
        assert store.drop_belief(pruned.belief_id)

        stats = builder.build_all(store)

        # Type-stable zeros: planner gates its log on any(stats.values()).
        assert stats == {"topics": 0, "files": 0, "concepts": 0}
        assert not any(stats.values())
        # The pruned belief was NOT resurrected -- no washing.
        assert store.find_by_entity_and_source("python", "topic:python") is None

    def test_build_all_reruns_when_a_source_changes(self, tmp_path):
        builder, store = self._watermark_fixture(tmp_path)
        builder.build_all(store)

        # Real change: a new learning record lands in longterm memory.
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": ["KP1"]},
            {"source_file": "f2.txt", "tags": ["rust"], "key_points": []},
        ])

        stats = builder.build_all(store)

        assert stats["topics"] >= 1  # 'rust' created -- pass really ran
        assert store.find_by_entity_and_source("rust", "topic:rust") is not None

    def test_build_all_force_overrides_watermark(self, tmp_path):
        builder, store = self._watermark_fixture(tmp_path)
        builder.build_all(store)
        pruned = store.find_by_entity_and_source("python", "topic:python")
        store.drop_belief(pruned.belief_id)

        stats = builder.build_all(store, force=True)

        assert stats["topics"] == 1  # manual rebuild resurrects
        assert store.find_by_entity_and_source("python", "topic:python") is not None

    def test_update_from_exam_pass(self, tmp_path):
        builder = self._make_builder(tmp_path)
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        b = create_belief(
            entity="f1.txt",
            entity_type=EntityType.FILE,
            belief_type=BeliefType.OBSERVATION,
            content="File f1.txt",
            confidence=0.5,
            source=BeliefSource.LEARNING,
            source_id="file:f1.txt",
        )
        store.add(b)

        revised = builder.update_from_exam(store, {"file": "f1.txt", "score": 0.85})
        assert revised == 1

        current = store.get_current()
        file_beliefs = [b for b in current if b.entity == "f1.txt"]
        assert len(file_beliefs) == 1
        assert file_beliefs[0].confidence == 0.6  # 0.5 + 0.1
        assert file_beliefs[0].belief_type == BeliefType.FACT

    def test_update_from_exam_fail(self, tmp_path):
        builder = self._make_builder(tmp_path)
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        b = create_belief(
            entity="f2.txt",
            entity_type=EntityType.FILE,
            belief_type=BeliefType.OBSERVATION,
            content="File f2.txt",
            confidence=0.5,
            source=BeliefSource.LEARNING,
            source_id="file:f2.txt",
        )
        store.add(b)

        revised = builder.update_from_exam(store, {"file": "f2.txt", "score": 0.3})
        assert revised == 1

        current = store.get_current()
        file_beliefs = [b for b in current if b.entity == "f2.txt"]
        assert len(file_beliefs) == 1
        assert file_beliefs[0].confidence == 0.35  # 0.5 - 0.15
        assert file_beliefs[0].belief_type == BeliefType.OBSERVATION  # Not upgraded

    def test_update_from_exam_no_file(self, tmp_path):
        builder = self._make_builder(tmp_path)
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        result = builder.update_from_exam(store, {"file": "", "score": 0.9})
        assert result == 0

    def test_empty_sources(self, tmp_path):
        builder = self._make_builder(tmp_path)
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        stats = builder.build_all(store)
        assert stats == {"topics": 0, "files": 0, "concepts": 0}


# ============================================================
# query.py
# ============================================================

class TestWorldModelQuery:
    def _make_store_with_beliefs(self, tmp_path):
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        # Add topic beliefs
        store.add(create_belief(
            entity="python", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Python topic",
            confidence=0.8, source=BeliefSource.LEARNING,
            source_id="topic:python", tags=["python"],
        ))
        store.add(create_belief(
            entity="math", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Math topic",
            confidence=0.3, source=BeliefSource.LEARNING,
            source_id="topic:math", tags=["math"],
        ))
        # Add file beliefs
        store.add(create_belief(
            entity="file1.txt", entity_type=EntityType.FILE,
            belief_type=BeliefType.FACT, content="File 1",
            confidence=0.9, source=BeliefSource.LEARNING,
            source_id="file:file1.txt", tags=["python"],
        ))
        # Add concept beliefs
        store.add(create_belief(
            entity="indentation", entity_type=EntityType.CONCEPT,
            belief_type=BeliefType.FACT, content="Python uses indentation",
            confidence=0.7, source=BeliefSource.MEMORY_FACT,
            source_id="concept:1", tags=["python"],
        ))
        store.add(create_belief(
            entity="algebra", entity_type=EntityType.CONCEPT,
            belief_type=BeliefType.OBSERVATION, content="Algebra basics",
            confidence=0.2, source=BeliefSource.MEMORY_FACT,
            source_id="concept:2", tags=["math"],
        ))
        return store

    def test_get_topic_confidence_map(self, tmp_path):
        store = self._make_store_with_beliefs(tmp_path)
        query = WorldModelQuery(store)
        conf_map = query.get_topic_confidence_map()
        assert "python" in conf_map
        assert "math" in conf_map
        # Python: topic 0.8, file 0.9, concept 0.7 -> avg (0.8+0.9+0.7)/3 = 0.8
        assert conf_map["python"] > 0.5

    def test_get_knowledge_gaps(self, tmp_path):
        store = self._make_store_with_beliefs(tmp_path)
        query = WorldModelQuery(store)
        gaps = query.get_knowledge_gaps()
        assert len(gaps) >= 2
        # Math should be weakest (0.3 topic, 0.2 concept)
        assert gaps[0]["topic"] == "math"
        assert gaps[0]["confidence"] < gaps[-1]["confidence"]

    def test_get_facts_for_topic(self, tmp_path):
        store = self._make_store_with_beliefs(tmp_path)
        query = WorldModelQuery(store)
        facts = query.get_facts_for_topic("python")
        assert len(facts) >= 1
        for f in facts:
            assert f.belief_type == BeliefType.FACT

    def test_get_facts_for_nonexistent_topic(self, tmp_path):
        store = self._make_store_with_beliefs(tmp_path)
        query = WorldModelQuery(store)
        facts = query.get_facts_for_topic("nonexistent")
        assert facts == []

    def test_get_entity_summary(self, tmp_path):
        store = self._make_store_with_beliefs(tmp_path)
        query = WorldModelQuery(store)
        summary = query.get_entity_summary("python")
        assert summary["entity"] == "python"
        assert summary["avg_confidence"] > 0
        assert summary["fact_count"] == 0  # topic belief is OBSERVATION
        assert summary["observation_count"] == 1

    def test_get_entity_summary_not_found(self, tmp_path):
        store = self._make_store_with_beliefs(tmp_path)
        query = WorldModelQuery(store)
        summary = query.get_entity_summary("nonexistent")
        assert summary["beliefs"] == []
        assert summary["avg_confidence"] == 0.0

    def test_get_world_summary(self, tmp_path):
        store = self._make_store_with_beliefs(tmp_path)
        query = WorldModelQuery(store)
        ws = query.get_world_summary()
        assert ws["total_beliefs"] == 5
        assert ws["facts"] == 2  # file1.txt + indentation
        assert ws["observations"] == 3  # python + math + algebra
        assert ws["topics"] == 2
        assert ws["avg_confidence"] > 0
        assert len(ws["weakest_topics"]) <= 5

    def test_empty_store(self, tmp_path):
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        query = WorldModelQuery(store)
        ws = query.get_world_summary()
        assert ws["total_beliefs"] == 0
        assert ws["avg_confidence"] == 0.0


# ============================================================
# __init__.py - WorldModel facade
# ============================================================

class TestWorldModelFacade:
    def _write_jsonl(self, path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def test_load_empty(self, tmp_path):
        wm = WorldModel(beliefs_path=tmp_path / "beliefs.jsonl")
        count = wm.load()
        assert count == 0

    def test_facade_exposes_build_not_build_all(self):
        """Regression guard: planner calls wm.build(), not wm.build_all().

        Historical bug: planner_core called self._world_model.build_all(),
        which only exists on wm.builder. The call raised AttributeError
        that was swallowed by try/except, silently preventing belief
        rebuilds for a full month after LEARN/EVALUATE cycles.
        """
        wm = WorldModel()
        assert hasattr(wm, "build"), "WorldModel facade must expose .build()"
        assert not hasattr(wm, "build_all"), (
            "WorldModel should NOT expose .build_all() — that's on .builder. "
            "If you need it on the facade, add a real method; don't let "
            "callers get AttributeError swallowed by try/except."
        )
        assert callable(wm.build)

    def test_build_and_stats(self, tmp_path):
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": ["KP1", "KP2"]},
        ])
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "f1.txt", "status": "completed", "last_scores": [0.8]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f1.txt", "score": 0.8, "grader_independent": True},
        ])

        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "knowledge_index.jsonl",
            longterm_memory_path=tmp_path / "longterm_memory.jsonl",
            exam_results_path=tmp_path / "exam_results.jsonl",
        )
        stats = wm.build()
        assert stats["topics"] >= 1
        assert stats["files"] >= 1
        assert wm.stats()["total"] > 0

    def test_reconcile_trust_prunes_unverified(self, tmp_path):
        """Facade reconcile_trust() drops a file belief that lost independent
        verification and persists -- the startup self-heal (#2, 2026-06-01)."""
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [
            {"id": "f.txt", "status": "completed", "last_scores": [0.9]},
        ])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f.txt", "score": 0.9, "grader_independent": True},
        ])
        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "knowledge_index.jsonl",
            longterm_memory_path=tmp_path / "longterm_memory.jsonl",
            exam_results_path=tmp_path / "exam_results.jsonl",
        )
        wm.build()
        wm.save()
        assert wm.store.find_by_entity_and_source("f.txt", "file:f.txt") is not None

        # f.txt loses independent verification
        self._write_jsonl(tmp_path / "exam_results.jsonl", [
            {"file": "f.txt", "score": 0.99, "grader_independent": False,
             "grader_model": "llama3.1:8b"},
        ])
        pruned = wm.reconcile_trust()
        assert pruned == 1
        assert wm.store.find_by_entity_and_source("f.txt", "file:f.txt") is None

    def test_save_and_reload(self, tmp_path):
        self._write_jsonl(tmp_path / "longterm_memory.jsonl", [
            {"source_file": "f1.txt", "tags": ["python"], "key_points": ["KP"]},
        ])
        self._write_jsonl(tmp_path / "knowledge_index.jsonl", [])
        self._write_jsonl(tmp_path / "exam_results.jsonl", [])

        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "knowledge_index.jsonl",
            longterm_memory_path=tmp_path / "longterm_memory.jsonl",
            exam_results_path=tmp_path / "exam_results.jsonl",
        )
        wm.build()
        wm.save()

        wm2 = WorldModel(beliefs_path=tmp_path / "beliefs.jsonl")
        count = wm2.load()
        assert count > 0

    def test_process_exam_result(self, tmp_path):
        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "ki.jsonl",
            longterm_memory_path=tmp_path / "lt.jsonl",
            exam_results_path=tmp_path / "er.jsonl",
        )
        # Manually add a belief
        b = create_belief(
            entity="f1.txt",
            entity_type=EntityType.FILE,
            belief_type=BeliefType.OBSERVATION,
            content="File f1",
            confidence=0.5,
            source=BeliefSource.LEARNING,
            source_id="file:f1.txt",
        )
        wm.store.add(b)

        revised = wm.process_exam_result({"file": "f1.txt", "score": 0.9})
        assert revised == 1

    def test_query_access(self, tmp_path):
        wm = WorldModel(beliefs_path=tmp_path / "beliefs.jsonl")
        assert hasattr(wm, "query")
        assert isinstance(wm.query, WorldModelQuery)


# ============================================================
# Planner integration
# ============================================================

class TestPlannerWorldModelIntegration:
    """Test K6 integration with PlannerCore."""

    def test_gather_context_includes_world_summary(self, tmp_path):
        from agent_core.planner.planner_core import PlannerCore

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        wm = WorldModel(beliefs_path=tmp_path / "beliefs.jsonl")
        wm.store.add(create_belief(
            entity="python", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Python",
            confidence=0.5, source=BeliefSource.LEARNING,
            tags=["python"],
        ))
        planner.set_world_model(wm)

        ctx = planner._gather_context()
        assert "world_summary" in ctx
        assert ctx["world_summary"]["total_beliefs"] == 1
        assert "knowledge_gaps" in ctx
        assert len(ctx["knowledge_gaps"]) >= 0

    def test_gather_context_without_world_model(self, tmp_path):
        from agent_core.planner.planner_core import PlannerCore

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        ctx = planner._gather_context()
        assert "world_summary" not in ctx
        assert "knowledge_gaps" not in ctx

    def test_goal_selector_accepts_world_summary(self):
        from agent_core.planner.goal_selector import GoalSelector

        selector = GoalSelector()
        # Just verify the parameter is accepted without error
        result = selector.select_goal(
            active_goals=[],
            evaluation_metrics={},
            knowledge_snapshot=None,
            world_summary={"total_beliefs": 10, "weakest_topics": ["math"]},
        )
        assert result is None  # No goals to select

    def test_auto_create_learning_goal_prefers_low_confidence(self, tmp_path):
        """K6: auto goal prefers topic with lowest confidence."""
        from unittest.mock import MagicMock
        from agent_core.planner.planner_core import PlannerCore

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        # Mock goal store
        goal_store = specced(GoalStore)
        goal_store.get_active.return_value = []
        planner.set_goal_store(goal_store)

        # Mock homeostasis - ACTIVE mode
        hcore = specced(HomeostasisCore)
        state_mock = specced(SystemState, mode=MagicMock())
        state_mock.mode.value = "active"
        hcore.get_state.return_value = state_mock
        planner.set_homeostasis_core(hcore)

        # Mock knowledge analyzer with topics
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_topic_file_map.return_value = {
            "python": ["f1.txt", "f2.txt"],  # 2 unfinished
            "math": ["f3.txt"],               # 1 unfinished
        }
        analyzer.get_knowledge_snapshot.return_value = {
            "new_files_available": ["f1.txt", "f2.txt", "f3.txt"],
            "learning_in_progress": [],
            "files_by_status": {"completed": []},
        }
        planner.set_knowledge_analyzer(analyzer)

        # Mock world model - math has lower confidence
        wm = specced(WorldModel, query=specced(WorldModelQuery))
        wm.query.get_topic_confidence_map.return_value = {
            "python": 0.8,
            "math": 0.2,
        }
        planner.set_world_model(wm)

        context = planner._gather_context()
        result = planner._auto_create_learning_goal(context)

        assert result is True
        # Verify goal was created with math (lower confidence)
        call_args = goal_store.create.call_args[0][0]
        assert "math" in call_args.metadata["topics"]

    def test_auto_create_learning_goal_fallback_without_world_model(self, tmp_path):
        """Without K6, falls back to most unfinished files."""
        from unittest.mock import MagicMock
        from agent_core.planner.planner_core import PlannerCore

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        goal_store = specced(GoalStore)
        goal_store.get_active.return_value = []
        planner.set_goal_store(goal_store)

        hcore = specced(HomeostasisCore)
        state_mock = specced(SystemState, mode=MagicMock())
        state_mock.mode.value = "active"
        hcore.get_state.return_value = state_mock
        planner.set_homeostasis_core(hcore)

        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_topic_file_map.return_value = {
            "python": ["f1.txt", "f2.txt", "f3.txt"],  # 3 unfinished
            "math": ["f4.txt"],                          # 1 unfinished
        }
        analyzer.get_knowledge_snapshot.return_value = {
            "new_files_available": ["f1.txt", "f2.txt", "f3.txt", "f4.txt"],
            "learning_in_progress": [],
            "files_by_status": {"completed": []},
        }
        planner.set_knowledge_analyzer(analyzer)
        # No world model set

        context = planner._gather_context()
        result = planner._auto_create_learning_goal(context)

        assert result is True
        # Without world model, picks topic with most unfinished files
        call_args = goal_store.create.call_args[0][0]
        assert "python" in call_args.metadata["topics"]

    def test_finalize_plan_updates_beliefs_after_exam(self, tmp_path):
        """After exam success, world model beliefs should be updated."""
        from unittest.mock import patch
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import ActionType

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        wm = specced(WorldModel, query=specced(WorldModelQuery))
        planner.set_world_model(wm)

        # Mock executor to return exam success
        planner.executor = specced(ActionExecutor)
        planner.executor.execute.return_value = {
            "success": True,
            "file": "f1.txt",
            "score": 0.85,
        }

        from agent_core.planner.planner_model import create_plan
        plan = create_plan(
            goal_id="g1",
            goal_description="Egzamin z python",
            action_type=ActionType.EXAM,
            action_params={},
        )

        planner._finalize_plan(plan)

        wm.process_exam_result.assert_called_once()
        wm.save.assert_called_once()

    def test_finalize_plan_no_belief_update_on_noop(self, tmp_path):
        """NOOP actions don't trigger belief updates."""
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import ActionType, create_plan

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        wm = specced(WorldModel, query=specced(WorldModelQuery))
        planner.set_world_model(wm)

        planner.executor = specced(ActionExecutor)
        planner.executor.execute.return_value = {"success": True}

        plan = create_plan(
            goal_id=None,
            goal_description="Nothing",
            action_type=ActionType.NOOP,
            action_params={},
        )

        planner._finalize_plan(plan)

        wm.process_exam_result.assert_not_called()


# ============================================================
# Belief Store v2: Evidence Tracking
# ============================================================


class TestBeliefEvidence:
    """Tests for v2 evidence field."""

    def test_create_belief_with_evidence(self):
        b = create_belief(
            entity="python",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT,
            content="Python jest jezykiem programowania",
            confidence=0.9,
            source=BeliefSource.LEARNING,
            evidence=[("learning", "topic:python", 0.9)],
        )
        assert len(b.evidence) == 1
        assert b.evidence[0] == ("learning", "topic:python", 0.9)

    def test_create_belief_without_evidence_default_empty(self):
        b = create_belief(
            entity="test",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION,
            content="test",
            confidence=0.5,
            source=BeliefSource.SYSTEM,
        )
        assert b.evidence == ()

    def test_evidence_serialization_roundtrip(self):
        b = create_belief(
            entity="fizyka",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT,
            content="Fizyka",
            confidence=0.8,
            source=BeliefSource.EXAM,
            evidence=[
                ("learning", "topic:fizyka", 0.6),
                ("exam", "exam:file_001", 0.85),
            ],
        )
        d = b.to_dict()
        assert "evidence" in d
        assert len(d["evidence"]) == 2

        restored = Belief.from_dict(d)
        assert len(restored.evidence) == 2
        assert restored.evidence[0] == ("learning", "topic:fizyka", 0.6)
        assert restored.evidence[1] == ("exam", "exam:file_001", 0.85)

    def test_from_dict_backward_compat_no_evidence(self):
        """Old belief records without evidence field should load fine."""
        d = {
            "belief_id": "belief-old",
            "entity": "test",
            "entity_type": "topic",
            "belief_type": "observation",
            "content": "old belief",
            "confidence": 0.5,
            "source": "system",
        }
        b = Belief.from_dict(d)
        assert b.evidence == ()

    def test_evidence_not_serialized_when_empty(self):
        b = create_belief(
            entity="test", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="test",
            confidence=0.5, source=BeliefSource.SYSTEM,
        )
        d = b.to_dict()
        assert "evidence" not in d

    def test_revise_merges_evidence(self, tmp_path):
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        b = create_belief(
            entity="fizyka", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Fizyka",
            confidence=0.5, source=BeliefSource.LEARNING,
            evidence=[("learning", "topic:fizyka", 0.5)],
        )
        store.add(b)

        revised = store.revise(
            b.belief_id, 0.8, BeliefType.FACT,
            new_evidence=[("exam", "exam:file_001", 0.85)],
        )
        assert revised is not None
        assert len(revised.evidence) == 2
        assert revised.evidence[0] == ("learning", "topic:fizyka", 0.5)
        assert revised.evidence[1] == ("exam", "exam:file_001", 0.85)

    def test_revise_dedup_evidence_by_ref(self, tmp_path):
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        b = create_belief(
            entity="fizyka", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Fizyka",
            confidence=0.5, source=BeliefSource.LEARNING,
            evidence=[("learning", "topic:fizyka", 0.5)],
        )
        store.add(b)

        # Same source_ref should not duplicate
        revised = store.revise(
            b.belief_id, 0.6,
            new_evidence=[("learning", "topic:fizyka", 0.6)],
        )
        assert len(revised.evidence) == 1  # Deduped


# ============================================================
# Belief Store v2: Compaction
# ============================================================


class TestCompaction:
    def test_compact_removes_superseded(self, tmp_path):
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        b1 = create_belief(
            entity="a", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="a",
            confidence=0.5, source=BeliefSource.SYSTEM,
        )
        store.add(b1)
        store.save()

        # Revise creates superseded record. _compact_if_needed may fire
        # automatically inside save() once the file grows past the
        # current-count threshold — so we check the invariant rather
        # than the exact transient line count.
        store.revise(b1.belief_id, 0.8)
        store.save()

        # Final invariant: file holds only non-superseded records, and
        # line count matches the in-memory current count.
        lines = len(open(tmp_path / "beliefs.jsonl").readlines())
        current = sum(1 for b in store._beliefs.values() if b.superseded_by is None)
        assert lines == current
        assert current == 1  # the revised belief

        # A further compact() is a no-op in this state (nothing to drop).
        store.compact()
        lines_after = len(open(tmp_path / "beliefs.jsonl").readlines())
        assert lines_after == 1

    def test_compact_preserves_current_beliefs(self, tmp_path):
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        for i in range(5):
            b = create_belief(
                entity=f"topic_{i}", entity_type=EntityType.TOPIC,
                belief_type=BeliefType.OBSERVATION, content=f"topic {i}",
                confidence=0.5, source=BeliefSource.SYSTEM,
            )
            store.add(b)
        store.save()

        before_count = len(store.get_current())
        store.compact()
        after_count = len(store.get_current())
        assert after_count == before_count

    def test_compact_on_empty_store(self, tmp_path):
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        removed = store.compact()
        assert removed == 0


# ============================================================
# Belief Store v2: Smart Pruning
# ============================================================


class TestSmartPruning:
    def test_compute_belief_score_factors(self):
        from agent_core.world_model.belief_maintenance import compute_belief_score
        now = time.time()

        # High confidence, fresh, high revision
        b_good = create_belief(
            entity="good", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT, content="good",
            confidence=0.9, source=BeliefSource.EXAM,
            belief_id="b-good", revision=5,
        )
        # Low confidence, stale, low revision
        b_bad = create_belief(
            entity="bad", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.HYPOTHESIS, content="bad",
            confidence=0.1, source=BeliefSource.SYSTEM,
            belief_id="b-bad", revision=1,
        )
        # Make b_bad appear old
        import dataclasses
        b_bad_old = dataclasses.replace(b_bad, updated_at=now - 86400 * 60)

        score_good = compute_belief_score(b_good, now, {"good": 5})
        score_bad = compute_belief_score(b_bad_old, now, {})

        assert score_good > score_bad
        assert score_good > 0.3
        assert score_bad < 0.3

    def test_smart_prune_keeps_high_scored(self, tmp_path):
        from agent_core.world_model.belief_maintenance import smart_prune
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        # Add 5 beliefs, cap at 3
        for i in range(5):
            b = create_belief(
                entity=f"t_{i}", entity_type=EntityType.TOPIC,
                belief_type=BeliefType.OBSERVATION, content=f"topic {i}",
                confidence=0.1 * (i + 1),  # 0.1, 0.2, 0.3, 0.4, 0.5
                source=BeliefSource.SYSTEM,
            )
            store.add(b)

        pruned = smart_prune(store, cap=3)
        assert pruned == 2
        current = store.get_current()
        assert len(current) == 3
        # Highest confidence beliefs should survive
        confs = sorted(b.confidence for b in current)
        assert confs[0] >= 0.3

    def test_smart_prune_no_action_under_cap(self, tmp_path):
        from agent_core.world_model.belief_maintenance import smart_prune
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        b = create_belief(
            entity="solo", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="solo",
            confidence=0.5, source=BeliefSource.SYSTEM,
        )
        store.add(b)
        assert smart_prune(store, cap=100) == 0


# ============================================================
# Belief Store v2: Confidence Decay
# ============================================================


class TestConfidenceDecay:
    def test_compute_decayed_confidence_30day_observation(self):
        from agent_core.world_model.belief_maintenance import compute_decayed_confidence
        now = time.time()
        b = create_belief(
            entity="test", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="test",
            confidence=0.8, source=BeliefSource.LEARNING,
        )
        # 30 days old with half_life=30 -> ~50% of original
        import dataclasses
        b_old = dataclasses.replace(b, updated_at=now - 86400 * 30)
        decayed = compute_decayed_confidence(b_old, now)
        assert 0.35 < decayed < 0.45  # ~0.4 (0.8 * 0.5)

    def test_fact_decays_slower_than_hypothesis(self):
        from agent_core.world_model.belief_maintenance import compute_decayed_confidence
        now = time.time()
        import dataclasses

        base = create_belief(
            entity="test", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.FACT, content="test",
            confidence=0.8, source=BeliefSource.EXAM,
        )
        b_fact = dataclasses.replace(base, updated_at=now - 86400 * 30)
        b_hypo = dataclasses.replace(
            base, belief_type=BeliefType.HYPOTHESIS,
            updated_at=now - 86400 * 30,
        )

        decay_fact = compute_decayed_confidence(b_fact, now)
        decay_hypo = compute_decayed_confidence(b_hypo, now)
        assert decay_fact > decay_hypo

    def test_decay_floor(self):
        from agent_core.world_model.belief_maintenance import compute_decayed_confidence, DECAY_FLOOR
        now = time.time()
        import dataclasses
        b = create_belief(
            entity="ancient", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.HYPOTHESIS, content="ancient",
            confidence=0.1, source=BeliefSource.SYSTEM,
        )
        b_ancient = dataclasses.replace(b, updated_at=now - 86400 * 365)
        decayed = compute_decayed_confidence(b_ancient, now)
        assert decayed >= DECAY_FLOOR

    def test_apply_decay_batch(self, tmp_path):
        from agent_core.world_model.belief_maintenance import apply_decay
        import dataclasses

        store = BeliefStore(tmp_path / "beliefs.jsonl")
        now = time.time()

        # Add a stale belief (60 days old)
        b = create_belief(
            entity="stale", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="stale topic",
            confidence=0.8, source=BeliefSource.LEARNING,
        )
        b_stale = dataclasses.replace(b, updated_at=now - 86400 * 60)
        store._beliefs[b_stale.belief_id] = b_stale

        revised = apply_decay(store, now=now)
        assert revised == 1

        # The revised belief should have lower confidence
        current = store.get_current()
        assert len(current) == 1
        assert current[0].confidence < 0.8

    def test_apply_decay_idempotent(self, tmp_path):
        from agent_core.world_model.belief_maintenance import apply_decay
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        # Fresh belief - should not be decayed
        b = create_belief(
            entity="fresh", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="fresh",
            confidence=0.8, source=BeliefSource.LEARNING,
        )
        store.add(b)

        # First pass: fresh belief should not decay much
        revised = apply_decay(store)
        # Second pass immediately: should revise 0
        revised2 = apply_decay(store)
        assert revised2 == 0

    def test_fresh_belief_not_decayed(self, tmp_path):
        from agent_core.world_model.belief_maintenance import apply_decay
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        b = create_belief(
            entity="fresh", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="fresh",
            confidence=0.8, source=BeliefSource.LEARNING,
        )
        store.add(b)
        revised = apply_decay(store)
        assert revised == 0  # Just created, delta < 0.05


# ============================================================
# Belief Store v2: Deduplication
# ============================================================


class TestDeduplication:
    def test_find_exact_duplicates(self, tmp_path):
        from agent_core.world_model.belief_maintenance import find_exact_duplicates
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        b1 = create_belief(
            entity="python", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Python jest jezykiem",
            confidence=0.5, source=BeliefSource.LEARNING,
        )
        b2 = create_belief(
            entity="python", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Python jest jezykiem",
            confidence=0.8, source=BeliefSource.EXAM,
        )
        store.add(b1)
        store.add(b2)

        pairs = find_exact_duplicates(store)
        assert len(pairs) == 1
        # Higher confidence should be kept
        assert pairs[0][0] == b2.belief_id

    def test_find_exact_no_duplicates(self, tmp_path):
        from agent_core.world_model.belief_maintenance import find_exact_duplicates
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        b1 = create_belief(
            entity="python", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Python",
            confidence=0.5, source=BeliefSource.LEARNING,
        )
        b2 = create_belief(
            entity="java", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Java",
            confidence=0.5, source=BeliefSource.LEARNING,
        )
        store.add(b1)
        store.add(b2)

        assert find_exact_duplicates(store) == []

    def test_merge_duplicate_pair(self, tmp_path):
        from agent_core.world_model.belief_maintenance import merge_duplicate_pair
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        b1 = create_belief(
            entity="python", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Python",
            confidence=0.8, source=BeliefSource.LEARNING,
            tags=["programowanie"],
            evidence=[("learning", "topic:python", 0.8)],
        )
        b2 = create_belief(
            entity="python", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Python",
            confidence=0.5, source=BeliefSource.EXAM,
            tags=["jezyk"],
            evidence=[("exam", "exam:file1", 0.7)],
        )
        store.add(b1)
        store.add(b2)

        result = merge_duplicate_pair(store, b1.belief_id, b2.belief_id)
        assert result is True

        current = store.get_current()
        assert len(current) == 1
        merged = current[0]
        assert merged.confidence == 0.8  # max
        assert "programowanie" in merged.tags
        assert "jezyk" in merged.tags
        assert len(merged.evidence) == 2
        assert merged.revision == 2

    def test_deduplicate_full_pass(self, tmp_path):
        from agent_core.world_model.belief_maintenance import deduplicate
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        # 3 beliefs, 2 are duplicates
        for i in range(2):
            b = create_belief(
                entity="fizyka", entity_type=EntityType.TOPIC,
                belief_type=BeliefType.OBSERVATION, content="Fizyka kwantowa",
                confidence=0.3 + i * 0.2,
                source=BeliefSource.LEARNING,
            )
            store.add(b)
        b_unique = create_belief(
            entity="chemia", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="Chemia organiczna",
            confidence=0.5, source=BeliefSource.LEARNING,
        )
        store.add(b_unique)

        merged = deduplicate(store)
        assert merged == 1
        current = store.get_current()
        assert len(current) == 2  # 1 merged fizyka + 1 chemia

    def test_deduplicate_without_semantic_memory(self, tmp_path):
        from agent_core.world_model.belief_maintenance import deduplicate
        store = BeliefStore(tmp_path / "beliefs.jsonl")
        b = create_belief(
            entity="solo", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="solo",
            confidence=0.5, source=BeliefSource.SYSTEM,
        )
        store.add(b)
        merged = deduplicate(store, semantic_memory=None)
        assert merged == 0


# ============================================================
# Belief Store v2: Full Maintenance Cycle
# ============================================================


class TestMaintenance:
    def test_maintain_runs_all_steps(self, tmp_path):
        from agent_core.world_model.belief_maintenance import run_maintenance
        store = BeliefStore(tmp_path / "beliefs.jsonl")

        # Add some beliefs
        for i in range(3):
            b = create_belief(
                entity=f"topic_{i}", entity_type=EntityType.TOPIC,
                belief_type=BeliefType.OBSERVATION, content=f"topic {i}",
                confidence=0.5, source=BeliefSource.SYSTEM,
            )
            store.add(b)
        store.save()

        results = run_maintenance(store)
        assert "decayed" in results
        assert "deduped" in results
        assert "pruned" in results
        assert "compacted" in results

    def test_world_model_maintain_facade(self, tmp_path):
        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "ki.jsonl",
            longterm_memory_path=tmp_path / "ltm.jsonl",
            exam_results_path=tmp_path / "exams.jsonl",
        )
        # Create source files
        (tmp_path / "ki.jsonl").touch()
        (tmp_path / "ltm.jsonl").touch()
        (tmp_path / "exams.jsonl").touch()

        b = create_belief(
            entity="test", entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION, content="test",
            confidence=0.5, source=BeliefSource.SYSTEM,
        )
        wm.store.add(b)
        wm.save()

        results = wm.maintain()
        assert isinstance(results, dict)
        assert "decayed" in results

    def test_world_model_compact_facade(self, tmp_path):
        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "ki.jsonl",
            longterm_memory_path=tmp_path / "ltm.jsonl",
            exam_results_path=tmp_path / "exams.jsonl",
        )
        (tmp_path / "ki.jsonl").touch()
        (tmp_path / "ltm.jsonl").touch()
        (tmp_path / "exams.jsonl").touch()

        removed = wm.compact()
        assert removed == 0  # Empty store

    def test_world_model_apply_decay_facade(self, tmp_path):
        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "ki.jsonl",
            longterm_memory_path=tmp_path / "ltm.jsonl",
            exam_results_path=tmp_path / "exams.jsonl",
        )
        (tmp_path / "ki.jsonl").touch()
        (tmp_path / "ltm.jsonl").touch()
        (tmp_path / "exams.jsonl").touch()

        revised = wm.apply_decay()
        assert revised == 0  # Empty store
