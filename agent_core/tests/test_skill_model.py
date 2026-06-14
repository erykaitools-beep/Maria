"""Tests for skill_model: dataclass shape + SKILL.md parser/serializer."""

import pytest

from agent_core.skills.skill_model import (
    Skill,
    SkillFrontmatter,
    SkillStatus,
    parse_skill_md,
    skill_to_md,
    new_skill_id,
    _parse_simple_yaml,
    _parse_md_sections,
)


# =========================================================================
# 1. SkillFrontmatter dataclass
# =========================================================================


class TestSkillFrontmatter:
    def test_defaults(self):
        fm = SkillFrontmatter(name="test-skill", description="a test")
        assert fm.name == "test-skill"
        assert fm.version == 1
        assert fm.status == SkillStatus.DRAFT
        assert fm.platforms == ["maria"]
        assert fm.created_at  # auto-populated
        assert fm.updated_at == fm.created_at

    def test_status_string_coerced_to_enum(self):
        fm = SkillFrontmatter(
            name="x", description="d", status="sandbox"  # type: ignore[arg-type]
        )
        assert fm.status == SkillStatus.SANDBOX

    def test_to_dict_serializes_status_as_string(self):
        fm = SkillFrontmatter(
            name="x", description="d", status=SkillStatus.PRODUCTION
        )
        d = fm.to_dict()
        assert d["status"] == "production"

    def test_from_dict_roundtrip(self):
        original = SkillFrontmatter(
            name="abc", description="hi", status=SkillStatus.SANDBOX, tags=["a", "b"]
        )
        roundtrip = SkillFrontmatter.from_dict(original.to_dict())
        assert roundtrip.name == original.name
        assert roundtrip.status == original.status
        assert roundtrip.tags == original.tags


# =========================================================================
# 2. Skill dataclass properties
# =========================================================================


class TestSkill:
    def test_is_active_draft_no(self):
        s = Skill(
            skill_id="sid",
            frontmatter=SkillFrontmatter(name="n", description="d", status=SkillStatus.DRAFT),
        )
        assert s.is_active is False
        assert s.is_production is False

    def test_is_active_sandbox_yes(self):
        s = Skill(
            skill_id="sid",
            frontmatter=SkillFrontmatter(name="n", description="d", status=SkillStatus.SANDBOX),
        )
        assert s.is_active is True
        assert s.is_production is False

    def test_is_production(self):
        s = Skill(
            skill_id="sid",
            frontmatter=SkillFrontmatter(
                name="n", description="d", status=SkillStatus.PRODUCTION
            ),
        )
        assert s.is_active is True
        assert s.is_production is True

    def test_l0_dict_compact_keys(self):
        s = Skill(
            skill_id="sid-1",
            frontmatter=SkillFrontmatter(
                name="fetch-rss", description="rss flow", tags=["fetch"], trigger_count=7
            ),
        )
        l0 = s.to_l0_dict()
        assert set(l0.keys()) == {
            "skill_id", "name", "description", "version",
            "status", "tags", "trigger_count",
        }
        # No body / sections leak into L0
        assert "sections" not in l0


# =========================================================================
# 3. Simple YAML subset parser
# =========================================================================


class TestSimpleYAML:
    def test_scalars(self):
        out = _parse_simple_yaml("name: foo\nversion: 3\nactive: true")
        assert out == {"name": "foo", "version": 3, "active": True}

    def test_quoted_string(self):
        out = _parse_simple_yaml('name: "with spaces"')
        assert out["name"] == "with spaces"

    def test_block_list(self):
        text = "tags:\n  - a\n  - b\n  - c"
        out = _parse_simple_yaml(text)
        assert out == {"tags": ["a", "b", "c"]}

    def test_inline_list(self):
        out = _parse_simple_yaml("tags: [x, y, z]")
        assert out == {"tags": ["x", "y", "z"]}

    def test_mixed(self):
        text = """name: my-skill
version: 2
status: sandbox
tags:
  - learning
  - fetch
trigger_count: 5
"""
        out = _parse_simple_yaml(text)
        assert out["name"] == "my-skill"
        assert out["version"] == 2
        assert out["tags"] == ["learning", "fetch"]
        assert out["trigger_count"] == 5


# =========================================================================
# 4. Markdown section splitter
# =========================================================================


class TestSectionSplitter:
    def test_basic_sections(self):
        body = """
## When to Use

When user asks X.

## Procedure

1. Step one
2. Step two

## Verification

It works if Y.
"""
        sections = _parse_md_sections(body)
        assert "When to Use" in sections
        assert "Procedure" in sections
        assert "Verification" in sections
        assert "Step one" in sections["Procedure"]

    def test_no_sections(self):
        assert _parse_md_sections("just text") == {}


# =========================================================================
# 5. parse_skill_md / skill_to_md round-trip
# =========================================================================


SAMPLE_SKILL_MD = """---
name: fetch-and-exam
description: Fetch fresh material and immediately exam yourself on it
version: 1
status: draft
platforms:
  - maria
created_at: 2026-05-15T19:30:00+00:00
updated_at: 2026-05-15T19:30:00+00:00
created_by: manual
tags:
  - learning
  - fetch
trigger_count: 0
---

## When to Use

After a fetch action returns new material on a topic Maria wants to learn.

## Procedure

1. Verify fetch produced at least one knowledge_index entry.
2. Trigger exam_agent on the new topic.
3. Read result and update bulletin if score < 0.7.

## Pitfalls

- Don't run if knowledge_index entry has chunks_learned=0 (no content yet).
- Don't run during QUIET window (22-07 Berlin).

## Verification

action_audit.jsonl contains a successful 'exam' action with the fetched
file_id and final_score >= 0.7.
"""


class TestRoundTrip:
    def test_parse_skill_md_basic(self):
        skill = parse_skill_md(SAMPLE_SKILL_MD, skill_id="fetch-and-exam-test")
        assert skill.skill_id == "fetch-and-exam-test"
        assert skill.frontmatter.name == "fetch-and-exam"
        assert skill.frontmatter.status == SkillStatus.DRAFT
        assert "learning" in skill.frontmatter.tags
        assert "When to Use" in skill.sections
        assert "Procedure" in skill.sections
        assert "Verification" in skill.sections
        assert "Pitfalls" in skill.sections

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError, match="frontmatter"):
            parse_skill_md("# Just markdown, no frontmatter")

    def test_roundtrip(self):
        skill = parse_skill_md(SAMPLE_SKILL_MD, skill_id="x")
        rendered = skill_to_md(skill)
        skill2 = parse_skill_md(rendered, skill_id="x")
        assert skill2.frontmatter.name == skill.frontmatter.name
        assert skill2.frontmatter.status == skill.frontmatter.status
        assert skill2.frontmatter.tags == skill.frontmatter.tags
        # All sections preserved
        for sec in skill.sections:
            assert sec in skill2.sections


# =========================================================================
# 6. new_skill_id
# =========================================================================


class TestSkillIdGen:
    def test_name_based_id(self):
        sid = new_skill_id("my-cool-skill")
        assert sid.startswith("my-cool-skill-")
        assert len(sid) > len("my-cool-skill-")

    def test_fallback_uuid_when_invalid_name(self):
        sid = new_skill_id("UPPERCASE-INVALID")
        assert sid.startswith("skill-")

    def test_fallback_uuid_when_no_name(self):
        sid = new_skill_id(None)
        assert sid.startswith("skill-")
