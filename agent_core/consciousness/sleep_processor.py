"""
SleepProcessor - Processes sleep phases for Maria's consciousness.

When Maria enters SLEEP mode, this processor runs through 4 phases:
- NREM1: Short-term consolidation (gather stats)
- NREM2: Strengthen important connections (boost edge weights)
- NREM3: Garbage collection (mark stale nodes as outdated)
- REM: Dreams - creative concept linking (DreamGenerator)

Pure logic, no LLM calls. Runs once when SLEEP mode is entered.
"""

import time
import logging
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from agent_core.consciousness.dream_generator import DreamGenerator

logger = logging.getLogger(__name__)

# Thresholds for NREM phases
EDGE_BOOST_MIN_ACCESS = 2       # Boost edges accessed 2+ times
EDGE_BOOST_AMOUNT = 0.1         # Weight increase per boost
NODE_STALE_HOURS = 48           # Mark nodes older than this if low importance
NODE_LOW_IMPORTANCE = 0.2       # Below this importance = candidate for cleanup
MAX_DREAMS_PER_CYCLE = 3        # Dreams generated in REM phase


class SleepPhase(Enum):
    """Sleep cycle phases."""
    NREM1 = "nrem1"
    NREM2 = "nrem2"
    NREM3 = "nrem3"
    REM = "rem"


class SleepProcessor:
    """
    Processes a full sleep cycle through 4 phases.

    Usage:
        processor = SleepProcessor(semantic_memory)
        report = processor.process_sleep_cycle()
        # report = {"phases": {...}, "dreams": [...], "duration_ms": 42}
    """

    def __init__(
        self,
        semantic_memory,
        session_id: int = 0,
        dream_log_path=None,
    ):
        """
        Initialize sleep processor.

        Args:
            semantic_memory: SemanticGraph instance
            session_id: Current session number
            dream_log_path: Optional path for dream persistence
        """
        self.graph = semantic_memory
        self.session_id = session_id
        self.dream_generator = DreamGenerator(
            semantic_memory,
            dream_log_path=dream_log_path,
        )

    def process_sleep_cycle(self) -> Dict[str, Any]:
        """
        Run full sleep cycle through all 4 phases.

        Returns:
            Report dict with phase results, dreams, and duration
        """
        start = time.time()

        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session": self.session_id,
            "phases": {},
            "dreams": [],
            "duration_ms": 0,
        }

        # Phase 1: NREM1 - Consolidation (gather stats)
        try:
            report["phases"]["nrem1"] = self._phase_nrem1()
        except Exception as e:
            logger.warning(f"NREM1 failed: {e}")
            report["phases"]["nrem1"] = {"error": str(e)}

        # Phase 2: NREM2 - Strengthen connections
        try:
            report["phases"]["nrem2"] = self._phase_nrem2()
        except Exception as e:
            logger.warning(f"NREM2 failed: {e}")
            report["phases"]["nrem2"] = {"error": str(e)}

        # Phase 3: NREM3 - Garbage collection
        try:
            report["phases"]["nrem3"] = self._phase_nrem3()
        except Exception as e:
            logger.warning(f"NREM3 failed: {e}")
            report["phases"]["nrem3"] = {"error": str(e)}

        # Phase 4: REM - Dreams
        try:
            rem_result = self._phase_rem()
            report["phases"]["rem"] = rem_result
            report["dreams"] = rem_result.get("dreams", [])
        except Exception as e:
            logger.warning(f"REM failed: {e}")
            report["phases"]["rem"] = {"error": str(e)}

        report["duration_ms"] = round((time.time() - start) * 1000, 1)

        logger.info(
            f"Sleep cycle complete: {len(report['dreams'])} dreams, "
            f"{report['duration_ms']}ms"
        )

        return report

    def _phase_nrem1(self) -> Dict[str, Any]:
        """
        NREM1 - Short-term consolidation.

        Gathers statistics about the current state of semantic memory.
        Light sleep phase - just observation.
        """
        total_nodes = len(self.graph.nodes)
        total_edges = len(self.graph.edges)

        # Count by type
        type_counts = {}
        for node in self.graph.nodes.values():
            ntype = node.get("type", "unknown")
            type_counts[ntype] = type_counts.get(ntype, 0) + 1

        # Count outdated
        outdated = sum(
            1 for n in self.graph.nodes.values()
            if n.get("is_outdated", False)
        )

        # Average importance
        importances = [
            n.get("importance", 0.5)
            for n in self.graph.nodes.values()
        ]
        avg_importance = sum(importances) / max(len(importances), 1)

        result = {
            "phase": "nrem1",
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "type_counts": type_counts,
            "outdated_nodes": outdated,
            "avg_importance": round(avg_importance, 3),
        }

        logger.debug(f"NREM1: {total_nodes} nodes, {total_edges} edges")
        return result

    def _phase_nrem2(self) -> Dict[str, Any]:
        """
        NREM2 - Strengthen important connections.

        Boosts edge weights for frequently accessed edges.
        Deep sleep phase - reinforcing memories.
        """
        boosted = 0

        for edge_key, edge in self.graph.edges.items():
            access_count = edge.get("access_count", 0)
            if access_count >= EDGE_BOOST_MIN_ACCESS:
                old_weight = edge.get("weight", 1.0)
                new_weight = min(2.0, old_weight + EDGE_BOOST_AMOUNT)
                edge["weight"] = new_weight
                boosted += 1

        result = {
            "phase": "nrem2",
            "edges_boosted": boosted,
            "boost_amount": EDGE_BOOST_AMOUNT,
        }

        logger.debug(f"NREM2: boosted {boosted} edges")
        return result

    def _phase_nrem3(self) -> Dict[str, Any]:
        """
        NREM3 - Garbage collection.

        Marks old, low-importance nodes as outdated.
        Very deep sleep - forgetting unimportant things.
        """
        marked = 0
        now = datetime.now()
        stale_threshold = now - timedelta(hours=NODE_STALE_HOURS)

        for node in self.graph.nodes.values():
            if node.get("is_outdated", False):
                continue

            importance = node.get("importance", 0.5)
            if importance >= NODE_LOW_IMPORTANCE:
                continue

            # Check age
            created_str = node.get("created_at", "")
            if not created_str:
                continue

            try:
                created = datetime.fromisoformat(created_str)
                if created < stale_threshold:
                    node["is_outdated"] = True
                    marked += 1
            except (ValueError, TypeError):
                continue

        result = {
            "phase": "nrem3",
            "nodes_marked_outdated": marked,
            "stale_threshold_hours": NODE_STALE_HOURS,
            "importance_threshold": NODE_LOW_IMPORTANCE,
        }

        logger.debug(f"NREM3: marked {marked} nodes as outdated")
        return result

    def _phase_rem(self) -> Dict[str, Any]:
        """
        REM - Dream phase.

        Generates creative connections between concepts.
        Uses DreamGenerator for rule-based dream creation.
        """
        dreams = self.dream_generator.generate_dreams(count=MAX_DREAMS_PER_CYCLE)

        # Save dreams to disk
        if dreams:
            self.dream_generator.save_dreams(dreams, session_id=self.session_id)

        result = {
            "phase": "rem",
            "dreams_generated": len(dreams),
            "dreams": dreams,
        }

        logger.debug(f"REM: generated {len(dreams)} dreams")
        return result
