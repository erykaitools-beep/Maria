"""
PrivacyGuard - Hard privacy boundaries for operator data.

Operator defines topics that Maria must NEVER ask about, store, or infer.
These boundaries are non-overridable - even if Maria could deduce something,
she must not if the topic is bounded.

Checked BEFORE any fact storage or active questioning.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


class PrivacyGuard:
    """
    Hard privacy boundaries, operator-defined, non-overridable.

    Boundaries are stored as lowercase topic strings.
    Matching is substring-based and case-insensitive:
    boundary "salary" blocks "my salary is X", "salary info", etc.
    """

    def __init__(self, boundaries: List[str] = None):
        self._boundaries: List[str] = []
        if boundaries:
            for b in boundaries:
                self._add_internal(b)

    def _add_internal(self, topic: str) -> bool:
        """Add without logging. Returns True if new."""
        topic = topic.strip().lower()
        if not topic or len(topic) > 200:
            return False
        if topic in self._boundaries:
            return False
        self._boundaries.append(topic)
        return True

    def add_boundary(self, topic: str) -> bool:
        """Add a privacy boundary. Returns True if new."""
        added = self._add_internal(topic)
        if added:
            logger.info("[PrivacyGuard] Boundary added: %s", topic.strip().lower())
        return added

    def remove_boundary(self, topic: str) -> bool:
        """Remove a privacy boundary. Returns True if found."""
        topic = topic.strip().lower()
        if topic in self._boundaries:
            self._boundaries.remove(topic)
            logger.info("[PrivacyGuard] Boundary removed: %s", topic)
            return True
        return False

    def get_boundaries(self) -> List[str]:
        """Return all boundaries."""
        return list(self._boundaries)

    def is_allowed(self, text: str) -> bool:
        """
        Check if text is allowed (not touching any boundary).

        Returns True if text does NOT match any boundary.
        Returns False if text matches a boundary (blocked).
        """
        if not self._boundaries:
            return True
        text_lower = text.strip().lower()
        for boundary in self._boundaries:
            if boundary in text_lower:
                return False
        return True

    def to_list(self) -> List[str]:
        """Serialize for persistence."""
        return list(self._boundaries)

    @classmethod
    def from_list(cls, boundaries: List[str]) -> "PrivacyGuard":
        """Deserialize from persistence."""
        return cls(boundaries=boundaries)
