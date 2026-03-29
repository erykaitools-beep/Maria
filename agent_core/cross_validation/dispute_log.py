"""
Dispute Log - Persists contradictions between LLM sources.

Records disagreements found during cross-validation.
Bounded in-memory + JSONL persistence.

ADR-027: Multi-Source Learning.
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
DEFAULT_LOG_PATH = _META_DIR / "dispute_log.jsonl"
MAX_RECENT = 200


@dataclass
class DisputeRecord:
    """A single cross-validation dispute."""
    dispute_id: str
    chunk_id: str                      # e.g. "file_id#chunk_0"
    file_id: str
    source_a: str                      # e.g. "nim", "ollama"
    source_b: str
    dimension: str                     # "summary", "key_points", "tags"
    severity: str                      # "low", "medium", "high"
    detail: str
    confidence_score: float            # overall score from scorer
    timestamp: float = 0.0
    resolved: bool = False
    resolution: str = ""               # how it was resolved

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "DisputeRecord":
        return cls(
            dispute_id=d.get("dispute_id", ""),
            chunk_id=d.get("chunk_id", ""),
            file_id=d.get("file_id", ""),
            source_a=d.get("source_a", ""),
            source_b=d.get("source_b", ""),
            dimension=d.get("dimension", ""),
            severity=d.get("severity", "low"),
            detail=d.get("detail", ""),
            confidence_score=d.get("confidence_score", 0.0),
            timestamp=d.get("timestamp", 0.0),
            resolved=d.get("resolved", False),
            resolution=d.get("resolution", ""),
        )


class DisputeLog:
    """
    Thread-safe dispute log with JSONL persistence.

    Records disagreements from cross-validation. Bounded in-memory.
    """

    def __init__(self, log_path: Optional[Path] = None):
        self._log_path = log_path or DEFAULT_LOG_PATH
        self._lock = threading.Lock()
        self._recent: List[DisputeRecord] = []

    def record_disputes(
        self,
        chunk_id: str,
        file_id: str,
        source_a: str,
        source_b: str,
        disputes: List[Dict[str, Any]],
        confidence_score: float,
    ) -> List[DisputeRecord]:
        """
        Record disputes from a cross-validation run.

        Args:
            chunk_id: Which chunk was validated
            file_id: Source file
            source_a: Primary LLM name
            source_b: Secondary LLM name
            disputes: List of dispute dicts from ConfidenceScorer
            confidence_score: Overall confidence score

        Returns:
            List of created DisputeRecords
        """
        records = []
        now = time.time()

        for d in disputes:
            record = DisputeRecord(
                dispute_id=f"disp-{uuid.uuid4().hex[:10]}",
                chunk_id=chunk_id,
                file_id=file_id,
                source_a=source_a,
                source_b=source_b,
                dimension=d.get("dimension", ""),
                severity=d.get("severity", "low"),
                detail=d.get("detail", ""),
                confidence_score=confidence_score,
                timestamp=now,
            )
            records.append(record)

        with self._lock:
            for r in records:
                self._recent.append(r)
                self._append_log(r)
            # Bound memory
            if len(self._recent) > MAX_RECENT:
                self._recent = self._recent[-MAX_RECENT:]

        if records:
            logger.info(
                "[DisputeLog] %d disputes for %s (confidence=%.2f)",
                len(records), chunk_id, confidence_score,
            )

        return records

    def get_recent(self, limit: int = 20) -> List[Dict]:
        """Get recent disputes."""
        with self._lock:
            return [r.to_dict() for r in self._recent[-limit:]]

    def get_by_file(self, file_id: str) -> List[Dict]:
        """Get disputes for a specific file."""
        with self._lock:
            return [
                r.to_dict() for r in self._recent
                if r.file_id == file_id
            ]

    def get_unresolved(self, limit: int = 20) -> List[Dict]:
        """Get unresolved disputes."""
        with self._lock:
            unresolved = [r for r in self._recent if not r.resolved]
            return [r.to_dict() for r in unresolved[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """Get dispute statistics."""
        with self._lock:
            total = len(self._recent)
            resolved = sum(1 for r in self._recent if r.resolved)
            by_severity = {}
            by_dimension = {}
            for r in self._recent:
                by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
                by_dimension[r.dimension] = by_dimension.get(r.dimension, 0) + 1
            avg_conf = (
                sum(r.confidence_score for r in self._recent) / total
                if total else 0.0
            )
            return {
                "total": total,
                "resolved": resolved,
                "unresolved": total - resolved,
                "by_severity": by_severity,
                "by_dimension": by_dimension,
                "avg_confidence": round(avg_conf, 3),
            }

    def _append_log(self, record: DisputeRecord) -> None:
        """Persist record to JSONL."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to write dispute log: %s", e)
