"""Skills as artifact - procedural memory module.

STATUS (2026-05-31): LIBRARY (1.0-backlog) — zamrożone. Kompletny core
(data model + storage + manager + schema) + testy, ale NIE wired do tick:
`teacher/skill_extractor.py` importuje moduł, lecz extractor nie jest wołany
z pętli planner/tick (0 reachable z daemon spine). Nie kasować — wróci gdy
1.0 da dane do ekstrakcji skilli. Zob. docs/SYSTEM_STATUS.md.

Hermes-inspired (agentskills.io compatible) but Maria-gated:
sandbox-first promote() flow, human approval at every status transition.

Phase 1 (2026-05-15) shipped core data model + storage + manager.
Phase 2/3 (teacher extraction, planner integration, sandbox K2) NOT wired.

See docs/SKILLS_DESIGN.md for full architecture.
"""

from agent_core.skills.skill_model import (
    Skill,
    SkillFrontmatter,
    SkillStatus,
    parse_skill_md,
    skill_to_md,
)
from agent_core.skills.skill_store import SkillStore
from agent_core.skills.skill_manager import SkillManager
from agent_core.skills.schema import (
    validate_frontmatter,
    SkillValidationError,
    REQUIRED_SECTIONS,
)

__all__ = [
    "Skill",
    "SkillFrontmatter",
    "SkillStatus",
    "parse_skill_md",
    "skill_to_md",
    "SkillStore",
    "SkillManager",
    "validate_frontmatter",
    "SkillValidationError",
    "REQUIRED_SECTIONS",
]
