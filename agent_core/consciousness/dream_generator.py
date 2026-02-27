"""
DreamGenerator - Creative concept linking during REM sleep phase.

Generates "dreams" by randomly connecting concepts from the semantic graph.
Rule-based (no LLM), deterministic given the same random seed.

Dreams are reported to the user after waking up and persisted
in meta_data/dream_log.jsonl.
"""

import json
import time
import random
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

DEFAULT_DREAM_LOG_PATH = Path("meta_data/dream_log.jsonl")

# Dream text templates (Polish)
CONNECTION_TEMPLATES = [
    "Snilo mi sie, ze {a} laczy sie z {b} - moze sa ze soba powiazane?",
    "Przysnilo mi sie, ze {a} i {b} maja cos wspolnego. Ciekawe...",
    "We snie zobaczyalam polaczenie miedzy {a} a {b}. Warto zbadac.",
    "Snilo mi sie o {a}. Nagle pojawialo sie {b} - dziwne, ale intrygujace.",
    "Miaalam sen, ze {a} przechodzi w {b}. Czy to mozliwe?",
]

HYPOTHESIS_TEMPLATES = [
    "A co jesli {a} wplywa na {b}? We snie to mialo sens.",
    "Moze {a} i {b} to dwa aspekty tego samego? Tak mi sie snilo.",
    "Sen podpowiedzial mi: zbadaj zwiazek miedzy {a} a {b}.",
]

EXPLORATION_TEMPLATES = [
    "Snilo mi sie o {a}. Chcialabym wiedziec o tym wiecej.",
    "We snie gleboko myslalam o {a}. Moze warto do tego wrocic.",
]


