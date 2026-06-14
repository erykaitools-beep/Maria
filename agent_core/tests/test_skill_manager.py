"""Tests for SkillManager: lifecycle gates + audit callback."""

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from agent_core.skills.skill_model import SkillStatus
from agent_core.skills.skill_store import SkillStore
from agent_core.skills.skill_manager import SkillManager
from agent_core.skills.schema import SkillValidationError


@pytest.fixture
def manager(tmp_path: Path) -> Tuple[SkillManager, List[Tuple[str, Dict[str, Any]]]]:
    store = SkillStore(root=tmp_path / "skills")
    store.load()
    audit_log: List[Tuple[str, Dict[str, Any]]] = []

    def callback(event_type: str, payload: Dict[str, Any]) -> None:
        audit_log.append((event_type, payload))

    return SkillManager(store=store, audit_callback=callback), audit_log


VALID_SECTIONS = {
    "When to Use": "When something happens.",
    "Procedure": "1. Do thing\n2. Do another",
    "Verification": "Check the output.",
}


# =========================================================================
# 1. create_draft
# =========================================================================


class TestCreateDraft:
    def test_create_valid_skill(self, manager):
        mgr, audit = manager
        skill = mgr.create_draft(
            name="test-skill",
            description="A test skill",
            sections=VALID_SECTIONS,
            created_by="test",
            tags=["test"],
        )
        assert skill.frontmatter.status == SkillStatus.DRAFT
        assert skill.frontmatter.name == "test-skill"
        assert skill.frontmatter.created_by == "test"
        assert mgr.store.exists(skill.skill_id)

    def test_create_emits_audit(self, manager):
        mgr, audit = manager
        mgr.create_draft(
            name="audited", description="audit me", sections=VALID_SECTIONS
        )
        assert len(audit) == 1
        event, payload = audit[0]
        assert event == "skill_created"
        assert payload["name"] == "audited"
        assert payload["status"] == "draft"

    def test_invalid_name_rejected(self, manager):
        mgr, _ = manager
        with pytest.raises(SkillValidationError):
            mgr.create_draft(
                name="UPPERCASE-INVALID",
                description="x",
                sections=VALID_SECTIONS,
            )

    def test_missing_required_section_rejected(self, manager):
        mgr, _ = manager
        bad_sections = {
            "When to Use": "trigger",
            # Procedure missing
            "Verification": "verify",
        }
        with pytest.raises(SkillValidationError, match="Procedure"):
            mgr.create_draft(
                name="bad-skill",
                description="x",
                sections=bad_sections,
            )

    def test_too_long_description_rejected(self, manager):
        mgr, _ = manager
        with pytest.raises(SkillValidationError, match="description too long"):
            mgr.create_draft(
                name="x-skill",
                description="x" * 200,
                sections=VALID_SECTIONS,
            )


# =========================================================================
# 2. patch
# =========================================================================


class TestPatch:
    def test_patch_bumps_version(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="patch-target", description="d", sections=VALID_SECTIONS
        )
        original_version = skill.frontmatter.version
        patched = mgr.patch(
            skill.skill_id,
            sections_update={"Procedure": "1. New steps"},
        )
        assert patched.frontmatter.version == original_version + 1

    def test_patch_updates_section(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="s2", description="d", sections=VALID_SECTIONS
        )
        mgr.patch(
            skill.skill_id, sections_update={"Procedure": "new procedure"}
        )
        loaded = mgr.store.get(skill.skill_id)
        assert "new procedure" in loaded.sections["Procedure"]

    def test_patch_emits_audit(self, manager):
        mgr, audit = manager
        skill = mgr.create_draft(
            name="patch-audit", description="d", sections=VALID_SECTIONS
        )
        mgr.patch(skill.skill_id, description="new desc")
        events = [e for e, _ in audit]
        assert "skill_patched" in events

    def test_patch_unknown_raises(self, manager):
        mgr, _ = manager
        with pytest.raises(ValueError, match="not found"):
            mgr.patch("nonexistent", description="x")

    def test_patch_no_bump_when_disabled(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="nobump", description="d", sections=VALID_SECTIONS
        )
        v = skill.frontmatter.version
        mgr.patch(skill.skill_id, description="x", bump_version=False)
        assert mgr.store.get(skill.skill_id).frontmatter.version == v


# =========================================================================
# 3. Promote (DRAFT -> SANDBOX -> PRODUCTION)
# =========================================================================


