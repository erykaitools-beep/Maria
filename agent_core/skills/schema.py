"""Skill schema validation - agentskills.io compatible JSON Schema.

Validates SkillFrontmatter dict + checks REQUIRED_SECTIONS in markdown body.
Pure-Python, no external JSON Schema library (would be overkill for a small
fixed schema).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from agent_core.skills.skill_model import (
    REQUIRED_SECTIONS,
    SkillStatus,
    _NAME_PATTERN,
    _NAME_MAX,
    _DESC_MAX,
)


class SkillValidationError(ValueError):
    """Raised when a Skill fails schema validation."""

    def __init__(self, errors: List[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


_VALID_STATUS = {s.value for s in SkillStatus}
_ISO_HINT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def validate_frontmatter(
    fm: Dict[str, Any], strict: bool = True
) -> Tuple[bool, List[str]]:
    """Validate a parsed YAML frontmatter dict against the skill schema.

    Returns (ok, errors). When strict=True raises SkillValidationError on
    any violation. When strict=False returns the list of errors instead.

    Required fields, types, value ranges (per docs/SKILLS_DESIGN.md):
    - name: lowercase-kebab, <=64 chars
    - description: <=140 chars
    - version: int >= 1
    - status: enum {draft, sandbox, production, archived}
    - created_at / updated_at: ISO-8601 prefix match
    - created_by: non-empty string
    """
    errors: List[str] = []

    def _check_required(field: str) -> bool:
        if field not in fm:
            errors.append(f"missing required field: {field}")
            return False
        return True

    # name
    if _check_required("name"):
        name = fm["name"]
        if not isinstance(name, str):
            errors.append("name must be a string")
        elif not _NAME_PATTERN.match(name):
            errors.append(
                f"name '{name}' must match [a-z0-9-]+ (lowercase kebab-case)"
            )
        elif len(name) > _NAME_MAX:
            errors.append(f"name too long: {len(name)} > {_NAME_MAX}")

    # description
    if _check_required("description"):
        desc = fm["description"]
        if not isinstance(desc, str):
            errors.append("description must be a string")
        elif len(desc) > _DESC_MAX:
            errors.append(
                f"description too long: {len(desc)} > {_DESC_MAX}"
            )
        elif not desc.strip():
            errors.append("description must not be empty")

    # version
    if "version" in fm:
        ver = fm["version"]
        if not isinstance(ver, int) or ver < 1:
            errors.append(f"version must be int >= 1, got {ver!r}")

    # status
    if _check_required("status"):
        status = fm["status"]
        if status not in _VALID_STATUS:
            errors.append(
                f"status must be one of {sorted(_VALID_STATUS)}, got {status!r}"
            )

    # timestamps
    for ts_field in ("created_at", "updated_at"):
        if ts_field in fm:
            ts = fm[ts_field]
            if not isinstance(ts, str) or not _ISO_HINT.match(ts):
                errors.append(
                    f"{ts_field} must be ISO-8601 string, got {ts!r}"
                )

    # created_by
    if "created_by" in fm:
        cb = fm["created_by"]
        if not isinstance(cb, str) or not cb.strip():
            errors.append("created_by must be a non-empty string")

    # platforms
    if "platforms" in fm:
        pl = fm["platforms"]
        if not isinstance(pl, list) or not all(isinstance(p, str) for p in pl):
            errors.append("platforms must be a list of strings")

    # source_episode_ids
    if "source_episode_ids" in fm:
        seids = fm["source_episode_ids"]
        if not isinstance(seids, list):
            errors.append("source_episode_ids must be a list")

    # trigger_count
    if "trigger_count" in fm:
        tc = fm["trigger_count"]
        if not isinstance(tc, int) or tc < 0:
            errors.append(
                f"trigger_count must be int >= 0, got {tc!r}"
            )

    ok = not errors
    if strict and not ok:
        raise SkillValidationError(errors)
    return ok, errors


def validate_sections(sections: Dict[str, str], strict: bool = True) -> Tuple[bool, List[str]]:
    """Validate that REQUIRED_SECTIONS are present and non-empty."""
    errors: List[str] = []
    for sec in REQUIRED_SECTIONS:
        if sec not in sections:
            errors.append(f"missing required section: ## {sec}")
        elif not sections[sec].strip():
            errors.append(f"required section '## {sec}' is empty")
    ok = not errors
    if strict and not ok:
        raise SkillValidationError(errors)
    return ok, errors
