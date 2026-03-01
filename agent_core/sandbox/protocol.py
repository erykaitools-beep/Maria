"""
Sandbox Protocol - dataclasses for sandbox sessions.

Kontrakt: docs/CONTRACTS.md - Kontrakt 2: Sandbox / Production Boundary
ADR-010: Sandbox-first learning
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List


class SandboxStatus(Enum):
    """Status sesji sandbox."""
    ACTIVE = "active"              # Sandbox aktywny, trwa nauka
    READY_TO_PROMOTE = "ready"     # Kryteria spelnione, czeka na promote
    PROMOTED = "promoted"          # Zawartosc przeniesiona do produkcji
    DISCARDED = "discarded"        # Zawartosc odrzucona


# Prog zdania egzaminu (=EXAM_PASS_THRESHOLD z config.py)
PROMOTE_SCORE_THRESHOLD = 0.6


@dataclass
class SandboxSession:
    """
    Jedna izolowana sesja nauki.

    Sandbox dir: meta_data/sandbox/sess_<session_id>/
    Zawiera lustrzane kopie JSONL (knowledge_index, longterm_memory, exam_results).
    """
    session_id: str
    created_at: float
    status: SandboxStatus

    # Sciezki
    sandbox_dir: Path
    sandbox_index: Path       # sandbox_dir / "knowledge_index.jsonl"
    sandbox_memory: Path      # sandbox_dir / "maria_longterm_memory.jsonl"
    sandbox_exams: Path       # sandbox_dir / "exam_results.jsonl"

    # Metryki (aktualizowane po kazdej operacji)
    files_learned: int = 0
    chunks_learned: int = 0
    exams_passed: int = 0
    exams_total: int = 0
    avg_score: float = 0.0
    validation_errors: List[str] = field(default_factory=list)

    def meets_promote_criteria(self) -> bool:
        """
        Sprawdz czy sandbox jest gotowy do promocji.

        Warunki (wszystkie musza byc spelnione):
        1. chunks_learned > 0
        2. exams_total > 0
        3. avg_score >= PROMOTE_SCORE_THRESHOLD (0.6)
        4. Brak validation_errors
        """
        return (
            len(self.validation_errors) == 0
            and self.chunks_learned > 0
            and self.exams_total > 0
            and self.avg_score >= PROMOTE_SCORE_THRESHOLD
        )

    def to_dict(self) -> dict:
        """Serializacja do dict (dla promote_log.jsonl)."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "status": self.status.value,
            "sandbox_dir": str(self.sandbox_dir),
            "files_learned": self.files_learned,
            "chunks_learned": self.chunks_learned,
            "exams_passed": self.exams_passed,
            "exams_total": self.exams_total,
            "avg_score": self.avg_score,
            "validation_errors": self.validation_errors,
        }


@dataclass
class PromoteResult:
    """Wynik operacji promote()."""
    success: bool
    files_promoted: int = 0
    chunks_promoted: int = 0
    errors: List[str] = field(default_factory=list)
