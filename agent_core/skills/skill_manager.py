"""Skill lifecycle manager - create_draft / patch / promote / archive.

Enforces Maria-style governance over Skills (Hermes-inspired but gated):
- DRAFT -> SANDBOX -> PRODUCTION -> ARCHIVED
- Every status transition requires explicit human gate via promote() /
  demote() / archive_skill() calls. NO autonomous promotion in Phase 1.
- audit_trail entries logged via callback (Phase 2 wires to bulletin/telegram).

See docs/SKILLS_DESIGN.md.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from agent_core.skills.skill_model import (
    Skill,
    SkillFrontmatter,
    SkillStatus,
    new_skill_id,
)
from agent_core.skills.schema import (
    validate_frontmatter,
    validate_sections,
    SkillValidationError,
)
from agent_core.skills.skill_store import SkillStore

logger = logging.getLogger(__name__)


# Allowed lifecycle transitions. Every transition requires explicit call.
_ALLOWED_TRANSITIONS = {
    (SkillStatus.DRAFT, SkillStatus.SANDBOX),
    (SkillStatus.SANDBOX, SkillStatus.PRODUCTION),
    (SkillStatus.SANDBOX, SkillStatus.DRAFT),       # demote
    (SkillStatus.PRODUCTION, SkillStatus.SANDBOX),  # demote
    (SkillStatus.DRAFT, SkillStatus.ARCHIVED),
    (SkillStatus.SANDBOX, SkillStatus.ARCHIVED),
    (SkillStatus.PRODUCTION, SkillStatus.ARCHIVED),
}


class SkillManager:
    """Lifecycle controller for Skills. Wraps SkillStore with policy."""

    def __init__(
        self,
        store: SkillStore,
        audit_callback: Optional[Callable[[str, Dict], None]] = None,
    ) -> None:
        self.store = store
        # audit_callback(event_type, payload) - Phase 2 hooks here for
        # bulletin/telegram notify. None = silent (test default).
        self.audit_callback = audit_callback

    # -----------------------------------------------------------------
    # Create
    # -----------------------------------------------------------------

    def create_draft(
        self,
        name: str,
        description: str,
        sections: Dict[str, str],
        created_by: str = "manual",
        source_episode_ids: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        platforms: Optional[List[str]] = None,
        trigger_count: int = 0,
    ) -> Skill:
        """Create a new DRAFT skill. Validates schema before persisting.

        Raises SkillValidationError if frontmatter or sections fail validation.
        """
        fm = SkillFrontmatter(
            name=name,
            description=description,
            status=SkillStatus.DRAFT,
            created_by=created_by,
            source_episode_ids=list(source_episode_ids or []),
            tags=list(tags or []),
            platforms=list(platforms or ["maria"]),
            trigger_count=trigger_count,
        )

        # Validate frontmatter (raises on error)
        validate_frontmatter(fm.to_dict(), strict=True)
        # Validate sections (raises on error)
        validate_sections(sections, strict=True)

        skill_id = new_skill_id(name)
        skill = Skill(
            skill_id=skill_id,
            frontmatter=fm,
            sections=dict(sections),
        )
        self.store.save_skill(skill)
        self._audit("skill_created", {
            "skill_id": skill_id,
            "name": name,
            "status": SkillStatus.DRAFT.value,
            "created_by": created_by,
        })
        return skill

    # -----------------------------------------------------------------
    # Mutate
    # -----------------------------------------------------------------

    def patch(
        self,
        skill_id: str,
        sections_update: Optional[Dict[str, str]] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        bump_version: bool = True,
    ) -> Skill:
        """Patch sections / description / tags. Bumps version by default.

        Status NOT mutated here - use promote/demote/archive for transitions.
        Raises ValueError if skill not found, SkillValidationError if patched
        skill fails validation.
        """
        skill = self.store.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")

        if description is not None:
            skill.frontmatter.description = description
        if tags is not None:
            skill.frontmatter.tags = list(tags)
        if sections_update:
            new_sections = dict(skill.sections)
            new_sections.update(sections_update)
            skill.sections = new_sections

        if bump_version:
            skill.frontmatter.version += 1

        validate_frontmatter(skill.frontmatter.to_dict(), strict=True)
        validate_sections(skill.sections, strict=True)

        self.store.save_skill(skill)
        self._audit("skill_patched", {
            "skill_id": skill_id,
            "new_version": skill.frontmatter.version,
        })
        return skill

    # -----------------------------------------------------------------
    # Transitions (human-gated in Phase 1 - caller proves intent)
    # -----------------------------------------------------------------

    def promote(self, skill_id: str, approved_by: str) -> Skill:
        """Promote skill one step up the lifecycle. DRAFT->SANDBOX or
        SANDBOX->PRODUCTION. Raises ValueError on illegal transition.

        approved_by is recorded in audit; required to be non-empty (proves
        a human authorized it, not an autonomous loop).
        """
        if not approved_by or not approved_by.strip():
            raise ValueError("promote() requires non-empty approved_by")
        skill = self._must_get(skill_id)
        current = skill.frontmatter.status
        if current == SkillStatus.DRAFT:
            target = SkillStatus.SANDBOX
        elif current == SkillStatus.SANDBOX:
            target = SkillStatus.PRODUCTION
        else:
            raise ValueError(
                f"Cannot promote from {current.value} (only DRAFT or SANDBOX)"
            )
        return self._transition(skill, target, approved_by, "promote")

    def demote(self, skill_id: str, approved_by: str, reason: str = "") -> Skill:
        """Demote skill one step down. PRODUCTION->SANDBOX or SANDBOX->DRAFT.

        Used when a promoted skill misbehaves and needs to go back to a
        tighter gate without archiving.
        """
        if not approved_by or not approved_by.strip():
            raise ValueError("demote() requires non-empty approved_by")
        skill = self._must_get(skill_id)
        current = skill.frontmatter.status
        if current == SkillStatus.PRODUCTION:
            target = SkillStatus.SANDBOX
        elif current == SkillStatus.SANDBOX:
            target = SkillStatus.DRAFT
        else:
            raise ValueError(
                f"Cannot demote from {current.value} (only PRODUCTION or SANDBOX)"
            )
        return self._transition(skill, target, approved_by, "demote", reason=reason)

    def archive(self, skill_id: str, approved_by: str, reason: str = "") -> Path:
        """Archive skill (any status -> ARCHIVED). Moves to archive/<ts>/.

        Returns archived path. Caller (e.g. CLI) can later restore from there.
        """
        if not approved_by or not approved_by.strip():
            raise ValueError("archive() requires non-empty approved_by")
        skill = self._must_get(skill_id)
        old_status = skill.frontmatter.status
        archived_path = self.store.archive_skill(skill_id)
        if archived_path is None:
            raise ValueError(f"Archive failed for {skill_id}")
        self._audit("skill_archived", {
            "skill_id": skill_id,
            "name": skill.frontmatter.name,
            "from_status": old_status.value,
            "approved_by": approved_by,
            "reason": reason,
            "archived_path": str(archived_path),
        })
        return archived_path

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _must_get(self, skill_id: str) -> Skill:
        skill = self.store.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")
        return skill

    def _transition(
        self,
        skill: Skill,
        target: SkillStatus,
        approved_by: str,
        kind: str,
        reason: str = "",
    ) -> Skill:
        current = skill.frontmatter.status
        if (current, target) not in _ALLOWED_TRANSITIONS:
            raise ValueError(
                f"Illegal transition: {current.value} -> {target.value}"
            )
        skill.frontmatter.status = target
        self.store.save_skill(skill)
        self._audit(f"skill_{kind}", {
            "skill_id": skill.skill_id,
            "name": skill.frontmatter.name,
            "from_status": current.value,
            "to_status": target.value,
            "approved_by": approved_by,
            "reason": reason,
        })
        return skill

    def _audit(self, event_type: str, payload: Dict) -> None:
        if self.audit_callback is not None:
            try:
                self.audit_callback(event_type, payload)
            except Exception as e:
                logger.warning("audit_callback failed for %s: %s", event_type, e)
