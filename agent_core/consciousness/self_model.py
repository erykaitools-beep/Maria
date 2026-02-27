"""
SelfModelBuilder - Maria's self-concept in the semantic graph.

Creates and maintains 'self_concept' nodes that represent Maria's
understanding of herself: name, purpose, traits, capabilities.

Traits evolve over time based on accumulated experiences.
Trait scores are stored on the self_concept node and persisted
via IdentityStore (since the graph is recreated each session).

Uses the existing SemanticGraph (same one used for learning).
"""

import time
import logging
from typing import Optional, List, Dict, Any

from agent_core.consciousness.trait_catalog import (
    TRAIT_CATALOG,
    EMERGENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)


class SelfModelBuilder:
    """
    Builds and updates Maria's self-concept in the semantic graph.

    Self-model nodes use type='self_concept'. This makes them
    queryable alongside Maria's learned knowledge.

    Usage:
        builder = SelfModelBuilder(semantic_memory)
        builder.ensure_self_model()

        print(builder.get_self_description())
        # "Jestem Maria (M.A.R.I.A.). Ucze sie autonomicznie z plikow.
        #  Moje cechy: ciekawska, systematyczna, pomocna."
    """

    # Default traits Maria starts with
    INITIAL_TRAITS = [
        "ciekawska",
        "systematyczna",
        "pomocna",
    ]

    def __init__(self, semantic_memory):
        """
        Initialize with reference to semantic graph.

        Args:
            semantic_memory: SemanticGraph instance (shared with learning system)
        """
        self.graph = semantic_memory
        self._self_node_id = None

    def ensure_self_model(self) -> str:
        """
        Create self-model if not exists, return self node_id.

        Idempotent - safe to call multiple times.

        Returns:
            Node ID of the self-concept node.
        """
        existing = self.graph.find_node_by_label("maria", "self_concept")
        if existing:
            self._self_node_id = existing["id"]
            logger.debug(f"Self-model already exists: {self._self_node_id}")
            return self._self_node_id

        return self._create_initial_self_model()

    def _create_initial_self_model(self) -> str:
        """Create initial self-concept nodes and edges."""
        # Main self-concept node
        self_id = self.graph.add_node(
            label="maria",
            node_type="self_concept",
            attributes={
                "name": "Maria",
                "full_name": "M.A.R.I.A.",
                "expanded": "Meta Analysis Recalibration Intelligence Architecture",
                "purpose": "autonomiczna nauka z plikow tekstowych",
                "traits": list(self.INITIAL_TRAITS),
                "capabilities": [
                    "uczenie sie z plikow",
                    "budowanie grafu wiedzy",
                    "egzaminowanie",
                    "introspekcja kodu",
                    "homeostaza",
                ],
                "limitations": [
                    "model llama3.1:8b",
                    "lokalne przetwarzanie",
                    "brak stalego internetu",
                ],
            },
            confidence=0.95,
            source="consciousness",
        )

        # Goal node
        goal_id = self.graph.add_node(
            label="cel_uczenie",
            node_type="goal",
            attributes={
                "description": "Autonomiczna nauka i strukturyzacja wiedzy",
                "priority": "primary",
            },
            confidence=0.95,
            source="consciousness",
        )

        # Edge: Maria -> has_goal -> learning
        try:
            self.graph.add_edge(
                self_id, "has_goal", goal_id,
                weight=1.0,
                confidence=0.95,
                source="consciousness",
            )
        except ValueError:
            pass  # Edge already exists or nodes missing

        self._self_node_id = self_id
        logger.info(f"Self-model created: {self_id}")
        return self_id

    def get_self_node(self) -> Optional[Dict[str, Any]]:
        """
        Get the self-concept node data.

        Returns:
            Node dict or None if not initialized.
        """
        if self._self_node_id and self._self_node_id in self.graph.nodes:
            return self.graph.nodes[self._self_node_id]

        # Try to find it
        existing = self.graph.find_node_by_label("maria", "self_concept")
        if existing:
            self._self_node_id = existing["id"]
            return existing
        return None

    def get_traits(self) -> List[str]:
        """
        Get Maria's current personality traits.

        Returns:
            List of trait strings.
        """
        node = self.get_self_node()
        if node and "attributes" in node:
            return node["attributes"].get("traits", [])
        return list(self.INITIAL_TRAITS)

    def update_trait(self, trait: str, confidence: float = 0.8) -> None:
        """
        Add or reinforce a personality trait.

        Args:
            trait: Trait name (e.g., "analityczna", "cierpliwa")
            confidence: How confident we are about this trait (0-1)
        """
        node = self.get_self_node()
        if node is None:
            self.ensure_self_model()
            node = self.get_self_node()

        if node and "attributes" in node:
            traits = node["attributes"].get("traits", [])
            if trait not in traits:
                traits.append(trait)
                node["attributes"]["traits"] = traits
                logger.info(f"New trait added: {trait} (confidence: {confidence})")

    def get_self_description(self) -> str:
        """
        Human-readable self-description.

        Returns:
            Maria's self-description in Polish.
        """
        node = self.get_self_node()
        if node is None:
            return "Jestem Maria, ale jeszcze sie nie znam dobrze."

        attrs = node.get("attributes", {})
        name = attrs.get("name", "Maria")
        full_name = attrs.get("full_name", "M.A.R.I.A.")
        purpose = attrs.get("purpose", "nauka")
        traits = attrs.get("traits", [])
        capabilities = attrs.get("capabilities", [])

        parts = [
            f"Jestem {name} ({full_name}).",
            f"Moj cel: {purpose}.",
        ]

        if traits:
            traits_str = ", ".join(traits[:5])
            parts.append(f"Moje cechy: {traits_str}.")

        if capabilities:
            caps_str = ", ".join(capabilities[:4])
            parts.append(f"Umiem: {caps_str}.")

        return " ".join(parts)

    def get_self_summary(self) -> Dict[str, Any]:
        """
        Get self-model as a dictionary for API/status.

        Returns:
            Dict with name, traits, capabilities, etc.
        """
        node = self.get_self_node()
        if node is None:
            return {"initialized": False}

        attrs = node.get("attributes", {})
        return {
            "initialized": True,
            "name": attrs.get("name", "Maria"),
            "full_name": attrs.get("full_name", "M.A.R.I.A."),
            "purpose": attrs.get("purpose", ""),
            "traits": attrs.get("traits", []),
            "trait_scores": attrs.get("trait_scores", {}),
            "capabilities": attrs.get("capabilities", []),
            "limitations": attrs.get("limitations", []),
            "node_id": node.get("id", ""),
        }

    # -------------------------------------------------
    # TRAIT SCORES (evolving personality)
    # -------------------------------------------------

    def get_trait_scores(self) -> Dict[str, Dict]:
        """
        Get detailed trait scores.

        Returns:
            Dict mapping trait_name -> {"score": float, "evidence_count": int, "last_updated": str}
        """
        node = self.get_self_node()
        if node and "attributes" in node:
            return node["attributes"].get("trait_scores", {})
        return {}

    def update_trait_scores(self, trait_scores: Dict[str, Dict]) -> None:
        """
        Update trait scores on self_concept node.

        Also updates the simple 'traits' list for backward compatibility:
        only traits with score >= EMERGENCE_THRESHOLD appear.

        Args:
            trait_scores: Dict mapping trait_name -> {"score": float, ...}
        """
        node = self.get_self_node()
        if node is None:
            self.ensure_self_model()
            node = self.get_self_node()

        if node and "attributes" in node:
            node["attributes"]["trait_scores"] = trait_scores

            # Update simple traits list (backward compatibility)
            emerged = sorted([
                name for name, data in trait_scores.items()
                if data.get("score", 0) >= EMERGENCE_THRESHOLD
            ])
            node["attributes"]["traits"] = emerged
            logger.debug(f"Trait scores updated, emerged: {emerged}")

    def add_milestone_experience(self, experience: Dict) -> Optional[str]:
        """
        Record a significant experience as a graph node linked to self.

        Only for milestone events (trait changes). Not every experience.

        Args:
            experience: Dict with at least 'event' and 'details' keys.

        Returns:
            Node ID of experience node, or None on failure.
        """
        self_id = self.ensure_self_model()

        label = "exp_{}_{}".format(
            experience.get("event", "unknown"),
            int(time.time()),
        )

        try:
            exp_id = self.graph.add_node(
                label=label,
                node_type="experience",
                attributes=experience,
                confidence=0.8,
                source="consciousness",
            )
        except Exception as e:
            logger.debug(f"Could not create experience node: {e}")
            return None

        try:
            self.graph.add_edge(
                self_id, "has_experience", exp_id,
                weight=1.0,
                confidence=0.8,
                source="consciousness",
            )
        except (ValueError, Exception):
            pass  # Node or edge issue, non-critical

        return exp_id

    def get_personality_description(self) -> str:
        """
        Human-readable personality description with trait scores.

        Returns:
            Multi-line Polish text describing personality.
        """
        trait_scores = self.get_trait_scores()
        if not trait_scores:
            return self.get_self_description()

        lines = [self.get_self_description(), ""]

        # Emerged traits (score >= threshold)
        emerged = []
        emerging = []
        dormant = []

        for name, data in sorted(trait_scores.items()):
            score = data.get("score", 0)
            evidence = data.get("evidence_count", 0)
            desc = TRAIT_CATALOG.get(name, {}).get("description", "")

            entry = f"  {name}: {score:.2f} ({evidence} doswiadczen)"
            if desc:
                entry += f" - {desc}"

            if score >= EMERGENCE_THRESHOLD:
                emerged.append(entry)
            elif score > 0:
                emerging.append(entry)
            else:
                dormant.append(entry)

        if emerged:
            lines.append("[Cechy aktywne]")
            lines.extend(emerged)

        if emerging:
            lines.append("\n[Cechy kielkujace]")
            lines.extend(emerging)

        return "\n".join(lines)
