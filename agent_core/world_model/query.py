"""
WorldModelQuery - Structured queries for Planner and Goal Selector.

Provides the interface that PlannerCore._gather_context() uses.
All queries are O(n) or better with in-memory indexes.

Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional

from agent_core.world_model.belief_model import (
    Belief, BeliefType, EntityType,
)
from agent_core.world_model.belief_store import BeliefStore


class WorldModelQuery:
    """Query interface for the world model."""

    def __init__(self, store: BeliefStore):
        self._store = store

    def get_topic_confidence_map(self) -> Dict[str, float]:
        """
        Map of topic -> average confidence across all beliefs for that topic.

        Returns:
            Dict[topic_name, avg_confidence]
        """
        topics = self._store.get_by_entity_type(EntityType.TOPIC)
        result = {}
        for t in topics:
            result[t.entity] = t.confidence

        # Also aggregate concept confidences per tag
        tag_confidences: Dict[str, List[float]] = defaultdict(list)
        for b in self._store.get_current():
            for tag in b.tags:
                tag_confidences[tag].append(b.confidence)

        # Merge: use tag average if available, topic belief otherwise
        for tag, confs in tag_confidences.items():
            if confs:
                result[tag] = round(sum(confs) / len(confs), 3)

        return result

    def get_knowledge_gaps(self) -> List[Dict[str, Any]]:
        """
        Topics with low confidence or few beliefs.

        Returns:
            List of {"topic", "confidence", "belief_count"} sorted by
            confidence ascending (weakest first).
        """
        topic_map = self.get_topic_confidence_map()

        # Count beliefs per topic
        topic_counts: Dict[str, int] = defaultdict(int)
        for b in self._store.get_current():
            for tag in b.tags:
                topic_counts[tag] += 1

        gaps = []
        for topic, confidence in topic_map.items():
            gaps.append({
                "topic": topic,
                "confidence": confidence,
                "belief_count": topic_counts.get(topic, 0),
            })

        gaps.sort(key=lambda g: g["confidence"])
        return gaps

    def get_facts_for_topic(self, topic: str) -> List[Belief]:
        """All FACT-type beliefs for a given topic (by tag match)."""
        beliefs = self._store.get_by_tag(topic)
        return [b for b in beliefs if b.belief_type == BeliefType.FACT]

    def get_entity_summary(self, entity: str) -> Dict[str, Any]:
        """
        Summary of everything known about an entity.

        Returns:
            Dict with beliefs, avg_confidence, related_topics, counts.
        """
        beliefs = self._store.get_by_entity(entity)
        if not beliefs:
            return {
                "entity": entity,
                "beliefs": [],
                "avg_confidence": 0.0,
                "related_topics": [],
                "fact_count": 0,
                "observation_count": 0,
                "hypothesis_count": 0,
            }

        total_conf = sum(b.confidence for b in beliefs)
        all_tags = set()
        fact_count = 0
        obs_count = 0
        hyp_count = 0

        for b in beliefs:
            all_tags.update(b.tags)
            if b.belief_type == BeliefType.FACT:
                fact_count += 1
            elif b.belief_type == BeliefType.OBSERVATION:
                obs_count += 1
            else:
                hyp_count += 1

        return {
            "entity": entity,
            "beliefs": [b.to_dict() for b in beliefs],
            "avg_confidence": round(total_conf / len(beliefs), 3),
            "related_topics": sorted(all_tags),
            "fact_count": fact_count,
            "observation_count": obs_count,
            "hypothesis_count": hyp_count,
        }

    def get_world_summary(self) -> Dict[str, Any]:
        """
        Compact summary for planner context.

        Returns:
            Dict with counts, avg_confidence, weakest_topics.
        """
        current = self._store.get_current()

        facts = 0
        observations = 0
        hypotheses = 0
        total_conf = 0.0
        topic_count = 0

        for b in current:
            total_conf += b.confidence
            if b.belief_type == BeliefType.FACT:
                facts += 1
            elif b.belief_type == BeliefType.OBSERVATION:
                observations += 1
            else:
                hypotheses += 1
            if b.entity_type == EntityType.TOPIC:
                topic_count += 1

        avg_conf = round(total_conf / len(current), 3) if current else 0.0

        # Top 5 weakest topics
        gaps = self.get_knowledge_gaps()
        weakest = [g["topic"] for g in gaps[:5]]

        return {
            "total_beliefs": len(current),
            "facts": facts,
            "observations": observations,
            "hypotheses": hypotheses,
            "topics": topic_count,
            "avg_confidence": avg_conf,
            "weakest_topics": weakest,
        }
