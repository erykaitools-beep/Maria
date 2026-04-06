"""
CodeSession - tracks the full lifecycle of one coding task.

Persisted to JSONL so sessions survive restarts and can resume
when LLM budget refreshes.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.code_agent.models import (
    ApprovalCheckpoint,
    GeneratedFile,
    PlannedFile,
    TestResult,
    WrittenFile,
)

logger = logging.getLogger(__name__)


class CodeSessionStatus(Enum):
    """Status of a coding session."""
    PLANNING = "planning"
    GENERATING = "generating"
    WRITING = "writing"
    TESTING = "testing"
    FIXING = "fixing"
    WAITING_BUDGET = "waiting_budget"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            CodeSessionStatus.COMPLETED,
            CodeSessionStatus.FAILED,
            CodeSessionStatus.CANCELLED,
        )

    @property
    def is_resumable(self) -> bool:
        return self in (
            CodeSessionStatus.WAITING_BUDGET,
            CodeSessionStatus.AWAITING_APPROVAL,
        )


@dataclass
class CodeSession:
    """Tracks the full lifecycle of one coding task.

    Designed to be serializable to JSONL and resumable after restart.
    """
    session_id: str = field(default_factory=lambda: f"cs-{uuid.uuid4().hex[:12]}")
    task_description: str = ""
    status: CodeSessionStatus = CodeSessionStatus.PLANNING
    target_dir: str = ""

    # Pipeline state
    architecture_context: str = ""
    files_planned: List[PlannedFile] = field(default_factory=list)
    files_generated: List[GeneratedFile] = field(default_factory=list)
    files_written: List[WrittenFile] = field(default_factory=list)
    test_results: List[TestResult] = field(default_factory=list)
    approval_checkpoints: List[ApprovalCheckpoint] = field(default_factory=list)

    # Progress tracking
    current_step: str = "plan"         # plan/generate/write/test/fix/review
    current_file_index: int = 0        # Which file we're generating/writing
    iterations: int = 0                # Fix cycle count
    max_iterations: int = 3

    # Budget tracking
    llm_calls_used: Dict[str, int] = field(default_factory=lambda: {"claude": 0, "codex": 0})

    # Timestamps
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    # Result
    result_summary: str = ""

    def update_status(self, status: CodeSessionStatus) -> None:
        """Update status with timestamp."""
        self.status = status
        self.updated_at = time.time()
        if status.is_terminal:
            self.completed_at = time.time()

    def record_llm_call(self, source: str) -> None:
        """Track LLM usage."""
        self.llm_calls_used[source] = self.llm_calls_used.get(source, 0) + 1
        self.updated_at = time.time()

    def add_test_result(self, result: TestResult) -> None:
        """Add test result."""
        self.test_results.append(result)
        self.updated_at = time.time()

    def add_approval(self, checkpoint: ApprovalCheckpoint) -> None:
        """Add approval checkpoint."""
        self.approval_checkpoints.append(checkpoint)
        self.updated_at = time.time()

    @property
    def total_llm_calls(self) -> int:
        return sum(self.llm_calls_used.values())

    @property
    def last_test_result(self) -> Optional[TestResult]:
        return self.test_results[-1] if self.test_results else None

    @property
    def duration_s(self) -> float:
        end = self.completed_at or time.time()
        return end - self.created_at

    def describe(self) -> str:
        """Human-readable session summary in Polish."""
        status_pl = {
            "planning": "planowanie",
            "generating": "generowanie kodu",
            "writing": "zapis plikow",
            "testing": "testowanie",
            "fixing": "naprawianie bledow",
            "waiting_budget": "czekam na odnowienie limitow",
            "awaiting_approval": "czekam na zatwierdzenie",
            "completed": "zakonczone",
            "failed": "nieudane",
            "cancelled": "anulowane",
        }.get(self.status.value, self.status.value)

        lines = [
            f"Sesja: {self.session_id}",
            f"Zadanie: {self.task_description}",
            f"Status: {status_pl}",
            f"Pliki: {len(self.files_planned)} zaplanowanych, "
            f"{len(self.files_generated)} wygenerowanych, "
            f"{len(self.files_written)} zapisanych",
        ]
        if self.test_results:
            last = self.last_test_result
            lines.append(f"Testy: {last.passed} passed, {last.failed} failed (run #{last.run_number})")
        if self.iterations > 0:
            lines.append(f"Iteracje fix: {self.iterations}/{self.max_iterations}")
        lines.append(f"LLM calls: Claude {self.llm_calls_used.get('claude', 0)}, "
                      f"Codex {self.llm_calls_used.get('codex', 0)}")
        if self.result_summary:
            lines.append(f"Wynik: {self.result_summary}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSONL persistence."""
        return {
            "session_id": self.session_id,
            "task_description": self.task_description,
            "status": self.status.value,
            "target_dir": self.target_dir,
            "current_step": self.current_step,
            "current_file_index": self.current_file_index,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "llm_calls_used": self.llm_calls_used,
            "files_planned": [f.to_dict() for f in self.files_planned],
            "files_generated": [f.to_dict() for f in self.files_generated],
            "files_written": [f.to_dict() for f in self.files_written],
            "test_results": [t.to_dict() for t in self.test_results],
            "approval_checkpoints": [a.to_dict() for a in self.approval_checkpoints],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeSession":
        """Restore from JSONL record."""
        session = cls(
            session_id=data["session_id"],
            task_description=data.get("task_description", ""),
            status=CodeSessionStatus(data.get("status", "planning")),
            target_dir=data.get("target_dir", ""),
            current_step=data.get("current_step", "plan"),
            current_file_index=data.get("current_file_index", 0),
            iterations=data.get("iterations", 0),
            max_iterations=data.get("max_iterations", 3),
            llm_calls_used=data.get("llm_calls_used", {"claude": 0, "codex": 0}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            completed_at=data.get("completed_at"),
            result_summary=data.get("result_summary", ""),
        )
        # Restore planned files
        for fd in data.get("files_planned", []):
            session.files_planned.append(PlannedFile(
                path=fd["path"],
                purpose=fd.get("purpose", ""),
                complexity=fd.get("complexity", "medium"),
                dependencies=tuple(fd.get("dependencies", [])),
                is_test=fd.get("is_test", False),
            ))
        # Restore approval checkpoints
        for ad in data.get("approval_checkpoints", []):
            session.approval_checkpoints.append(ApprovalCheckpoint(
                name=ad["name"],
                request_id=ad.get("request_id", ""),
                status=ad.get("status", "pending"),
                timestamp=ad.get("timestamp", 0),
            ))
        return session


class CodeSessionStore:
    """JSONL persistence for code sessions.

    Follows BeliefStore pattern: append-only JSONL with in-memory cache.
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path or os.path.join("meta_data", "code_sessions.jsonl")
        self._sessions: Dict[str, CodeSession] = {}
        self._load()

    def _load(self) -> None:
        """Load sessions from JSONL."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        session = CodeSession.from_dict(data)
                        self._sessions[session.session_id] = session
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.debug(f"Skipping malformed session record: {e}")
        except Exception as e:
            logger.warning(f"Could not load code sessions: {e}")

    def save(self, session: CodeSession) -> None:
        """Save/update a session (append to JSONL)."""
        self._sessions[session.session_id] = session
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(session.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Could not save code session: {e}")

    def get(self, session_id: str) -> Optional[CodeSession]:
        """Get session by ID (prefix match supported)."""
        if session_id in self._sessions:
            return self._sessions[session_id]
        # Prefix match
        matches = [s for sid, s in self._sessions.items() if sid.startswith(session_id)]
        return matches[0] if len(matches) == 1 else None

    def get_active(self) -> Optional[CodeSession]:
        """Get the currently active (non-terminal) session."""
        for session in reversed(list(self._sessions.values())):
            if not session.status.is_terminal:
                return session
        return None

    def get_resumable(self) -> Optional[CodeSession]:
        """Get a session that can be resumed (WAITING_BUDGET or AWAITING_APPROVAL)."""
        for session in reversed(list(self._sessions.values())):
            if session.status.is_resumable:
                return session
        return None

    def list_recent(self, limit: int = 10) -> List[CodeSession]:
        """List recent sessions, newest first."""
        sessions = sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)
        return sessions[:limit]

    def compact(self) -> None:
        """Rewrite JSONL with only latest state per session."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                for session in self._sessions.values():
                    f.write(json.dumps(session.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Could not compact code sessions: {e}")
