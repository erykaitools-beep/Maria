"""
Unified Memory Query - single interface to all Maria's knowledge sources.

Phase 2 of Stabilization Roadmap: Memory Consistency.
Resolves ambiguity between knowledge_index, beliefs, semantic memory, and exam data.

Truth hierarchy (from most to least authoritative):
    1. Operator instructions (direct commands)
    2. Raw source records (knowledge_index, exam_results)
    3. Derived beliefs (K6 world model)
    4. Semantic vectors (embedding-based search)
    5. Episodic summaries (dreams, reflections)

Each MemoryResult carries: source, confidence, freshness, provenance.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemorySource(Enum):
    """Where a memory result came from."""
    KNOWLEDGE_INDEX = "knowledge_index"    # Primary learning data
    EXAM_RESULTS = "exam_results"          # Exam performance
    BELIEFS = "beliefs"                    # K6 world model (derived)
    SEMANTIC = "semantic"                  # Embedding search (derived)
    TOPIC_HINTS = "topic_hints"            # K12 suggestions


@dataclass
class MemoryResult:
    """Single result from unified memory query.

    Carries provenance metadata so consumers can judge reliability.
    """
    source: MemorySource
    content: str                           # Human-readable text
    confidence: float = 0.0                # 0.0-1.0 (how certain)
    freshness: float = 0.0                 # 0.0-1.0 (1.0 = just updated)
    relevance: float = 0.0                 # 0.0-1.0 (how relevant to query)
    provenance: Dict[str, Any] = field(default_factory=dict)  # Source-specific metadata

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "content": self.content,
            "confidence": round(self.confidence, 3),
            "freshness": round(self.freshness, 3),
            "relevance": round(self.relevance, 3),
            "provenance": self.provenance,
        }


def _freshness_score(ts: float, max_age_hours: float = 168) -> float:
    """Convert timestamp to freshness score (1.0 = now, 0.0 = max_age_hours ago)."""
    if ts <= 0:
        return 0.0
    age_hours = (time.time() - ts) / 3600
    if age_hours <= 0:
        return 1.0
    if age_hours >= max_age_hours:
        return 0.0
    return round(1.0 - (age_hours / max_age_hours), 3)


class MemoryQuery:
    """Unified memory query interface.

    Searches across knowledge_index, beliefs, semantic memory, and exam data.
    Returns merged, deduplicated results with provenance.
    """

    def __init__(
        self,
        knowledge_path: Optional[Path] = None,
        beliefs_path: Optional[Path] = None,
        exam_path: Optional[Path] = None,
        hints_path: Optional[Path] = None,
        semantic_memory=None,
    ):
        self._knowledge_path = knowledge_path or Path("memory/knowledge_index.jsonl")
        self._beliefs_path = beliefs_path or Path("meta_data/beliefs.jsonl")
        self._exam_path = exam_path or Path("memory/exam_results.jsonl")
        self._hints_path = hints_path or Path("meta_data/topic_hints.jsonl")
        self._semantic = semantic_memory

        # Lazy-loaded caches
        self._knowledge_cache: Optional[Dict[str, Dict]] = None
        self._beliefs_cache: Optional[Dict[str, Dict]] = None
        self._cache_ts: float = 0.0

    def set_semantic_memory(self, sm) -> None:
        """Attach SemanticMemory for embedding-based search."""
        self._semantic = sm

    def _invalidate_cache(self) -> None:
        """Force reload on next query (call after writes)."""
        self._knowledge_cache = None
        self._beliefs_cache = None

    def _ensure_cache(self, max_age_sec: float = 60) -> None:
        """Load/refresh caches if stale."""
        if self._knowledge_cache is not None and (time.time() - self._cache_ts) < max_age_sec:
            return

        self._knowledge_cache = {}
        self._beliefs_cache = {}
        self._cache_ts = time.time()

        # Load knowledge_index
        if self._knowledge_path.exists():
            for rec in _load_jsonl(self._knowledge_path):
                fid = rec.get("id", "")
                if fid:
                    self._knowledge_cache[fid] = rec

        # Load beliefs (MERGE: last per entity wins)
        if self._beliefs_path.exists():
            for rec in _load_jsonl(self._beliefs_path):
                entity = rec.get("entity", "")
                if entity and not rec.get("superseded_by"):
                    self._beliefs_cache[entity] = rec

    def query_topic(self, topic: str, top_k: int = 10) -> List[MemoryResult]:
        """Query all memory sources about a topic.

        Returns merged results sorted by: confidence * relevance * freshness.

        Args:
            topic: Topic string to search for.
            top_k: Max results per source.
        """
        self._ensure_cache()
        results: List[MemoryResult] = []
        topic_lower = topic.lower()

        # 1. Knowledge Index: file statuses matching topic
        for fid, rec in (self._knowledge_cache or {}).items():
            filename = rec.get("file", "")
            # Simple topic match: filename or tags contain topic
            if topic_lower in filename.lower() or topic_lower in fid.lower():
                status = rec.get("status", "new")
                scores = rec.get("last_scores", [])
                avg_score = sum(scores) / len(scores) if scores else 0.0
                updated_at = rec.get("updated_at", "")
                ts = _parse_ts(updated_at)

                results.append(MemoryResult(
                    source=MemorySource.KNOWLEDGE_INDEX,
                    content=f"Plik '{filename}': status={status}, chunks={rec.get('chunks_learned', 0)}/{rec.get('total_chunks', 0)}, avg_score={avg_score:.1%}",
                    confidence=avg_score if scores else 0.1,
                    freshness=_freshness_score(ts),
                    relevance=0.9 if topic_lower in filename.lower() else 0.6,
                    provenance={"file_id": fid, "status": status, "exam_attempts": rec.get("exam_attempts", 0)},
                ))

        # 2. Beliefs: entities matching topic
        for entity, rec in (self._beliefs_cache or {}).items():
            if topic_lower in entity.lower() or topic_lower in rec.get("content", "").lower():
                tags = rec.get("tags", [])
                tag_match = any(topic_lower in t.lower() for t in tags)
                ts = rec.get("updated_at", rec.get("created_at", 0))

                results.append(MemoryResult(
                    source=MemorySource.BELIEFS,
                    content=rec.get("content", entity),
                    confidence=rec.get("confidence", 0.5),
                    freshness=_freshness_score(ts),
                    relevance=0.9 if topic_lower in entity.lower() else (0.7 if tag_match else 0.5),
                    provenance={
                        "entity": entity,
                        "belief_type": rec.get("belief_type", ""),
                        "source": rec.get("source", ""),
                        "source_id": rec.get("source_id", ""),
                    },
                ))

        # 3. Semantic search (if available)
        if self._semantic:
            try:
                search_results = self._semantic.search(topic, top_k=top_k, threshold=0.3)
                for sr in search_results:
                    ns = sr.entry.metadata.get("namespace", "unknown")
                    results.append(MemoryResult(
                        source=MemorySource.SEMANTIC,
                        content=sr.entry.text,
                        confidence=0.5,  # Semantic similarity is not certainty
                        freshness=_freshness_score(sr.entry.metadata.get("created_ts", 0)),
                        relevance=sr.score,
                        provenance={
                            "entry_id": sr.entry.entry_id,
                            "namespace": ns,
                            "score": round(sr.score, 3),
                        },
                    ))
            except Exception as e:
                logger.debug(f"[MemoryQuery] Semantic search failed: {e}")

        # Sort by combined score: relevance * confidence * (0.5 + 0.5 * freshness)
        results.sort(
            key=lambda r: r.relevance * r.confidence * (0.5 + 0.5 * r.freshness),
            reverse=True,
        )

        return results[:top_k]

    def get_topic_summary(self, topic: str) -> Dict[str, Any]:
        """Get a concise summary of what Maria knows about a topic.

        Returns a single dict with:
        - files_known: count
        - avg_confidence: float
        - status: overall status
        - freshest_update: timestamp
        - sources_consulted: list of source names
        """
        results = self.query_topic(topic, top_k=20)
        if not results:
            return {"known": False, "topic": topic}

        knowledge_results = [r for r in results if r.source == MemorySource.KNOWLEDGE_INDEX]
        belief_results = [r for r in results if r.source == MemorySource.BELIEFS]

        confidences = [r.confidence for r in results if r.confidence > 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        freshest = max(r.freshness for r in results) if results else 0.0

        return {
            "known": True,
            "topic": topic,
            "files_count": len(knowledge_results),
            "beliefs_count": len(belief_results),
            "total_results": len(results),
            "avg_confidence": round(avg_conf, 3),
            "freshness": round(freshest, 3),
            "sources": list(set(r.source.value for r in results)),
        }

    def get_knowledge_gaps(self, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find topics with low confidence or missing coverage.

        Aggregates evidence across sources before flagging a gap:
        - Topic-level beliefs (observations) carry meta-info with fast decay
        - Fact beliefs carry actual knowledge, linked to topics via `tags`
        - knowledge_index files carry exam scores for files matching topic

        A topic is flagged as gap only when ALL evidence sources are weak.
        This prevents false positives when Maria has facts/exam passes on a
        topic but the observation-belief's confidence decayed over time.

        Useful for K12 Self-Analysis and topic suggestion.
        """
        self._ensure_cache()
        gaps = []

        # Partition beliefs: facts are evidence, others are gap candidates
        facts: List[Dict[str, Any]] = []
        candidates: Dict[str, Dict[str, Any]] = {}
        for entity, rec in (self._beliefs_cache or {}).items():
            if rec.get("belief_type") == "fact":
                facts.append(rec)
            else:
                candidates[entity] = rec

        for entity, rec in candidates.items():
            obs_conf = rec.get("confidence", 0.5)
            entity_lower = entity.lower()

            # Supporting facts: tags match the topic (case-insensitive)
            supporting_facts = [
                f for f in facts
                if any(t.lower() == entity_lower for t in f.get("tags", []))
            ]
            max_fact_conf = max(
                (f.get("confidence", 0.0) for f in supporting_facts),
                default=0.0,
            )

            # Supporting files: knowledge_index entry with matching filename + completed
            topic_token = entity_lower.replace(" ", "_").replace("-", "_")
            supporting_scores: List[float] = []
            for _fid, krec in (self._knowledge_cache or {}).items():
                fname = (krec.get("file") or "").lower()
                name_match = (topic_token in fname) or (entity_lower in fname)
                if name_match and krec.get("status") == "completed":
                    scores = krec.get("last_scores", [])
                    if scores:
                        supporting_scores.append(max(scores))
            max_file_score = max(supporting_scores, default=0.0)

            # Effective confidence: best available evidence wins
            effective = max(obs_conf, max_fact_conf, max_file_score)
            if effective >= 0.5:
                continue  # Not a gap — evidence exists

            has_evidence = bool(supporting_facts or supporting_scores)
            gaps.append({
                "topic": entity,
                "confidence": round(effective, 2),
                "source": rec.get("source", ""),
                "reason": "low_confidence_aggregate" if has_evidence else "low_confidence_belief",
                "evidence": {
                    "observation_conf": round(obs_conf, 2),
                    "fact_count": len(supporting_facts),
                    "max_fact_conf": round(max_fact_conf, 2),
                    "file_count": len(supporting_scores),
                    "max_file_score": round(max_file_score, 2),
                } if has_evidence else {},
            })

        # Files with exam_failed status — independent signal
        for fid, rec in (self._knowledge_cache or {}).items():
            if rec.get("status") in ("exam_failed", "hard_topic"):
                gaps.append({
                    "topic": fid,
                    "confidence": 0.2,
                    "source": "knowledge_index",
                    "reason": rec.get("status"),
                })

        gaps.sort(key=lambda g: g["confidence"])
        return gaps[:top_k]


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load records from JSONL file."""
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return records


def _parse_ts(ts_str) -> float:
    """Parse timestamp from various formats to UNIX float."""
    if isinstance(ts_str, (int, float)):
        return float(ts_str)
    if isinstance(ts_str, str) and ts_str:
        try:
            from datetime import datetime
            # ISO8601
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, AttributeError):
            pass
    return 0.0
