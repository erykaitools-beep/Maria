"""
Cognitive Bulletin Board - shared registry of Maria's cognitive needs.

Pre-Learn Audit Layer: separates topic (cognitive task) from material
(learning input). Modules post needs, planner reads and acts on them.

Phase 1: visibility (NEED_MATERIAL, READY_TO_LEARN, NEED_TEST,
NEED_REVIEW, WAITING_HUMAN).
"""

from agent_core.bulletin.bulletin_model import (
    BulletinEntry,
    EntryType,
    EntryStatus,
)
from agent_core.bulletin.bulletin_store import BulletinStore

__all__ = [
    "BulletinEntry",
    "EntryType",
    "EntryStatus",
    "BulletinStore",
]