class TestPromote:
    def test_draft_to_sandbox(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="promo-1", description="d", sections=VALID_SECTIONS
        )
        promoted = mgr.promote(skill.skill_id, approved_by="eryk")
        assert promoted.frontmatter.status == SkillStatus.SANDBOX

    def test_sandbox_to_production(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="promo-2", description="d", sections=VALID_SECTIONS
        )
        mgr.promote(skill.skill_id, approved_by="eryk")
        mgr.promote(skill.skill_id, approved_by="eryk")
        assert mgr.store.get(skill.skill_id).frontmatter.status == SkillStatus.PRODUCTION

    def test_production_cannot_promote(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="topcap", description="d", sections=VALID_SECTIONS
        )
        mgr.promote(skill.skill_id, approved_by="eryk")
        mgr.promote(skill.skill_id, approved_by="eryk")
        with pytest.raises(ValueError, match="Cannot promote"):
            mgr.promote(skill.skill_id, approved_by="eryk")

    def test_promote_emits_audit_with_approver(self, manager):
        mgr, audit = manager
        skill = mgr.create_draft(
            name="promo-audit", description="d", sections=VALID_SECTIONS
        )
        mgr.promote(skill.skill_id, approved_by="eryk")
        promo_events = [p for e, p in audit if e == "skill_promote"]
        assert len(promo_events) == 1
        assert promo_events[0]["approved_by"] == "eryk"
        assert promo_events[0]["from_status"] == "draft"
        assert promo_events[0]["to_status"] == "sandbox"

    def test_promote_requires_approved_by(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="noapprove", description="d", sections=VALID_SECTIONS
        )
        with pytest.raises(ValueError, match="approved_by"):
            mgr.promote(skill.skill_id, approved_by="")
        with pytest.raises(ValueError, match="approved_by"):
            mgr.promote(skill.skill_id, approved_by="   ")


# =========================================================================
# 4. Demote (PRODUCTION -> SANDBOX -> DRAFT)
# =========================================================================


class TestDemote:
    def test_production_to_sandbox(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="demo-1", description="d", sections=VALID_SECTIONS
        )
        mgr.promote(skill.skill_id, approved_by="eryk")
        mgr.promote(skill.skill_id, approved_by="eryk")
        demoted = mgr.demote(skill.skill_id, approved_by="eryk", reason="misbehaving")
        assert demoted.frontmatter.status == SkillStatus.SANDBOX

    def test_sandbox_to_draft(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="demo-2", description="d", sections=VALID_SECTIONS
        )
        mgr.promote(skill.skill_id, approved_by="eryk")
        demoted = mgr.demote(skill.skill_id, approved_by="eryk")
        assert demoted.frontmatter.status == SkillStatus.DRAFT

    def test_draft_cannot_demote(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="bottomcap", description="d", sections=VALID_SECTIONS
        )
        with pytest.raises(ValueError, match="Cannot demote"):
            mgr.demote(skill.skill_id, approved_by="eryk")


# =========================================================================
# 5. Archive (any -> ARCHIVED)
# =========================================================================


class TestArchive:
    def test_archive_draft(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="arch-1", description="d", sections=VALID_SECTIONS
        )
        path = mgr.archive(skill.skill_id, approved_by="eryk", reason="unused")
        assert path.exists()
        assert not mgr.store.exists(skill.skill_id)

    def test_archive_production(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="arch-prod", description="d", sections=VALID_SECTIONS
        )
        mgr.promote(skill.skill_id, approved_by="eryk")
        mgr.promote(skill.skill_id, approved_by="eryk")
        path = mgr.archive(skill.skill_id, approved_by="eryk", reason="stale")
        assert path.exists()

    def test_archive_emits_audit(self, manager):
        mgr, audit = manager
        skill = mgr.create_draft(
            name="arch-audit", description="d", sections=VALID_SECTIONS
        )
        mgr.archive(skill.skill_id, approved_by="eryk", reason="test")
        events = [e for e, _ in audit]
        assert "skill_archived" in events

    def test_archive_requires_approved_by(self, manager):
        mgr, _ = manager
        skill = mgr.create_draft(
            name="archnoapp", description="d", sections=VALID_SECTIONS
        )
        with pytest.raises(ValueError, match="approved_by"):
            mgr.archive(skill.skill_id, approved_by="")

    def test_archive_unknown_raises(self, manager):
        mgr, _ = manager
        with pytest.raises(ValueError, match="not found"):
            mgr.archive("nonexistent", approved_by="eryk")


# =========================================================================
# 6. Audit callback isolation (callback exception doesn't break manager)
# =========================================================================


class TestAuditFailureIsolated:
    def test_failing_callback_does_not_break_create(self, tmp_path):
        store = SkillStore(root=tmp_path / "skills")
        store.load()

        def bad_callback(event_type, payload):
            raise RuntimeError("audit boom")

        mgr = SkillManager(store=store, audit_callback=bad_callback)
        # Should NOT raise despite callback failure
        skill = mgr.create_draft(
            name="resilient", description="d", sections=VALID_SECTIONS
        )
        assert mgr.store.exists(skill.skill_id)