class DreamGenerator:
    """
    Generates dreams by connecting random concepts from semantic graph.

    Usage:
        gen = DreamGenerator(semantic_memory)
        dreams = gen.generate_dreams(count=3)
        gen.save_dreams(dreams, session_id=11)
    """

    def __init__(self, semantic_memory, dream_log_path: Optional[Path] = None):
        """
        Initialize dream generator.

        Args:
            semantic_memory: SemanticGraph instance
            dream_log_path: Path for dream persistence
        """
        self.graph = semantic_memory
        self.dream_log_path = Path(dream_log_path or DEFAULT_DREAM_LOG_PATH)

    def generate_dreams(self, count: int = 3) -> List[Dict[str, Any]]:
        """
        Generate N dreams from semantic graph.

        Args:
            count: Number of dreams to generate

        Returns:
            List of dream entry dicts
        """
        dreams = []
        attempts = 0
        max_attempts = count * 3  # Avoid infinite loops

        while len(dreams) < count and attempts < max_attempts:
            attempts += 1
            dream = self.generate_dream()
            if dream:
                dreams.append(dream)

        return dreams

    def generate_dream(self) -> Optional[Dict[str, Any]]:
        """
        Generate a single dream.

        Picks random nodes from the graph and creates a creative
        connection between them.

        Returns:
            Dream entry dict or None if graph too small
        """
        nodes = list(self.graph.nodes.values())

        if len(nodes) < 2:
            return None

        # Filter out system/meta nodes, prefer entity nodes
        dreamable = [
            n for n in nodes
            if n.get("type") not in ("system", "meta")
            and not n.get("is_outdated", False)
        ]

        if len(dreamable) < 2:
            dreamable = nodes

        if len(dreamable) < 2:
            return None

        # Pick random pair - weighted by importance
        node_a, node_b = self._pick_random_pair(dreamable)

        if node_a is None or node_b is None:
            return None

        # Check if already connected
        already_connected = self._are_connected(node_a["id"], node_b["id"])

        # Choose dream type
        if already_connected:
            # Explore one of the nodes deeper
            dream_type = "exploration"
            target = random.choice([node_a, node_b])
            template = random.choice(EXPLORATION_TEMPLATES)
            content = template.format(a=target["label"])
            labels = [target["label"]]
            node_ids = [target["id"]]
        elif random.random() < 0.4:
            # Hypothesis dream
            dream_type = "hypothesis"
            template = random.choice(HYPOTHESIS_TEMPLATES)
            content = template.format(a=node_a["label"], b=node_b["label"])
            labels = [node_a["label"], node_b["label"]]
            node_ids = [node_a["id"], node_b["id"]]
        else:
            # Connection discovery dream
            dream_type = "connection_discovery"
            template = random.choice(CONNECTION_TEMPLATES)
            content = template.format(a=node_a["label"], b=node_b["label"])
            labels = [node_a["label"], node_b["label"]]
            node_ids = [node_a["id"], node_b["id"]]

            # Create a weak dream connection in graph
            try:
                self.graph.add_edge(
                    node_a["id"],
                    "dream_connection",
                    node_b["id"],
                    weight=0.3,
                    confidence=0.3,
                    source="dream",
                )
            except (ValueError, KeyError):
                pass  # Nodes may not exist anymore

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ts": time.time(),
            "phase": "rem",
            "type": dream_type,
            "content": content,
            "nodes": node_ids,
            "labels": labels,
            "confidence": 0.3,
            "to_explore": dream_type != "exploration",
        }

    def _pick_random_pair(self, nodes: List[Dict]) -> tuple:
        """Pick two random nodes, weighted by importance."""
        if len(nodes) < 2:
            return None, None

        # Weight by importance (0.5 default + some randomness)
        weights = [
            n.get("importance", 0.5) + random.random() * 0.3
            for n in nodes
        ]

        # Pick first node
        idx_a = self._weighted_choice(weights)
        node_a = nodes[idx_a]

        # Pick second node (different from first, prefer different type)
        remaining = [(i, n, w) for i, (n, w) in enumerate(zip(nodes, weights)) if i != idx_a]
        if not remaining:
            return None, None

        # Boost weight for nodes of different type
        type_a = node_a.get("type", "")
        adjusted = []
        for i, n, w in remaining:
            if n.get("type", "") != type_a:
                adjusted.append(w * 1.5)
            else:
                adjusted.append(w)

        idx_b = self._weighted_choice(adjusted)
        node_b = remaining[idx_b][1]

        return node_a, node_b

    def _weighted_choice(self, weights: List[float]) -> int:
        """Pick random index weighted by values."""
        total = sum(weights)
        if total == 0:
            return random.randint(0, len(weights) - 1)
        r = random.random() * total
        cumulative = 0
        for i, w in enumerate(weights):
            cumulative += w
            if r <= cumulative:
                return i
        return len(weights) - 1

    def _are_connected(self, node_a_id: str, node_b_id: str) -> bool:
        """Check if two nodes are already connected."""
        for (from_id, _rel, to_id) in self.graph.edges:
            if (from_id == node_a_id and to_id == node_b_id) or \
               (from_id == node_b_id and to_id == node_a_id):
                return True
        return False

    # --- Persistence ---

    def save_dreams(self, dreams: List[Dict], session_id: int = 0) -> None:
        """
        Append dreams to JSONL log file.

        Args:
            dreams: List of dream dicts
            session_id: Current session number
        """
        if not dreams:
            return

        try:
            self.dream_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.dream_log_path, "a", encoding="utf-8") as f:
                for dream in dreams:
                    dream["session"] = session_id
                    f.write(json.dumps(dream, ensure_ascii=False) + "\n")
            logger.info(f"Saved {len(dreams)} dreams to {self.dream_log_path}")
        except Exception as e:
            logger.warning(f"Failed to save dreams: {e}")

    @staticmethod
    def load_recent_dreams(limit: int = 10, dream_log_path: Optional[Path] = None) -> List[Dict]:
        """
        Load recent dreams from JSONL log.

        Can be called without an instance (static method).

        Args:
            limit: Maximum number of dreams to return
            dream_log_path: Override log path (default: meta_data/dream_log.jsonl)

        Returns:
            List of dream dicts, newest last
        """
        log_path = Path(dream_log_path or DEFAULT_DREAM_LOG_PATH)
        if not log_path.exists():
            return []

        dreams = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        dreams.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to load dreams: {e}")
            return []

        return dreams[-limit:]
