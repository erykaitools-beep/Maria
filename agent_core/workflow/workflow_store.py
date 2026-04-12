"""
Workflow Store - JSONL persistence for workflow state.

Follows project convention: JSONL with MERGE semantics (key=workflow_id).
"""

import json
import logging
import os
import threading
from typing import Dict, List, Optional

from agent_core.workflow.workflow_model import WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)

DEFAULT_PATH = os.path.join("meta_data", "workflows.jsonl")
MAX_IN_MEMORY = 100


class WorkflowStore:
    """JSONL-backed workflow persistence."""

    def __init__(self, path: str = DEFAULT_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._workflows: Dict[str, WorkflowState] = {}
        self._load()

    def _load(self) -> None:
        """Load workflows from JSONL (MERGE semantics - last wins)."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        wf = WorkflowState.from_dict(d)
                        self._workflows[wf.workflow_id] = wf
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning("Skipping malformed workflow line: %s", e)
        except OSError as e:
            logger.error("Failed to load workflows: %s", e)

    def save(self, workflow: WorkflowState) -> None:
        """Save or update a workflow (append to JSONL)."""
        with self._lock:
            self._workflows[workflow.workflow_id] = workflow
            self._append(workflow)
            self._maybe_compact()

    def _append(self, workflow: WorkflowState) -> None:
        """Append single workflow record to JSONL."""
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(workflow.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error("Failed to write workflow: %s", e)

    def _maybe_compact(self) -> None:
        """Compact JSONL if too many duplicate keys (>2x in-memory count)."""
        try:
            if not os.path.exists(self._path):
                return
            with open(self._path, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            if line_count > len(self._workflows) * 2 + 10:
                self._compact()
        except OSError:
            pass

    def _compact(self) -> None:
        """Rewrite JSONL with only latest state per workflow."""
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for wf in self._workflows.values():
                    f.write(json.dumps(wf.to_dict(), ensure_ascii=False) + "\n")
            os.replace(tmp, self._path)
            logger.info("Compacted workflows.jsonl: %d records", len(self._workflows))
        except OSError as e:
            logger.error("Compact failed: %s", e)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def get(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow by ID."""
        return self._workflows.get(workflow_id)

    def get_by_goal(self, goal_id: str) -> Optional[WorkflowState]:
        """Get workflow associated with a goal."""
        for wf in self._workflows.values():
            if wf.goal_id == goal_id:
                return wf
        return None

    def list_active(self) -> List[WorkflowState]:
        """List non-terminal workflows."""
        return [
            wf for wf in self._workflows.values()
            if not wf.is_terminal
        ]

    def list_all(self, status: Optional[WorkflowStatus] = None) -> List[WorkflowState]:
        """List workflows, optionally filtered by status."""
        wfs = list(self._workflows.values())
        if status is not None:
            wfs = [wf for wf in wfs if wf.status == status]
        return sorted(wfs, key=lambda w: w.updated_at, reverse=True)

    def recover_interrupted(self) -> List[WorkflowState]:
        """Find workflows that were RUNNING when system stopped."""
        interrupted = []
        for wf in self._workflows.values():
            if wf.status == WorkflowStatus.RUNNING:
                wf.status = WorkflowStatus.PAUSED
                wf.paused_by = "system"
                self.save(wf)
                interrupted.append(wf)
        return interrupted

    def count(self) -> int:
        """Total workflow count."""
        return len(self._workflows)

    def prune_old(self, max_terminal: int = 50) -> int:
        """Remove oldest terminal workflows beyond limit."""
        terminal = [
            wf for wf in self._workflows.values()
            if wf.is_terminal
        ]
        if len(terminal) <= max_terminal:
            return 0
        terminal.sort(key=lambda w: w.completed_at or w.updated_at)
        to_remove = terminal[:len(terminal) - max_terminal]
        for wf in to_remove:
            del self._workflows[wf.workflow_id]
        if to_remove:
            self._compact()
        return len(to_remove)
