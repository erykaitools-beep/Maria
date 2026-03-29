"""
BeliefBuilder - Populates world model from existing JSONL sources.

READ-ONLY consumption of:
- knowledge_index.jsonl (file statuses, exam scores)
- maria_longterm_memory.jsonl (summaries, tags, key_points per chunk)
- exam_results.jsonl (pass/fail confirmation)

Zero LLM. Zero side effects on source files.
Pattern: KnowledgeAnalyzer (teacher/knowledge_analyzer.py)
Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
"""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.world_model.belief_model import (
    Belief, BeliefType, BeliefSource, EntityType, create_belief,
)
from agent_core.world_model.belief_store import BeliefStore

logger = logging.getLogger(__name__)

# Tag normalization (same rules as KnowledgeAnalyzer)
_TAG_STOP_WORDS = {
    "inne", "ogolne", "wiedza", "other", "general", "misc",
    "rozne", "notatki", "tekst", "plik",
}
_TAG_MIN_LEN = 2
_TAG_MAX_LEN = 40


def _normalize_tag(tag: str) -> Optional[str]:
    """Normalize a tag. Same logic as KnowledgeAnalyzer._normalize_tag()."""
    normalized = tag.lower().strip()
    if len(normalized) < _TAG_MIN_LEN or len(normalized) > _TAG_MAX_LEN:
        return None
    if normalized in _TAG_STOP_WORDS:
        return None
    return normalized


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load records from a JSONL file. Returns empty list on error."""
    if not path.exists():
        return []
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except IOError:
        pass
    return records


class BeliefBuilder:
    """
    Builds beliefs from existing JSONL data sources.

    All methods are idempotent - they check for existing beliefs
    before creating duplicates (via entity + source_id matching).
    """

    def __init__(
        self,
        knowledge_index_path: Path,
        longterm_memory_path: Path,
        exam_results_path: Path,
    ):
        self._knowledge_index_path = Path(knowledge_index_path)
        self._longterm_memory_path = Path(longterm_memory_path)
        self._exam_results_path = Path(exam_results_path)

    def build_all(self, store: BeliefStore) -> Dict[str, int]:
        """
        Build all beliefs from JSONL sources. Idempotent.

        Returns:
            Stats dict with counts per category.
        """
        stats = {
            "topics": self.build_topic_beliefs(store),
            "files": self.build_file_beliefs(store),
            "concepts": self.build_concept_beliefs(store),
        }
        logger.info(
            f"[WorldModel] Built beliefs: "
            f"{stats['topics']} topics, {stats['files']} files, "
            f"{stats['concepts']} concepts"
        )
        return stats

    def build_topic_beliefs(self, store: BeliefStore) -> int:
        """
        Create TOPIC beliefs from longterm memory tags.

        Each unique tag becomes a TOPIC entity with confidence
        based on how many files mention it.
        """
        records = _load_jsonl(self._longterm_memory_path)
        if not records:
            return 0

        # Count tag occurrences and track source files
        tag_files: Dict[str, set] = defaultdict(set)
        for rec in records:
            source_file = rec.get("source_file", "")
            for tag in rec.get("tags", []):
                normalized = _normalize_tag(tag)
                if normalized:
                    tag_files[normalized].add(source_file)

        created = 0
        for tag, files in tag_files.items():
            # Dedup: skip if belief already exists for this topic
            if store.find_by_entity_and_source(tag, f"topic:{tag}"):
                continue

            confidence = min(1.0, len(files) / 5.0)
            belief = create_belief(
                entity=tag,
                entity_type=EntityType.TOPIC,
                belief_type=BeliefType.OBSERVATION,
                content=f"Temat '{tag}' wystepuje w {len(files)} plikach",
                confidence=confidence,
                source=BeliefSource.LEARNING,
                source_id=f"topic:{tag}",
                tags=[tag],
                related_entities=list(files)[:10],
                evidence=[(BeliefSource.LEARNING.value, f"topic:{tag}", confidence)],
            )
            store.add(belief)
            created += 1

        return created

    def build_file_beliefs(self, store: BeliefStore) -> int:
        """
        Create FILE beliefs from knowledge_index.

        File status determines belief type and confidence.
        """
        records = _load_jsonl(self._knowledge_index_path)
        if not records:
            return 0

        # MERGE semantics: last record per id wins
        by_id: Dict[str, Dict] = {}
        for rec in records:
            file_id = rec.get("id", rec.get("file", ""))
            if file_id:
                by_id[file_id] = rec

        created = 0
        for file_id, rec in by_id.items():
            # Dedup
            if store.find_by_entity_and_source(file_id, f"file:{file_id}"):
                continue

            status = rec.get("status", "new")
            last_scores = rec.get("last_scores", [])
            avg_score = sum(last_scores) / len(last_scores) if last_scores else 0.0
            chunks_learned = rec.get("chunks_learned", 0)
            total_chunks = rec.get("total_chunks", 1)

            if status == "completed" and avg_score >= 0.7:
                belief_type = BeliefType.FACT
                confidence = min(1.0, avg_score)
                content = f"Plik '{file_id}' opanowany (score {avg_score:.0%})"
            elif status == "completed":
                belief_type = BeliefType.OBSERVATION
                confidence = max(0.3, avg_score)
                content = f"Plik '{file_id}' ukonczony, ale slaby wynik ({avg_score:.0%})"
            elif status == "learning":
                belief_type = BeliefType.OBSERVATION
                progress = chunks_learned / max(total_chunks, 1)
                confidence = progress * 0.5
                content = f"Plik '{file_id}' w trakcie nauki ({chunks_learned}/{total_chunks})"
            else:
                # new or unknown status
                belief_type = BeliefType.OBSERVATION
                confidence = 0.1
                content = f"Plik '{file_id}' nowy, nie rozpoczety"

            tags = [t.lower() for t in rec.get("tags", [])][:10]
            ev = [(BeliefSource.LEARNING.value, f"file:{file_id}", confidence)]
            if avg_score > 0:
                ev.append((BeliefSource.EXAM.value, f"exam:{file_id}", avg_score))
            belief = create_belief(
                entity=file_id,
                entity_type=EntityType.FILE,
                belief_type=belief_type,
                content=content,
                confidence=confidence,
                source=BeliefSource.LEARNING,
                source_id=f"file:{file_id}",
                tags=tags,
                evidence=ev,
            )
            store.add(belief)
            created += 1

        return created

    def build_concept_beliefs(self, store: BeliefStore) -> int:
        """
        Create CONCEPT beliefs from longterm memory key_points.

        Each key_point becomes a CONCEPT with tags as related entities.
        """
        records = _load_jsonl(self._longterm_memory_path)
        if not records:
            return 0

        # Build exam score map for confidence boosting
        exam_records = _load_jsonl(self._exam_results_path)
        exam_scores: Dict[str, float] = {}
        for er in exam_records:
            file_id = er.get("file", "")
            score = er.get("score", 0.0)
            if file_id:
                # Keep best score per file
                exam_scores[file_id] = max(exam_scores.get(file_id, 0.0), score)

        created = 0
        for rec in records:
            source_file = rec.get("source_file", "")
            chunk_id = rec.get("chunk_id", source_file)
            key_points = rec.get("key_points", [])
            tags = rec.get("tags", [])
            normalized_tags = [t for t in (_normalize_tag(tg) for tg in tags) if t]

            for i, kp in enumerate(key_points):
                if not kp or not isinstance(kp, str):
                    continue

                # Truncate very long key points
                kp_short = kp[:200] if len(kp) > 200 else kp
                concept_id = f"concept:{chunk_id}:{i}"

                # Dedup
                if store.find_by_entity_and_source(kp_short, concept_id):
                    continue

                # Base confidence + boost if exam passed
                confidence = 0.5
                belief_type = BeliefType.OBSERVATION
                best_score = exam_scores.get(source_file, 0.0)
                if best_score >= 0.7:
                    confidence = min(1.0, confidence + 0.2)
                    belief_type = BeliefType.FACT

                ev = [(BeliefSource.MEMORY_FACT.value, concept_id, confidence)]
                if best_score >= 0.7:
                    ev.append((BeliefSource.EXAM.value, f"exam:{source_file}", best_score))
                belief = create_belief(
                    entity=kp_short,
                    entity_type=EntityType.CONCEPT,
                    belief_type=belief_type,
                    content=kp_short,
                    confidence=confidence,
                    source=BeliefSource.MEMORY_FACT,
                    source_id=concept_id,
                    tags=normalized_tags,
                    related_entities=[source_file],
                    evidence=ev,
                )
                store.add(belief)
                created += 1

        return created

    def update_from_exam(
        self, store: BeliefStore, exam_record: Dict[str, Any]
    ) -> int:
        """
        Update beliefs based on exam result.

        Pass (score >= 0.7): +0.1 confidence, upgrade OBSERVATION to FACT.
        Fail (score < 0.7): -0.15 confidence, keep OBSERVATION.

        Returns:
            Number of beliefs revised.
        """
        file_id = exam_record.get("file", "")
        score = exam_record.get("score", 0.0)
        if not file_id:
            return 0

        passed = score >= 0.7
        revised = 0

        # Find beliefs related to this file (by source_id or related_entities)
        candidates = []
        for belief in store.get_current():
            if belief.source_id and file_id in belief.source_id:
                candidates.append(belief)
            elif file_id in belief.related_entities:
                candidates.append(belief)

        exam_evidence = [(BeliefSource.EXAM.value, f"exam:{file_id}", score)]

        for belief in candidates:
            if passed:
                new_conf = min(1.0, belief.confidence + 0.1)
                new_type = BeliefType.FACT
            else:
                new_conf = max(0.1, belief.confidence - 0.15)
                new_type = None  # Keep current type

            result = store.revise(
                belief.belief_id, new_conf, new_type,
                new_evidence=exam_evidence,
            )
            if result:
                revised += 1

        return revised
