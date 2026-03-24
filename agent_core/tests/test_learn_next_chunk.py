"""
Tests for learn_next_chunk: target_file_id selection + chunk failure backoff.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def learning_env(tmp_path):
    """Setup minimal learning environment."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    index_path = tmp_path / "knowledge_index.jsonl"
    memory_path = tmp_path / "longterm_memory.jsonl"

    # Create two input files
    (input_dir / "file_a.txt").write_text("Ala ma kota. Kot ma Ale.")
    (input_dir / "file_b.txt").write_text("Pies lubi spacery. Spacery sa zdrowe.")

    # Index: file_a higher priority, file_b lower
    records = [
        {"id": "file_a.txt", "folder": "root", "file": "file_a.txt",
         "status": "new", "priority": 90, "chunks_learned": 0, "total_chunks": 0},
        {"id": "file_b.txt", "folder": "root", "file": "file_b.txt",
         "status": "new", "priority": 50, "chunks_learned": 0, "total_chunks": 0},
    ]
    with open(index_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    return {
        "input_dir": input_dir,
        "index_path": index_path,
        "memory_path": memory_path,
    }


def _fake_llm(prompt):
    """Fake LLM that returns valid learning JSON."""
    return json.dumps({
        "summary": "Test summary",
        "key_points": ["point 1"],
        "tags": ["test"],
        "questions": [{"q": "Q?", "a": "A."}],
    })


def _failing_llm(prompt):
    """Fake LLM that returns garbage (simulates parse failure)."""
    return "I cannot process this request properly."


class TestTargetFileId:
    """Tests for target_file_id parameter."""

    def test_without_target_picks_highest_priority(self, learning_env):
        """Without target_file_id, picks file_a (priority 90)."""
        from maria_core.learning.learning_agent import learn_next_chunk

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
        )
        assert result is True

        # Check that file_a was learned (higher priority)
        with open(learning_env["memory_path"]) as f:
            mem = json.loads(f.readline())
        assert "file_a.txt" in mem["source_file"]

    def test_with_target_overrides_priority(self, learning_env):
        """With target_file_id=file_b, learns file_b despite lower priority."""
        from maria_core.learning.learning_agent import learn_next_chunk

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
            target_file_id="file_b.txt",
        )
        assert result is True

        with open(learning_env["memory_path"]) as f:
            mem = json.loads(f.readline())
        assert "file_b.txt" in mem["source_file"]

    def test_with_invalid_target_falls_back(self, learning_env):
        """With invalid target_file_id, falls back to priority selection."""
        from maria_core.learning.learning_agent import learn_next_chunk

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
            target_file_id="nonexistent.txt",
        )
        assert result is True

        with open(learning_env["memory_path"]) as f:
            mem = json.loads(f.readline())
        assert "file_a.txt" in mem["source_file"]

    def test_target_must_be_in_candidates(self, learning_env):
        """target_file_id only works for files with learnable status."""
        from maria_core.learning.learning_agent import learn_next_chunk

        # Mark file_b as completed (not a candidate)
        with open(learning_env["index_path"]) as f:
            lines = f.readlines()
        records = [json.loads(l) for l in lines]
        for r in records:
            if r["id"] == "file_b.txt":
                r["status"] = "completed"
        with open(learning_env["index_path"], "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
            target_file_id="file_b.txt",
        )
        assert result is True

        # Falls back to file_a
        with open(learning_env["memory_path"]) as f:
            mem = json.loads(f.readline())
        assert "file_a.txt" in mem["source_file"]


class TestChunkBackoff:
    """Tests for chunk failure backoff."""

    def test_failure_increments_counter(self, learning_env):
        """Each failed learn attempt increments chunk_failures."""
        from maria_core.learning.learning_agent import learn_next_chunk

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_failing_llm,
        )
        assert result is False

        with open(learning_env["index_path"]) as f:
            rec = json.loads(f.readline())
        failures = rec.get("chunk_failures", {})
        assert len(failures) == 1
        assert list(failures.values())[0] == 1

    def test_skip_after_max_retries(self, learning_env):
        """After 5 failures, chunk is skipped with marker record."""
        from maria_core.learning.learning_agent import learn_next_chunk

        # Pre-set failure counter to 5
        with open(learning_env["index_path"]) as f:
            lines = f.readlines()
        records = [json.loads(l) for l in lines]
        records[0]["chunk_failures"] = {"file_a.txt#chunk_0": 5}
        with open(learning_env["index_path"], "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_failing_llm,  # Won't even be called
        )
        assert result is True  # Skipped = success (unblocks pipeline)

        # Memory has skip marker
        with open(learning_env["memory_path"]) as f:
            mem = json.loads(f.readline())
        assert "[SKIPPED]" in mem["summary"]
        assert "hard_chunk" in mem["tags"]

    def test_skip_clears_failure_counter(self, learning_env):
        """After skipping, failure counter for that chunk is cleared."""
        from maria_core.learning.learning_agent import learn_next_chunk

        with open(learning_env["index_path"]) as f:
            lines = f.readlines()
        records = [json.loads(l) for l in lines]
        records[0]["chunk_failures"] = {"file_a.txt#chunk_0": 5}
        with open(learning_env["index_path"], "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_failing_llm,
        )

        with open(learning_env["index_path"]) as f:
            rec = json.loads(f.readline())
        failures = rec.get("chunk_failures", {})
        assert "file_a.txt#chunk_0" not in failures

    def test_multiple_failures_accumulate(self, learning_env):
        """Multiple failures accumulate until threshold."""
        from maria_core.learning.learning_agent import learn_next_chunk

        for i in range(3):
            learn_next_chunk(
                base_dir=learning_env["input_dir"],
                index_path=learning_env["index_path"],
                memory_path=learning_env["memory_path"],
                llm_fn=_failing_llm,
            )

        with open(learning_env["index_path"]) as f:
            rec = json.loads(f.readline())
        failures = rec.get("chunk_failures", {})
        assert list(failures.values())[0] == 3
