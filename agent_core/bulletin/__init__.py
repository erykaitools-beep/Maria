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
from agent_core.bulletin.knowledge_auditor import (
    KnowledgeAuditor,
    AuditReport,
    KnowledgeGap,
    GapType,
)
from agent_core.bulletin.gap_planner import (
    GapPlanner,
    GapPlan,
    GapAction,
)
from agent_core.bulletin.expert_bridge import (
    ExpertBridge,
    ExpertResponse,
)

__all__ = [
    "BulletinEntry",
    "EntryType",
    "EntryStatus",
    "BulletinStore",
    "KnowledgeAuditor",
    "AuditReport",
    "KnowledgeGap",
    "GapType",
    "GapPlanner",
    "GapPlan",
    "GapAction",
    "ExpertBridge",
    "ExpertResponse",
]
