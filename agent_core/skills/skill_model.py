"""Skill data model + SKILL.md parser.

Skill = procedural memory artifact, formatted as Markdown with YAML
frontmatter. Compatible with agentskills.io (cross-agent portability).

Lifecycle: DRAFT -> SANDBOX -> PRODUCTION -> ARCHIVED. Each transition
requires human gate (Maria-style, ADR-010/011).

See docs/SKILLS_DESIGN.md for design rationale.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums + constants
# ---------------------------------------------------------------------------


class SkillStatus(str, Enum):
    """Skill lifecycle state. Each transition requires human gate."""

    DRAFT = "draft"
    SANDBOX = "sandbox"
    PRODUCTION = "production"
    ARCHIVED = "archived"


REQUIRED_SECTIONS = ("When to Use", "Procedure", "Verification")
OPTIONAL_SECTIONS = ("Pitfalls",)

_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
_NAME_MAX = 64
_DESC_MAX = 140


# ---------------------------------------------------------------------------
# Frontmatter dataclass
# ---------------------------------------------------------------------------


@dataclass
class SkillFrontmatter:
    """YAML frontmatter of a SKILL.md file. L0 disclosure layer."""

    name: str
    description: str
    version: int = 1
    status: SkillStatus = SkillStatus.DRAFT
    platforms: List[str] = field(default_factory=lambda: ["maria"])
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "manual"
    source_episode_ids: List[str] = field(default_factory=list)
    trigger_count: int = 0
    tags: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at
        # Normalize status (str -> enum) - YAML may give us a plain string
        if isinstance(self.status, str):
            self.status = SkillStatus(self.status)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict suitable for YAML dump."""
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, SkillStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SkillFrontmatter":
        """Deserialize from parsed YAML dict. Tolerant of missing fields."""
        return cls(
            name=d["name"],
            description=d["description"],
            version=int(d.get("version", 1)),
            status=SkillStatus(d.get("status", "draft")),
            platforms=list(d.get("platforms", ["maria"])),
            created_at=d.get("created_at", "") or _now_iso(),
            updated_at=d.get("updated_at", "") or _now_iso(),
            created_by=d.get("created_by", "manual"),
            source_episode_ids=list(d.get("source_episode_ids", [])),
            trigger_count=int(d.get("trigger_count", 0)),
            tags=list(d.get("tags", [])),
        )


# ---------------------------------------------------------------------------
# Skill (full L1 model)
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    """Full skill - frontmatter (L0) + sections body (L1).

    skill_id is a derived identifier (slug or uuid) used in filesystem paths
    and L0 catalog. NOT the same as frontmatter.name - skill_id is stable
    across renames; name is human-readable and may change in patches.
    """

    skill_id: str
    frontmatter: SkillFrontmatter
    sections: Dict[str, str] = field(default_factory=dict)
    # Path to SKILL.md on disk, optional (None for in-memory drafts).
    source_path: Optional[Path] = None

    @property
    def is_active(self) -> bool:
        """True if skill is usable by planner (SANDBOX or PRODUCTION)."""
        return self.frontmatter.status in (
            SkillStatus.SANDBOX,
            SkillStatus.PRODUCTION,
        )

    @property
    def is_production(self) -> bool:
        return self.frontmatter.status == SkillStatus.PRODUCTION

    def to_l0_dict(self) -> Dict[str, Any]:
        """Compact L0 catalog entry. ~200 tokens equivalent."""
        return {
            "skill_id": self.skill_id,
            "name": self.frontmatter.name,
            "description": self.frontmatter.description,
            "version": self.frontmatter.version,
            "status": self.frontmatter.status.value,
            "tags": list(self.frontmatter.tags),
            "trigger_count": self.frontmatter.trigger_count,
        }


# ---------------------------------------------------------------------------
# Parser (SKILL.md -> Skill) and serializer (Skill -> SKILL.md)
# ---------------------------------------------------------------------------


_FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL
)


