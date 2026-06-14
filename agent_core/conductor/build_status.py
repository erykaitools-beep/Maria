"""
Conductor — Build status snapshot per project.

Where TaskQueue is the append log, BuildStatus is the rolled-up state
the operator looks at: which phase, what % done, what's blocking
progress, what's next. One status file holds all projects keyed by
project name.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "meta_data" / "market_build_status.json"
)


@dataclass
class BuildStatus:
    """Rolled-up project status — one snapshot per project."""

    project: str
    current_phase: str = ""
    progress_pct: float = 0.0   # 0.0 - 1.0 of total tasks done in project
    blockers: List[str] = field(default_factory=list)
    last_completed_task_id: Optional[str] = None
    next_task_id: Optional[str] = None
    pending_count: int = 0
    in_progress_count: int = 0
    done_count: int = 0
    blocked_count: int = 0
    total_count: int = 0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BuildStatus":
        return cls(
            project=d["project"],
            current_phase=d.get("current_phase", ""),
            progress_pct=float(d.get("progress_pct", 0.0)),
            blockers=list(d.get("blockers", [])),
            last_completed_task_id=d.get("last_completed_task_id"),
            next_task_id=d.get("next_task_id"),
            pending_count=int(d.get("pending_count", 0)),
            in_progress_count=int(d.get("in_progress_count", 0)),
            done_count=int(d.get("done_count", 0)),
            blocked_count=int(d.get("blocked_count", 0)),
            total_count=int(d.get("total_count", 0)),
            updated_at=float(d.get("updated_at", time.time())),
        )


class BuildStatusStore:
    """JSON-backed store keyed by project name.

    Whole-file rewrites on every save — fine because the file holds
    rolled-up snapshots, not history.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._cache: Optional[Dict[str, BuildStatus]] = None

    def _ensure_loaded(self) -> None:
        if self._cache is not None:
            return
        self._cache = {}
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                logger.warning("[CONDUCTOR] build_status.json malformed (not a dict)")
                return
            for project, payload in d.items():
                try:
                    self._cache[project] = BuildStatus.from_dict(payload)
                except (KeyError, ValueError) as e:
                    logger.warning(
                        "[CONDUCTOR] Skipping corrupted status for %s: %s",
                        project,
                        e,
                    )
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"[CONDUCTOR] Cannot read {self._path}: {e}")

    def _flush(self) -> None:
        assert self._cache is not None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {p: s.to_dict() for p, s in self._cache.items()}
            tmp = self._path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
        except OSError as e:
            logger.error(f"[CONDUCTOR] Cannot write {self._path}: {e}")

    def save(self, status: BuildStatus) -> None:
        self._ensure_loaded()
        assert self._cache is not None
        status.updated_at = time.time()
        self._cache[status.project] = status
        self._flush()

    def load(self, project: str) -> Optional[BuildStatus]:
        self._ensure_loaded()
        assert self._cache is not None
        return self._cache.get(project)

    def list_projects(self) -> List[str]:
        self._ensure_loaded()
        assert self._cache is not None
        return sorted(self._cache.keys())
