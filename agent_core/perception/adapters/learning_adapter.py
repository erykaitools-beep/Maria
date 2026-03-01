"""
Learning Adapter - mapuje wyniki nauki na PerceptionEvent.

Obsluguje:
- chunk_learned - nauczony chunk
- file_scan_result - wynik skanowania plikow
- sandbox_promoted - sandbox przeniesiony do produkcji
- sandbox_discarded - sandbox odrzucony

Kontrakt: docs/CONTRACTS.md - Event Type Registry
"""

from typing import Optional

from agent_core.perception.event import (
    PerceptionEvent,
    PerceptionSource,
    create_event,
)


class LearningAdapter:
    """Konwertuje wyniki nauki na PerceptionEvent."""

    @staticmethod
    def from_chunk_learned(
        file_id: str,
        chunk_index: int,
        chunks_total: int,
        summary_preview: Optional[str] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Wynik learn_next_chunk() -> PerceptionEvent(chunk_learned).

        Args:
            file_id: Identyfikator pliku
            chunk_index: Indeks nauczonego chunka (0-based)
            chunks_total: Calkowita liczba chunkow w pliku
            summary_preview: opcjonalny podglad streszczenia
            parent_event_id: opcjonalny event_id przyczyny (np. teacher_decision)
        """
        payload = {
            "file_id": file_id,
            "chunk_index": chunk_index,
            "chunks_total": chunks_total,
        }
        if summary_preview is not None:
            payload["summary_preview"] = summary_preview

        return create_event(
            source=PerceptionSource.LEARNING,
            event_type="chunk_learned",
            payload=payload,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_file_scan(
        new_files: int,
        changed_files: int,
        total_files: int,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Wynik skanowania input/ -> PerceptionEvent(file_scan_result).

        Args:
            new_files: Liczba nowych plikow
            changed_files: Liczba zmienionych plikow
            total_files: Calkowita liczba plikow
            parent_event_id: opcjonalny event_id przyczyny
        """
        return create_event(
            source=PerceptionSource.LEARNING,
            event_type="file_scan_result",
            payload={
                "new_files": new_files,
                "changed_files": changed_files,
                "total_files": total_files,
            },
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_sandbox_promoted(
        session_id: str,
        files_promoted: int,
        chunks_promoted: int,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Sandbox promoted -> PerceptionEvent(sandbox_promoted).

        Args:
            session_id: ID sesji sandbox
            files_promoted: Liczba promowanych plikow
            chunks_promoted: Liczba promowanych chunkow
            parent_event_id: opcjonalny event_id przyczyny
        """
        return create_event(
            source=PerceptionSource.LEARNING,
            event_type="sandbox_promoted",
            payload={
                "session_id": session_id,
                "files_promoted": files_promoted,
                "chunks_promoted": chunks_promoted,
            },
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_sandbox_discarded(
        session_id: str,
        reason: str,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Sandbox discarded -> PerceptionEvent(sandbox_discarded).

        Args:
            session_id: ID sesji sandbox
            reason: Powod odrzucenia
            parent_event_id: opcjonalny event_id przyczyny
        """
        return create_event(
            source=PerceptionSource.LEARNING,
            event_type="sandbox_discarded",
            payload={
                "session_id": session_id,
                "reason": reason,
            },
            parent_event_id=parent_event_id,
        )
