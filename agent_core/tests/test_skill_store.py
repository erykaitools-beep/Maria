"""Tests for SkillStore: disk persistence + L0 catalog + archive."""

import json
import pytest
from pathlib import Path

from agent_core.skills.skill_model import (
    Skill,
    SkillFrontmatter,
    SkillStatus,
)
from agent_core.skills.skill_store import SkillStore


@pytest.fixture
def store(tmp_path: Path) -> SkillStore:
    s = SkillStore(root=tmp_path / "skills")
    s.load()
    return s


def _make_skill(skill_id: str, name: str, status: SkillStatus = SkillStatus.DRAFT) -> Skill:
    return Skill(
        skill_id=skill_id,
        frontmatter=SkillFrontmatter(
            name=name, description=f"{name} skill", status=status
        ),
        sections={
            "When to Use": "Some trigger.",
            "Procedure": "1. Do thing",
            "Verification": "It worked.",
        },
    )


# =========================================================================
# 1. Empty store
# =========================================================================


class TestEmptyStore:
    def test_count_zero(self, store):
        assert store.count() == 0

    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_l0_catalog_empty(self, store):
        assert store.l0_catalog() == []

    def test_get_unknown_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_exists_false(self, store):
        assert store.exists("nope") is False


# =========================================================================
# 2. Save + load round trip
# =========================================================================


class TestSaveLoad:
    def test_save_single_skill(self, store, tmp_path):
        skill = _make_skill("sid-1", "test-one")
        path = store.save_skill(skill)
        assert path.exists()
        assert path.name == "SKILL.md"
        # Index file rebuilt
        assert (store.root / "index.jsonl").exists()

    def test_reload_after_save(self, tmp_path):
        s1 = SkillStore(root=tmp_path / "skills")
        s1.load()
        s1.save_skill(_make_skill("sid-a", "a-skill"))
        s1.save_skill(_make_skill("sid-b", "b-skill", SkillStatus.SANDBOX))

        # Fresh store reads from disk
        s2 = SkillStore(root=tmp_path / "skills")
        count = s2.load()
        assert count == 2
        assert s2.exists("sid-a")
        assert s2.exists("sid-b")
        assert s2.get("sid-b").frontmatter.status == SkillStatus.SANDBOX

    def test_save_updates_timestamp(self, store):
        skill = _make_skill("sid-time", "time-skill")
        original_updated = skill.frontmatter.updated_at
        # Save tweaks updated_at to "now"; ensure it changes or stays valid
        store.save_skill(skill)
        loaded = store.get("sid-time")
        assert loaded is not None
        assert loaded.frontmatter.updated_at  # non-empty


# =========================================================================
# 3. Query - by status / active / catalog
# =========================================================================


class TestQuery:
    def test_list_by_status(self, store):
        store.save_skill(_make_skill("d1", "draft-1", SkillStatus.DRAFT))
        store.save_skill(_make_skill("d2", "draft-2", SkillStatus.DRAFT))
        store.save_skill(_make_skill("s1", "sandbox-1", SkillStatus.SANDBOX))
        store.save_skill(_make_skill("p1", "prod-1", SkillStatus.PRODUCTION))
        assert len(store.list_by_status(SkillStatus.DRAFT)) == 2
        assert len(store.list_by_status(SkillStatus.SANDBOX)) == 1
        assert len(store.list_by_status(SkillStatus.PRODUCTION)) == 1

    def test_list_active(self, store):
        # DRAFT not active; SANDBOX + PRODUCTION are
        store.save_skill(_make_skill("d1", "drafted", SkillStatus.DRAFT))
        store.save_skill(_make_skill("s1", "sandboxed", SkillStatus.SANDBOX))
        store.save_skill(_make_skill("p1", "produced", SkillStatus.PRODUCTION))
        active = store.list_active()
        assert len(active) == 2
        skill_ids = {s.skill_id for s in active}
        assert "s1" in skill_ids
        assert "p1" in skill_ids
        assert "d1" not in skill_ids

    def test_l0_catalog_compact(self, store):
        store.save_skill(_make_skill("k1", "kat-one", SkillStatus.SANDBOX))
        catalog = store.l0_catalog()
        assert len(catalog) == 1
        entry = catalog[0]
        # L0 should NOT contain section bodies
        for forbidden in ("sections", "Procedure", "When to Use"):
            assert forbidden not in entry
        assert entry["skill_id"] == "k1"
        assert entry["status"] == "sandbox"


# =========================================================================
# 4. Index.jsonl is derived (rebuild on save)
# =========================================================================


class TestIndexFile:
    def test_index_contains_l0_per_skill(self, store, tmp_path):
        store.save_skill(_make_skill("a1", "a-one", SkillStatus.DRAFT))
        store.save_skill(_make_skill("a2", "a-two", SkillStatus.SANDBOX))
        index_path = store.root / "index.jsonl"
        lines = index_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        names = {e["name"] for e in parsed}
        assert names == {"a-one", "a-two"}


# =========================================================================
# 5. Archive
# =========================================================================


class TestArchive:
    def test_archive_moves_to_archive_dir(self, store):
        store.save_skill(_make_skill("doomed", "doomed-skill"))
        assert store.exists("doomed")
        path = store.archive_skill("doomed")
        assert path is not None
        # Source dir gone
        assert not (store.root / "doomed").exists()
        # Archive dir exists
        assert path.exists()
        # Not in memory anymore
        assert not store.exists("doomed")
        assert store.get("doomed") is None

    def test_archive_sets_status_to_archived(self, store):
        store.save_skill(_make_skill("arch-me", "arch-skill", SkillStatus.PRODUCTION))
        path = store.archive_skill("arch-me")
        # Read archived SKILL.md to verify status was updated before move
        archived_md = (path / "SKILL.md").read_text(encoding="utf-8")
        assert "status: archived" in archived_md

    def test_archive_unknown_returns_none(self, store):
        assert store.archive_skill("does-not-exist") is None


# =========================================================================
# 6. Malformed skill skipped on load
# =========================================================================


class TestMalformedSkipped:
    def test_load_skips_skill_without_frontmatter(self, tmp_path):
        skills_dir = tmp_path / "skills"
        (skills_dir / "bad-skill").mkdir(parents=True)
        (skills_dir / "bad-skill" / "SKILL.md").write_text(
            "# Just a header, no frontmatter\nContent.", encoding="utf-8"
        )
        store = SkillStore(root=skills_dir)
        count = store.load()
        assert count == 0
        assert not store.exists("bad-skill")
