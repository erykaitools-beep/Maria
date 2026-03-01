"""
Tests for Sandbox / Production Boundary.

Contract reference: docs/CONTRACTS.md - Kontrakt 2
ADR-010: Sandbox-first learning
"""

import json
import time
from pathlib import Path

import pytest

from agent_core.sandbox.protocol import (
    SandboxStatus,
    SandboxSession,
    PromoteResult,
    PROMOTE_SCORE_THRESHOLD,
)
from agent_core.sandbox.manager import SandboxManager, SANDBOX_TIMEOUT_SEC


@pytest.fixture
def sandbox_env(tmp_path):
    """Create a sandbox environment with temporary paths."""
    sandbox_base = tmp_path / "sandbox"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    prod_index = memory_dir / "knowledge_index.jsonl"
    prod_memory = memory_dir / "maria_longterm_memory.jsonl"
    prod_exams = memory_dir / "exam_results.jsonl"

    # Create empty production files
    prod_index.touch()
    prod_memory.touch()
    prod_exams.touch()

    manager = SandboxManager(
        sandbox_base_dir=sandbox_base,
        production_index=prod_index,
        production_memory=prod_memory,
        production_exams=prod_exams,
    )
    return manager, sandbox_base, memory_dir


@pytest.fixture
def manager_with_session(sandbox_env):
    """Create manager with an active session."""
    manager, _, _ = sandbox_env
    session = manager.create_session()
    return manager, session


