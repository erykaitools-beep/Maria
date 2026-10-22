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
        assert result.learned is True

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
        assert result.learned is True

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
        assert result.learned is True

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
        assert result.learned is True

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
        assert result.learned is False

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
        # A backoff skip advances the file (it writes the marker record below)
        # but nothing was learned -- no LLM call happened. Reporting it as a
        # learn success is the same conflation that let no-op learns inflate the
        # action success rate by 22% on 2026-07-16. It must not read as a
        # failure either: the self-repair failure-storm detector counts
        # `success is False and not skipped`.
        assert result.learned is False
        assert result.skipped is True
        assert result.reason == "chunk_backoff"

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


def _simple_llm(prompt):
    """Fake LLM returning the PROMPT_LEARN_SIMPLE output schema."""
    return json.dumps({
        "summary_simple": "Prosto: kot nalezy do Ali.",
        "core_ideas": ["kot", "Ala", "posiadanie"],
        "tags": ["prosto", "test"],
    })


def _index_records(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_index(path, records):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _set_status(path, file_id, status):
    records = _index_records(path)
    for r in records:
        if r["id"] == file_id:
            r["status"] = status
    _write_index(path, records)


class TestNothingToLearnIsSkipNotSuccess:
    """A file with no unlearned chunks did no work -- say so.

    learn_next_chunk used to return True here. Once such files reached the head
    of the priority queue (36 of 73 candidates on 2026-08-16, the top three by
    priority among them), the planner ran `learn` every minute, was told it
    succeeded every time, and learned nothing: K12 logged "Learning velocity
    flat at 0.0 across 10 periods while 'learn' actions report 100".
    """

    def test_second_pass_reports_skip(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = dict(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
        )
        first = learn_next_chunk(llm_fn=_fake_llm, **kwargs)
        assert first.learned is True

        second = learn_next_chunk(target_file_id="file_a.txt", llm_fn=_fake_llm, **kwargs)
        assert second.learned is False
        assert second.skipped is True
        assert second.reason == "nothing_to_learn"

    def test_skip_does_not_read_as_failure(self, learning_env):
        """The self-repair storm detector counts `success is False and not skipped`."""
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = dict(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
        )
        learn_next_chunk(llm_fn=_fake_llm, **kwargs)
        result = learn_next_chunk(target_file_id="file_a.txt", llm_fn=_fake_llm, **kwargs)
        assert not (result.learned is False and not result.skipped)

    def test_no_candidates_is_also_a_skip(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        for file_id in ("file_a.txt", "file_b.txt"):
            _set_status(learning_env["index_path"], file_id, "completed")

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
        )
        assert result.learned is False
        assert result.skipped is True
        assert result.reason == "no_candidates"


class TestExamFailedRecoveryPass:
    """exam_failed must re-teach with the simple prompt, not report 'done'.

    PROMPT_LEARN_SIMPLE exists for exactly this ("wyjasnij jak dziecku"), gated
    on `use_simple = status == STATUS_EXAM_FAILED`. It was unreachable: the
    chunk selector skipped every chunk already in memory, and after a failed
    exam they all are. 4 learned_simple records in 9952 across the project.
    """

    def _learn_then_fail_exam(self, env):
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = dict(
            base_dir=env["input_dir"],
            index_path=env["index_path"],
            memory_path=env["memory_path"],
        )
        assert learn_next_chunk(llm_fn=_fake_llm, **kwargs).learned is True
        _set_status(env["index_path"], "file_a.txt", "exam_failed")
        return kwargs

    def test_recovery_pass_actually_relearns(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = self._learn_then_fail_exam(learning_env)
        result = learn_next_chunk(target_file_id="file_a.txt", llm_fn=_simple_llm, **kwargs)

        assert result.learned is True, "recovery pass must re-teach, not report done"
        assert result.reason == "simple"

    def test_recovery_pass_uses_the_simple_prompt(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = self._learn_then_fail_exam(learning_env)
        seen = {}

        def capturing_llm(prompt):
            seen["prompt"] = prompt
            return _simple_llm(prompt)

        learn_next_chunk(target_file_id="file_a.txt", llm_fn=capturing_llm, **kwargs)
        assert "dziecku" in seen["prompt"], "must be PROMPT_LEARN_SIMPLE"

    def test_recovery_record_is_marked_simple(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = self._learn_then_fail_exam(learning_env)
        learn_next_chunk(target_file_id="file_a.txt", llm_fn=_simple_llm, **kwargs)

        records = _index_records(learning_env["memory_path"])
        assert records[-1]["learned_simple"] is True
        assert records[-1]["chunk_id"] == "file_a.txt#chunk_0"

    def test_recovery_pass_terminates(self, learning_env):
        """Once every chunk has a simple record, it is genuinely done."""
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = self._learn_then_fail_exam(learning_env)
        learn_next_chunk(target_file_id="file_a.txt", llm_fn=_simple_llm, **kwargs)
        _set_status(learning_env["index_path"], "file_a.txt", "exam_failed")

        again = learn_next_chunk(target_file_id="file_a.txt", llm_fn=_simple_llm, **kwargs)
        assert again.learned is False
        assert again.skipped is True
        assert again.reason == "nothing_to_learn"

    def test_progress_counter_does_not_regress(self, learning_env):
        """chunks_learned counts the union, not the recovery pass alone."""
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = self._learn_then_fail_exam(learning_env)
        before = [r for r in _index_records(learning_env["index_path"])
                  if r["id"] == "file_a.txt"][0]["chunks_learned"]
        learn_next_chunk(target_file_id="file_a.txt", llm_fn=_simple_llm, **kwargs)
        after = [r for r in _index_records(learning_env["index_path"])
                 if r["id"] == "file_a.txt"][0]["chunks_learned"]
        assert after >= before

    def test_normal_pass_unaffected(self, learning_env):
        """A non-exam_failed file must still skip chunks already in memory."""
        from maria_core.learning.learning_agent import learn_next_chunk

        kwargs = dict(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
        )
        learn_next_chunk(llm_fn=_fake_llm, **kwargs)
        result = learn_next_chunk(target_file_id="file_a.txt", llm_fn=_fake_llm, **kwargs)
        assert result.skipped is True


class TestRequestedFileIsNotAlwaysTheProcessedFile:
    """A caller that names a file must be told which file was actually touched.

    When the named file is not learnable, selection falls back to priority and a
    DIFFERENT file gets learned. The exam path carried the same bug until
    2026-08-12, where crediting a score to strategy.target benched a healthy file
    and left the broken one eligible.
    """

    def test_fallback_reports_the_file_it_really_learned(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        _set_status(learning_env["index_path"], "file_b.txt", "completed")
        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
            target_file_id="file_b.txt",   # not learnable -> falls back
        )
        assert result.learned is True
        assert result.file_id == "file_a.txt", "must name the file actually learned"

    def test_direct_hit_reports_that_file(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
            target_file_id="file_b.txt",
        )
        assert result.file_id == "file_b.txt"


class TestExplicitSimpleOverride:
    """The teacher's retry_hard_topic intent must reach the prompt selector."""

    def test_hard_topic_is_reachable_when_named(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        _set_status(learning_env["index_path"], "file_b.txt", "hard_topic")
        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_simple_llm,
            target_file_id="file_b.txt",
            use_simple=True,
        )
        assert result.file_id == "file_b.txt", "named hard_topic must be reachable"
        assert result.learned is True
        assert result.reason == "simple"

    def test_hard_topic_stays_out_of_the_autonomous_pool(self, learning_env):
        """Reachable when NAMED must not mean reachable by the priority loop."""
        from maria_core.learning.learning_agent import learn_next_chunk

        _set_status(learning_env["index_path"], "file_a.txt", "hard_topic")
        result = learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=_fake_llm,
        )
        assert result.file_id == "file_b.txt", "hard_topic must not be auto-selected"

    def test_override_forces_the_simple_prompt(self, learning_env):
        from maria_core.learning.learning_agent import learn_next_chunk

        seen = {}

        def capturing(prompt):
            seen["prompt"] = prompt
            return _simple_llm(prompt)

        learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=capturing,
            target_file_id="file_a.txt",
            use_simple=True,
        )
        assert "dziecku" in seen["prompt"]

    def test_none_still_derives_from_status(self, learning_env):
        """Default must stay 'derive from status' -- the autonomous loop relies on it."""
        from maria_core.learning.learning_agent import learn_next_chunk

        seen = {}

        def capturing(prompt):
            seen["prompt"] = prompt
            return _fake_llm(prompt)

        learn_next_chunk(
            base_dir=learning_env["input_dir"],
            index_path=learning_env["index_path"],
            memory_path=learning_env["memory_path"],
            llm_fn=capturing,
            target_file_id="file_a.txt",
        )
        assert "dziecku" not in seen["prompt"]
