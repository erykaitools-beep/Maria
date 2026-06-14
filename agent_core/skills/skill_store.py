"""Skill storage layer.

Disk layout (per docs/SKILLS_DESIGN.md):
    meta_data/skills/
      index.jsonl                   # L0 catalog (derived from SKILL.md files)
      <skill_id>/
        SKILL.md                    # L1 full content (single source of truth)
        examples/                   # L2 optional
      archive/                      # archived skills (rollback path)
        <timestamp>/<skill_id>/

ADR-001 pattern: SKILL.md files are source of truth, index.jsonl is derived
cache rebuilt on load() / save_skill().
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from agent_core.skills.skill_model import (
    Skill,
    SkillStatus,
    parse_skill_md,
    skill_to_md,
)

logger = logging.getLogger(__name__)


class SkillStore:
    """Persistent store for Skill artifacts.

    Thread-safe via an internal lock on mutating operations. Read operations
    return snapshots (lists), so callers can iterate without holding the lock.
    """

    INDEX_FILE = "index.jsonl"
    SKILL_FILENAME = "SKILL.md"
    ARCHIVE_DIR = "archive"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self._skills: Dict[str, Skill] = {}
        self._loaded = False

    # -----------------------------------------------------------------
    # Load / persist
    # -----------------------------------------------------------------

    def load(self) -> int:
        """Load all SKILL.md files from disk. Returns count loaded.

        Builds in-memory catalog. Idempotent - subsequent calls reload
        from disk (useful after external edits).
        """
        with self._lock:
            self._skills.clear()
            if not self.root.exists():
                self._loaded = True
                return 0
            count = 0
            for skill_dir in sorted(self.root.iterdir()):
                if not skill_dir.is_dir():
                    continue
                if skill_dir.name == self.ARCHIVE_DIR:
                    continue
                skill_md = skill_dir / self.SKILL_FILENAME
                if not skill_md.exists():
                    continue
                try:
                    text = skill_md.read_text(encoding="utf-8")
                    skill = parse_skill_md(
                        text, skill_id=skill_dir.name, source_path=skill_md
                    )
                    self._skills[skill.skill_id] = skill
                    count += 1
                except Exception as e:
                    logger.warning(
                        "Skipping malformed skill %s: %s", skill_dir.name, e
                    )
            self._loaded = True
            self._rebuild_index()
            return count

    def save_skill(self, skill: Skill) -> Path:
        """Persist a single Skill. Creates directory if missing.

        Updates frontmatter.updated_at to now. Rebuilds index.jsonl.
        Returns the path to the written SKILL.md.
        """
        with self._lock:
            skill_dir = self.root / skill.skill_id
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill.frontmatter.updated_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            md_text = skill_to_md(skill)
            skill_md = skill_dir / self.SKILL_FILENAME
            skill_md.write_text(md_text, encoding="utf-8")
            skill.source_path = skill_md
            self._skills[skill.skill_id] = skill
            self._rebuild_index()
            return skill_md

    def archive_skill(self, skill_id: str) -> Optional[Path]:
        """Move a skill to archive/<timestamp>/. Returns archived path.

        Sets status=ARCHIVED in frontmatter before moving. Returns None if
        skill not found.
        """
        with self._lock:
            skill = self._skills.get(skill_id)
            if skill is None:
                return None
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive_root = self.root / self.ARCHIVE_DIR / ts
            archive_root.mkdir(parents=True, exist_ok=True)
            src = self.root / skill_id
            dst = archive_root / skill_id

            # Update status before move so the archived copy reflects archived state
            skill.frontmatter.status = SkillStatus.ARCHIVED
            skill.frontmatter.updated_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            (src / self.SKILL_FILENAME).write_text(
                skill_to_md(skill), encoding="utf-8"
            )

            shutil.move(str(src), str(dst))
            del self._skills[skill_id]
            self._rebuild_index()
            return dst

    # -----------------------------------------------------------------
    # Query
    # -----------------------------------------------------------------

    def get(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by id. None if not found."""
        with self._lock:
            return self._skills.get(skill_id)

    def list_all(self) -> List[Skill]:
        """All known skills (any status)."""
        with self._lock:
            return list(self._skills.values())

    def list_by_status(self, status: SkillStatus) -> List[Skill]:
        """All skills with a given status."""
        with self._lock:
            return [s for s in self._skills.values() if s.frontmatter.status == status]

    def list_active(self) -> List[Skill]:
        """SANDBOX + PRODUCTION skills (planner-usable)."""
        with self._lock:
            return [s for s in self._skills.values() if s.is_active]

    def l0_catalog(self) -> List[dict]:
        """Return L0 catalog entries (compact, for planner injection).

        Each entry ~200 tokens equivalent. Use for "Maria knows this skill
        exists" without paying the cost of loading full SKILL.md body.
        """
        with self._lock:
            return [s.to_l0_dict() for s in self._skills.values()]

    def exists(self, skill_id: str) -> bool:
        with self._lock:
            return skill_id in self._skills

    def count(self) -> int:
        with self._lock:
            return len(self._skills)

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _rebuild_index(self) -> None:
        """Rewrite index.jsonl from in-memory state. Caller holds the lock."""
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
        index_path = self.root / self.INDEX_FILE
        lines = [json.dumps(s.to_l0_dict(), ensure_ascii=False) for s in self._skills.values()]
        index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