def parse_skill_md(content: str, skill_id: Optional[str] = None,
                   source_path: Optional[Path] = None) -> Skill:
    """Parse a SKILL.md file into a Skill instance.

    Raises ValueError if frontmatter is missing/malformed or required
    sections are absent. Use schema.validate_frontmatter() before this
    for richer error messages.
    """
    m = _FRONTMATTER_PATTERN.match(content)
    if not m:
        raise ValueError("SKILL.md missing YAML frontmatter (--- ... ---)")
    yaml_text, body = m.group(1), m.group(2)
    fm_dict = _parse_simple_yaml(yaml_text)
    fm = SkillFrontmatter.from_dict(fm_dict)

    sections = _parse_md_sections(body)

    if skill_id is None:
        skill_id = fm.name  # fallback - prefer to pass explicit skill_id

    return Skill(
        skill_id=skill_id,
        frontmatter=fm,
        sections=sections,
        source_path=source_path,
    )


def skill_to_md(skill: Skill) -> str:
    """Serialize a Skill back to SKILL.md text."""
    fm_dict = skill.frontmatter.to_dict()
    yaml_text = _dump_simple_yaml(fm_dict)
    parts = [f"---\n{yaml_text}---\n"]

    section_order = list(REQUIRED_SECTIONS) + list(OPTIONAL_SECTIONS)
    written = set()
    for sec in section_order:
        if sec in skill.sections:
            parts.append(f"\n## {sec}\n\n{skill.sections[sec].strip()}\n")
            written.add(sec)
    # Append any non-canonical sections preserved
    for sec, body in skill.sections.items():
        if sec not in written:
            parts.append(f"\n## {sec}\n\n{body.strip()}\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Helpers - simple YAML (subset - no external dependency)
# ---------------------------------------------------------------------------


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Parse a flat-ish YAML subset: key: value, list items as `- item`.

    Only handles what we use in SKILL.md frontmatter. NOT a general YAML
    parser. Sufficient for: scalars (str/int/bool), lists of strings,
    ISO-8601 timestamps (kept as string).
    """
    out: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[List[str]] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # List continuation: "  - item"
        stripped = line.lstrip()
        if stripped.startswith("- ") and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue
        # New key
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                current_key = key
                current_list = []
                out[key] = current_list
                continue
            # Inline list: [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                items = [
                    s.strip().strip('"').strip("'")
                    for s in val[1:-1].split(",")
                    if s.strip()
                ]
                out[key] = items
                current_list = None
                continue
            # Scalar
            out[key] = _coerce_scalar(val)
            current_list = None
    return out


def _coerce_scalar(val: str) -> Any:
    """Coerce a YAML scalar string to int / bool / str."""
    # Strip surrounding quotes
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        return val[1:-1]
    # Bool
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    # Int
    try:
        return int(val)
    except ValueError:
        pass
    return val


def _dump_simple_yaml(d: Dict[str, Any]) -> str:
    """Dump dict to YAML subset matching _parse_simple_yaml shape."""
    lines: List[str] = []
    for k, v in d.items():
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        else:
            s = str(v)
            # Quote if contains colon or starts with special char
            if ":" in s or s.startswith(("[", "{", "-", "?", "!")):
                s = f'"{s}"'
            lines.append(f"{k}: {s}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers - section splitter
# ---------------------------------------------------------------------------


_SECTION_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _parse_md_sections(body: str) -> Dict[str, str]:
    """Split markdown body by `## Header` into {header: content}."""
    out: Dict[str, str] = {}
    headers = list(_SECTION_HEADER.finditer(body))
    for i, m in enumerate(headers):
        header = m.group(1).strip()
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        out[header] = body[start:end].strip()
    return out


def _now_iso() -> str:
    """ISO-8601 timestamp in UTC for SKILL.md frontmatter."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_skill_id(name: Optional[str] = None) -> str:
    """Generate a stable skill_id. Prefers name-based slug, falls back uuid."""
    if name and _NAME_PATTERN.match(name) and len(name) <= _NAME_MAX:
        # Append short uuid suffix to ensure uniqueness across renames
        return f"{name}-{uuid.uuid4().hex[:8]}"
    return f"skill-{uuid.uuid4().hex[:12]}"