def _write_jsonl(path: Path, records: list):
    """Helper: write records to JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list:
    """Helper: read records from JSONL file."""
    records = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


# --- Protocol Tests ---

class TestSandboxStatus:
    """Tests for SandboxStatus enum."""

    def test_all_statuses(self):
        assert SandboxStatus.ACTIVE.value == "active"
        assert SandboxStatus.READY_TO_PROMOTE.value == "ready"
        assert SandboxStatus.PROMOTED.value == "promoted"
        assert SandboxStatus.DISCARDED.value == "discarded"

    def test_status_count(self):
        assert len(SandboxStatus) == 4


class TestSandboxSession:
    """Tests for SandboxSession dataclass."""

    def _make_session(self, **kwargs):
        defaults = {
            "session_id": "test-123",
            "created_at": time.time(),
            "status": SandboxStatus.ACTIVE,
            "sandbox_dir": Path("/tmp/sandbox/sess_test"),
            "sandbox_index": Path("/tmp/sandbox/sess_test/knowledge_index.jsonl"),
            "sandbox_memory": Path("/tmp/sandbox/sess_test/maria_longterm_memory.jsonl"),
            "sandbox_exams": Path("/tmp/sandbox/sess_test/exam_results.jsonl"),
        }
        defaults.update(kwargs)
        return SandboxSession(**defaults)

    def test_meets_criteria_all_ok(self):
        """Promote criteria met when all conditions satisfied."""
        session = self._make_session(
            chunks_learned=3,
            exams_total=1,
            exams_passed=1,
            avg_score=0.85,
        )
        assert session.meets_promote_criteria() is True

    def test_criteria_no_chunks(self):
        """Criteria fail: no chunks learned."""
        session = self._make_session(
            chunks_learned=0,
            exams_total=1,
            avg_score=0.9,
        )
        assert session.meets_promote_criteria() is False

    def test_criteria_no_exams(self):
        """Criteria fail: no exams taken."""
        session = self._make_session(
            chunks_learned=3,
            exams_total=0,
            avg_score=0.0,
        )
        assert session.meets_promote_criteria() is False

    def test_criteria_low_score(self):
        """Criteria fail: score below threshold."""
        session = self._make_session(
            chunks_learned=3,
            exams_total=2,
            avg_score=0.5,
        )
        assert session.meets_promote_criteria() is False

    def test_criteria_score_at_threshold(self):
        """Criteria pass: score exactly at threshold."""
        session = self._make_session(
            chunks_learned=1,
            exams_total=1,
            avg_score=PROMOTE_SCORE_THRESHOLD,
        )
        assert session.meets_promote_criteria() is True

    def test_criteria_validation_errors(self):
        """Criteria fail: validation errors exist."""
        session = self._make_session(
            chunks_learned=3,
            exams_total=1,
            avg_score=0.9,
            validation_errors=["bad line in JSONL"],
        )
        assert session.meets_promote_criteria() is False

    def test_to_dict(self):
        """Serialization to dict."""
        session = self._make_session()
        d = session.to_dict()
        assert d["session_id"] == "test-123"
        assert d["status"] == "active"


class TestPromoteResult:
    """Tests for PromoteResult dataclass."""

    def test_success_result(self):
        result = PromoteResult(success=True, files_promoted=2, chunks_promoted=5)
        assert result.success is True
        assert result.errors == []

    def test_failure_result(self):
        result = PromoteResult(success=False, errors=["Score too low"])
        assert result.success is False
        assert len(result.errors) == 1


# --- Manager Tests ---

class TestSandboxManagerCreate:
    """Tests for session creation."""

    def test_create_session(self, sandbox_env):
        manager, sandbox_base, _ = sandbox_env

        session = manager.create_session()
        assert session.status == SandboxStatus.ACTIVE
        assert session.sandbox_dir.exists()
        assert session.sandbox_index.exists()
        assert session.sandbox_memory.exists()
        assert session.sandbox_exams.exists()
        assert session.chunks_learned == 0
        assert session.exams_total == 0

    def test_create_sets_active_session(self, sandbox_env):
        manager, _, _ = sandbox_env
        assert not manager.has_active_session()

        session = manager.create_session()
        assert manager.has_active_session()
        assert manager.active_session is session

    def test_create_second_session_fails(self, sandbox_env):
        manager, _, _ = sandbox_env
        manager.create_session()

        with pytest.raises(RuntimeError, match="Active sandbox session already exists"):
            manager.create_session()

    def test_session_id_format(self, sandbox_env):
        manager, _, _ = sandbox_env
        session = manager.create_session()
        assert len(session.session_id) == 12  # UUID4[:12]
        assert session.sandbox_dir.name.startswith("sess_")


class TestSandboxManagerSeed:
    """Tests for seeding from production."""

    def test_seed_all(self, sandbox_env):
        manager, _, memory_dir = sandbox_env
        prod_index = memory_dir / "knowledge_index.jsonl"

        # Create production index
        _write_jsonl(prod_index, [
            {"file_id": "physics.txt", "status": "completed", "updated_at": 100},
            {"file_id": "math.txt", "status": "in_progress", "updated_at": 200},
        ])

        session = manager.create_session()
        seeded = manager.seed_from_production()
        assert seeded == 2

        # Check sandbox index has records
        sandbox_records = _read_jsonl(session.sandbox_index)
        assert len(sandbox_records) == 2

    def test_seed_specific_files(self, sandbox_env):
        manager, _, memory_dir = sandbox_env
        prod_index = memory_dir / "knowledge_index.jsonl"

        _write_jsonl(prod_index, [
            {"file_id": "physics.txt", "status": "completed", "updated_at": 100},
            {"file_id": "math.txt", "status": "in_progress", "updated_at": 200},
            {"file_id": "bio.txt", "status": "new", "updated_at": 300},
        ])

        session = manager.create_session()
        seeded = manager.seed_from_production(file_ids=["math.txt"])
        assert seeded == 1

        sandbox_records = _read_jsonl(session.sandbox_index)
        assert len(sandbox_records) == 1
        assert sandbox_records[0]["file_id"] == "math.txt"

    def test_seed_empty_production(self, sandbox_env):
        manager, _, _ = sandbox_env
        manager.create_session()
        seeded = manager.seed_from_production()
        assert seeded == 0

    def test_seed_requires_active_session(self, sandbox_env):
        manager, _, _ = sandbox_env
        with pytest.raises(RuntimeError):
            manager.seed_from_production()


class TestSandboxManagerRecord:
    """Tests for recording learning/exam results."""

    def test_record_chunk(self, manager_with_session):
        manager, session = manager_with_session
        manager.record_chunk_learned("physics.txt")
        assert session.chunks_learned == 1

    def test_record_multiple_chunks(self, manager_with_session):
        manager, session = manager_with_session
        manager.record_chunk_learned("physics.txt")
        manager.record_chunk_learned("physics.txt")
        manager.record_chunk_learned("math.txt")
        assert session.chunks_learned == 3

    def test_record_exam_passed(self, manager_with_session):
        manager, session = manager_with_session
        manager.record_exam_result("physics.txt", score=0.85, passed=True)
        assert session.exams_total == 1
        assert session.exams_passed == 1
        assert session.avg_score == 0.85

    def test_record_exam_failed(self, manager_with_session):
        manager, session = manager_with_session
        manager.record_exam_result("physics.txt", score=0.4, passed=False)
        assert session.exams_total == 1
        assert session.exams_passed == 0
        assert session.avg_score == 0.4

    def test_avg_score_multiple_exams(self, manager_with_session):
        manager, session = manager_with_session
        manager.record_exam_result("f1.txt", score=0.8, passed=True)
        manager.record_exam_result("f2.txt", score=0.6, passed=True)
        assert session.exams_total == 2
        assert abs(session.avg_score - 0.7) < 0.001

    def test_auto_ready_to_promote(self, manager_with_session):
        manager, session = manager_with_session
        session.chunks_learned = 3
        manager.record_exam_result("f1.txt", score=0.8, passed=True)
        assert session.status == SandboxStatus.READY_TO_PROMOTE


class TestSandboxManagerPromote:
    """Tests for promote operation."""

    def _prepare_for_promote(self, manager, session):
        """Helper: fill sandbox with valid data for promotion."""
        # Write sandbox JSONL
        _write_jsonl(session.sandbox_index, [
            {"file_id": "physics.txt", "status": "completed", "updated_at": time.time()},
        ])
        _write_jsonl(session.sandbox_memory, [
            {"source_file": "physics.txt", "chunk": 0, "summary": "Fizyka kwantowa..."},
            {"source_file": "physics.txt", "chunk": 1, "summary": "Zasada Heisenberga..."},
        ])
        _write_jsonl(session.sandbox_exams, [
            {"file": "physics.txt", "score": 85, "passed": True},
        ])

        # Record metrics
        session.chunks_learned = 2
        session.exams_total = 1
        session.exams_passed = 1
        session.avg_score = 0.85

    def test_promote_success(self, sandbox_env):
        manager, sandbox_base, memory_dir = sandbox_env
        session = manager.create_session()
        self._prepare_for_promote(manager, session)

        result = manager.promote()
        assert result.success is True
        assert result.files_promoted >= 1
        assert result.chunks_promoted >= 2

        # Session cleared
        assert not manager.has_active_session()

        # Sandbox dir removed
        assert not session.sandbox_dir.exists()

        # Production files have data
        prod_memory = _read_jsonl(memory_dir / "maria_longterm_memory.jsonl")
        assert len(prod_memory) == 2

        prod_exams = _read_jsonl(memory_dir / "exam_results.jsonl")
        assert len(prod_exams) == 1

    def test_promote_writes_transaction_log(self, sandbox_env):
        manager, sandbox_base, _ = sandbox_env
        session = manager.create_session()
        self._prepare_for_promote(manager, session)

        manager.promote()

        log = _read_jsonl(sandbox_base / "promote_log.jsonl")
        assert len(log) == 2
        assert log[0]["marker"] == "START"
        assert log[1]["marker"] == "COMMIT"
        assert log[0]["session_id"] == session.session_id

    def test_promote_criteria_not_met(self, sandbox_env):
        manager, _, _ = sandbox_env
        session = manager.create_session()
        # No chunks, no exams -> criteria not met

        result = manager.promote()
        assert result.success is False
        assert len(result.errors) > 0

        # Session still active
        assert manager.has_active_session()

    def test_promote_bad_jsonl(self, sandbox_env):
        manager, _, _ = sandbox_env
        session = manager.create_session()
        session.chunks_learned = 2
        session.exams_total = 1
        session.exams_passed = 1
        session.avg_score = 0.85

        # Write invalid JSONL
        with open(session.sandbox_memory, "w") as f:
            f.write("not valid json\n")

        result = manager.promote()
        assert result.success is False

    def test_promote_merges_index(self, sandbox_env):
        manager, _, memory_dir = sandbox_env
        prod_index = memory_dir / "knowledge_index.jsonl"

        # Existing production record
        _write_jsonl(prod_index, [
            {"file_id": "old.txt", "status": "completed", "updated_at": 100},
            {"file_id": "physics.txt", "status": "in_progress", "updated_at": 100},
        ])

        session = manager.create_session()

        # Sandbox has newer version of physics.txt
        _write_jsonl(session.sandbox_index, [
            {"file_id": "physics.txt", "status": "completed", "updated_at": 999},
        ])
        _write_jsonl(session.sandbox_memory, [
            {"source_file": "physics.txt", "chunk": 0, "summary": "test"},
        ])
        _write_jsonl(session.sandbox_exams, [
            {"file": "physics.txt", "score": 90, "passed": True},
        ])
        session.chunks_learned = 1
        session.exams_total = 1
        session.exams_passed = 1
        session.avg_score = 0.9

        result = manager.promote()
        assert result.success is True

        # Check merged index
        merged = _read_jsonl(prod_index)
        assert len(merged) == 2  # old.txt + physics.txt
        physics = [r for r in merged if r["file_id"] == "physics.txt"][0]
        assert physics["status"] == "completed"
        assert physics["updated_at"] == 999  # Newer version wins


class TestSandboxManagerDiscard:
    """Tests for discard operation."""

    def test_discard(self, manager_with_session):
        manager, session = manager_with_session
        sandbox_dir = session.sandbox_dir

        result = manager.discard(reason="test")
        assert result is True
        assert not manager.has_active_session()
        assert not sandbox_dir.exists()

    def test_discard_no_session(self, sandbox_env):
        manager, _, _ = sandbox_env
        result = manager.discard()
        assert result is False


class TestSandboxManagerTimeout:
    """Tests for auto-timeout."""

    def test_timeout_old_session(self, manager_with_session):
        manager, session = manager_with_session

        # Make session 25h old
        session.created_at = time.time() - (25 * 3600)
        result = manager.check_timeout()
        assert result is True
        assert not manager.has_active_session()

    def test_timeout_fresh_session(self, manager_with_session):
        manager, session = manager_with_session
        result = manager.check_timeout()
        assert result is False
        assert manager.has_active_session()


class TestSandboxManagerStartupRecovery:
    """Tests for startup recovery."""

    def test_recovery_start_without_commit_sandbox_exists(self, sandbox_env):
        manager, sandbox_base, _ = sandbox_env

        # Simulate interrupted promote: START written, sandbox dir exists
        promote_log = sandbox_base / "promote_log.jsonl"
        _write_jsonl(promote_log, [
            {"ts": 100, "marker": "START", "session_id": "abc123", "files": 1, "chunks": 3},
        ])
        orphan_dir = sandbox_base / "sess_abc123"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "test.jsonl").touch()

        manager.startup_recovery()

        # Dir should be removed
        assert not orphan_dir.exists()

        # ROLLBACK marker added
        log = _read_jsonl(promote_log)
        assert log[-1]["marker"] == "ROLLBACK"
        assert log[-1]["reason"] == "startup_recovery"

    def test_recovery_start_without_commit_no_dir(self, sandbox_env):
        manager, sandbox_base, _ = sandbox_env

        # Simulate: START but sandbox dir already gone (partial append)
        promote_log = sandbox_base / "promote_log.jsonl"
        _write_jsonl(promote_log, [
            {"ts": 100, "marker": "START", "session_id": "xyz789", "files": 1, "chunks": 3},
        ])

        manager.startup_recovery()

        log = _read_jsonl(promote_log)
        assert log[-1]["marker"] == "ROLLBACK"
        assert log[-1]["reason"] == "startup_recovery"

    def test_recovery_normal_commit(self, sandbox_env):
        manager, sandbox_base, _ = sandbox_env

        # Normal: START + COMMIT (nothing to recover)
        promote_log = sandbox_base / "promote_log.jsonl"
        _write_jsonl(promote_log, [
            {"ts": 100, "marker": "START", "session_id": "ok123", "files": 1, "chunks": 3},
            {"ts": 101, "marker": "COMMIT", "session_id": "ok123", "result": "ok"},
        ])

        manager.startup_recovery()

        # No new entries
        log = _read_jsonl(promote_log)
        assert len(log) == 2

    def test_recovery_no_log(self, sandbox_env):
        manager, _, _ = sandbox_env
        # No promote log file - should not crash
        manager.startup_recovery()


class TestSandboxManagerCleanup:
    """Tests for stale directory cleanup."""

    def test_cleanup_stale_dirs(self, sandbox_env):
        manager, sandbox_base, _ = sandbox_env

        # Create orphan dirs
        (sandbox_base / "sess_orphan1").mkdir(parents=True)
        (sandbox_base / "sess_orphan2").mkdir(parents=True)

        removed = manager.cleanup_stale()
        assert removed == 2
        assert not (sandbox_base / "sess_orphan1").exists()

    def test_cleanup_preserves_active(self, sandbox_env):
        manager, sandbox_base, _ = sandbox_env

        session = manager.create_session()
        (sandbox_base / "sess_orphan").mkdir(parents=True)

        removed = manager.cleanup_stale()
        assert removed == 1
        assert session.sandbox_dir.exists()  # Active preserved


class TestSandboxManagerStatus:
    """Tests for get_status()."""

    def test_status_no_session(self, sandbox_env):
        manager, _, _ = sandbox_env
        status = manager.get_status()
        assert status["active"] is False

    def test_status_with_session(self, manager_with_session):
        manager, session = manager_with_session
        status = manager.get_status()
        assert status["active"] is True
        assert status["session_id"] == session.session_id
        assert status["status"] == "active"
        assert status["chunks_learned"] == 0


class TestSandboxEndToEnd:
    """End-to-end sandbox lifecycle tests."""

    def test_full_lifecycle(self, sandbox_env):
        """create -> seed -> learn -> exam -> promote."""
        manager, sandbox_base, memory_dir = sandbox_env
        prod_index = memory_dir / "knowledge_index.jsonl"

        # 1. Seed production
        _write_jsonl(prod_index, [
            {"file_id": "quantum.txt", "status": "in_progress",
             "chunks_done": 2, "chunks_total": 5, "updated_at": 100},
        ])

        # 2. Create sandbox
        session = manager.create_session()
        assert session.status == SandboxStatus.ACTIVE

        # 3. Seed from production
        seeded = manager.seed_from_production(file_ids=["quantum.txt"])
        assert seeded == 1

        # 4. Simulate learning (write to sandbox JSONL)
        _write_jsonl(session.sandbox_index, [
            {"file_id": "quantum.txt", "status": "completed",
             "chunks_done": 5, "chunks_total": 5, "updated_at": 999},
        ])
        _write_jsonl(session.sandbox_memory, [
            {"source_file": "quantum.txt", "chunk": 2, "summary": "Superposition"},
            {"source_file": "quantum.txt", "chunk": 3, "summary": "Entanglement"},
            {"source_file": "quantum.txt", "chunk": 4, "summary": "Measurement"},
        ])
        manager.record_chunk_learned("quantum.txt")
        manager.record_chunk_learned("quantum.txt")
        manager.record_chunk_learned("quantum.txt")

        # 5. Simulate exam
        _write_jsonl(session.sandbox_exams, [
            {"file": "quantum.txt", "score": 80, "passed": True},
        ])
        manager.record_exam_result("quantum.txt", score=0.8, passed=True)

        assert session.status == SandboxStatus.READY_TO_PROMOTE
        assert session.meets_promote_criteria()

        # 6. Promote
        result = manager.promote()
        assert result.success is True
        assert result.chunks_promoted == 3

        # 7. Verify production updated
        prod_records = _read_jsonl(prod_index)
        quantum = [r for r in prod_records if r["file_id"] == "quantum.txt"][0]
        assert quantum["status"] == "completed"
        assert quantum["updated_at"] == 999

        # 8. Verify transaction log
        log = _read_jsonl(sandbox_base / "promote_log.jsonl")
        assert log[0]["marker"] == "START"
        assert log[1]["marker"] == "COMMIT"

    def test_discard_lifecycle(self, sandbox_env):
        """create -> learn -> discard (score too low)."""
        manager, _, _ = sandbox_env
        session = manager.create_session()

        manager.record_chunk_learned("hard.txt")
        manager.record_exam_result("hard.txt", score=0.3, passed=False)

        # Can't promote
        assert not session.meets_promote_criteria()

        # Discard
        manager.discard(reason="score_too_low")
        assert not manager.has_active_session()
        assert not session.sandbox_dir.exists()
