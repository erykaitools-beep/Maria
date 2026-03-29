"""
Cross-Validator - Validates learned knowledge using a second LLM.

Post-learning validation flow:
1. Load learned chunk from memory (summary, key_points, tags)
2. Send original source text to secondary LLM with same prompt
3. Compare results using ConfidenceScorer
4. Log disputes to DisputeLog
5. Update confidence in memory record

The validator does NOT re-learn. It only validates existing knowledge
by asking a different LLM to independently analyze the same text.

ADR-027: Multi-Source Learning.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_core.cross_validation.confidence_scorer import ConfidenceScorer
from agent_core.cross_validation.dispute_log import DisputeLog

logger = logging.getLogger(__name__)

# Validation prompt - same structure as learning but explicit about independent analysis
VALIDATION_PROMPT = """Przeczytaj ponizszy fragment tekstu i wykonaj niezalezna analize.

Twoje zadanie:
1. Stresci fragment w maksymalnie 10-12 zdaniach.
2. Wypisz liste 5-12 kluczowych punktow (bullet-points).
3. Wyodrebnij 5-15 najwazniejszych pojec/tagow.

Odpowiedz w czystym JSON (bez markdown):
{{
  "summary": "...",
  "key_points": ["...", "..."],
  "tags": ["...", "..."]
}}

Tekst do analizy:
{chunk_text}"""

# Minimum confidence score to consider knowledge "validated"
VALIDATION_THRESHOLD = 0.5

# Maximum chunks to validate per session
MAX_CHUNKS_PER_SESSION = 10


class CrossValidator:
    """
    Validates learned knowledge by cross-checking with a second LLM.

    Usage:
        validator = CrossValidator(
            llm_fn=lambda p: nim_client._ask_once(p),
            source_name="nim",
        )
        results = validator.validate_file(file_id, chunks, memories)
    """

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
        source_name: str = "secondary",
        scorer: Optional[ConfidenceScorer] = None,
        dispute_log: Optional[DisputeLog] = None,
    ):
        """
        Args:
            llm_fn: Secondary LLM function (prompt -> response)
            source_name: Name of secondary source for logging
            scorer: ConfidenceScorer instance
            dispute_log: DisputeLog instance for persisting disputes
        """
        self._llm_fn = llm_fn
        self._source_name = source_name
        self._scorer = scorer or ConfidenceScorer()
        self._dispute_log = dispute_log or DisputeLog()

        # Stats
        self._total_validations = 0
        self._total_agreements = 0
        self._total_disputes = 0

    def set_llm_fn(self, llm_fn: Callable[[str], str]) -> None:
        """Set or update the secondary LLM function."""
        self._llm_fn = llm_fn

    def validate_chunk(
        self,
        chunk_id: str,
        file_id: str,
        chunk_text: str,
        original_result: Dict[str, Any],
        primary_source: str = "ollama",
    ) -> Dict[str, Any]:
        """
        Validate a single learned chunk.

        Args:
            chunk_id: Chunk identifier (e.g. "file#chunk_0")
            file_id: Source file ID
            chunk_text: Original source text
            original_result: What the primary LLM learned {summary, key_points, tags}
            primary_source: Name of primary LLM

        Returns:
            {
                "validated": bool,
                "confidence": float,
                "score_details": {...},
                "disputes": [...],
                "secondary_result": {...} or None,
            }
        """
        if not self._llm_fn:
            return {
                "validated": False,
                "confidence": 0.0,
                "error": "No secondary LLM configured",
            }

        self._total_validations += 1

        # Call secondary LLM
        prompt = VALIDATION_PROMPT.format(chunk_text=chunk_text[:3000])
        try:
            response = self._llm_fn(prompt)
        except Exception as e:
            logger.warning("[CrossValidator] LLM call failed: %s", e)
            return {
                "validated": False,
                "confidence": 0.0,
                "error": str(e),
            }

        # Parse response
        secondary_result = self._parse_response(response)
        if not secondary_result:
            return {
                "validated": False,
                "confidence": 0.0,
                "error": "Failed to parse secondary LLM response",
            }

        # Score agreement
        score = self._scorer.score(original_result, secondary_result)

        # Log disputes
        if score["disputes"]:
            self._dispute_log.record_disputes(
                chunk_id=chunk_id,
                file_id=file_id,
                source_a=primary_source,
                source_b=self._source_name,
                disputes=score["disputes"],
                confidence_score=score["overall"],
            )
            self._total_disputes += len(score["disputes"])

        validated = score["overall"] >= VALIDATION_THRESHOLD
        if validated:
            self._total_agreements += 1

        return {
            "validated": validated,
            "confidence": score["overall"],
            "score_details": score,
            "disputes": score["disputes"],
            "secondary_result": secondary_result,
        }

    def validate_file(
        self,
        file_id: str,
        chunk_texts: Dict[str, str],
        memory_records: List[Dict[str, Any]],
        primary_source: str = "ollama",
        max_chunks: int = MAX_CHUNKS_PER_SESSION,
    ) -> Dict[str, Any]:
        """
        Validate all learned chunks for a file.

        Args:
            file_id: Source file ID
            chunk_texts: {chunk_id: original_text}
            memory_records: Learned memory records for this file
            primary_source: Name of primary LLM
            max_chunks: Max chunks to validate per call

        Returns:
            {
                "file_id": str,
                "chunks_validated": int,
                "chunks_agreed": int,
                "chunks_disputed": int,
                "avg_confidence": float,
                "results": [{...per chunk...}],
            }
        """
        results = []
        total_confidence = 0.0

        # Build lookup: chunk_id -> memory record
        memory_by_chunk = {}
        for rec in memory_records:
            cid = rec.get("chunk_id", "")
            if cid:
                memory_by_chunk[cid] = rec

        validated_count = 0
        for chunk_id, chunk_text in list(chunk_texts.items())[:max_chunks]:
            memory = memory_by_chunk.get(chunk_id)
            if not memory:
                continue

            result = self.validate_chunk(
                chunk_id=chunk_id,
                file_id=file_id,
                chunk_text=chunk_text,
                original_result=memory,
                primary_source=primary_source,
            )
            results.append({"chunk_id": chunk_id, **result})
            if "confidence" in result:
                total_confidence += result["confidence"]
                validated_count += 1

        agreed = sum(1 for r in results if r.get("validated"))
        disputed = sum(1 for r in results if r.get("disputes"))
        avg_conf = total_confidence / validated_count if validated_count else 0.0

        return {
            "file_id": file_id,
            "chunks_validated": validated_count,
            "chunks_agreed": agreed,
            "chunks_disputed": disputed,
            "avg_confidence": round(avg_conf, 3),
            "results": results,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get validator statistics."""
        return {
            "total_validations": self._total_validations,
            "total_agreements": self._total_agreements,
            "total_disputes": self._total_disputes,
            "agreement_rate": (
                self._total_agreements / self._total_validations
                if self._total_validations else 0.0
            ),
            "dispute_log_stats": self._dispute_log.get_stats(),
        }

    @staticmethod
    def _parse_response(response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response, with markdown fallback."""
        if not response:
            return None
        try:
            from maria_core.learning.llm_utils import extract_json_from_response
            return extract_json_from_response(response)
        except (ImportError, Exception):
            pass
        # Simple fallback: try direct JSON parse
        try:
            # Strip markdown fences
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            return json.loads(text)
        except (json.JSONDecodeError, Exception):
            return None
