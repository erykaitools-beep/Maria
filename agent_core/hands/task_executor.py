"""
TaskExecutor - Multi-step task execution with journal tracking.

Wraps individual tools (OpenClaw, web_source, file ops) into
a tracked execution with retry, validation, and audit trail.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent_core.hands.execution_journal import ExecutionJournal, JournalEntry
from agent_core.hands.result_validator import ResultValidator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskStep:
    """A single step in a multi-step task."""

    name: str
    tool_name: str
    tool_args: Dict[str, Any]
    description: str = ""


@dataclass
class TaskResult:
    """Result of a multi-step task execution."""

    task_id: str
    success: bool
    steps_completed: int
    steps_total: int
    results: List[Dict[str, Any]]
    errors: List[str]
    duration_ms: float
    journal_entry_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "results": self.results,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "journal_entry_id": self.journal_entry_id,
        }


class TaskExecutor:
    """Executes multi-step tasks with tracking and validation."""

    def __init__(
        self,
        journal: Optional[ExecutionJournal] = None,
        validator: Optional[ResultValidator] = None,
    ):
        self._journal = journal or ExecutionJournal()
        self._validator = validator or ResultValidator()
        self._tool_handlers: Dict[str, Callable] = {}

    def register_tool(self, tool_name: str, handler: Callable) -> None:
        """Register a tool handler. Handler signature: (args: Dict) -> Dict."""
        self._tool_handlers[tool_name] = handler

    def execute_single(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        description: str = "",
        goal_id: Optional[str] = None,
        max_retries: int = 1,
    ) -> TaskResult:
        """Execute a single-step task."""
        step = TaskStep(
            name=description or tool_name,
            tool_name=tool_name,
            tool_args=tool_args,
            description=description,
        )
        return self.execute_steps([step], description or tool_name, goal_id, max_retries)

    def execute_steps(
        self,
        steps: List[TaskStep],
        task_description: str,
        goal_id: Optional[str] = None,
        max_retries: int = 1,
    ) -> TaskResult:
        """Execute a multi-step task with journal tracking."""
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        start = time.time()

        # Create journal entry for the overall task
        entry = self._journal.create_entry(
            task_description=task_description,
            tool_name="multi_step" if len(steps) > 1 else steps[0].tool_name,
            tool_args={"steps": [s.name for s in steps]},
            goal_id=goal_id,
            max_retries=max_retries,
        )
        self._journal.mark_running(entry)

        results = []
        errors = []
        completed = 0

        for i, step in enumerate(steps):
            step_result = self._execute_step(step, entry, attempt=1, max_retries=max_retries)

            if step_result.get("success"):
                completed += 1
                results.append(step_result)
            else:
                error_msg = step_result.get("error", f"Step {step.name} failed")
                errors.append(error_msg)
                results.append(step_result)
                # Stop on first failure (sequential execution)
                break

        duration = (time.time() - start) * 1000
        success = completed == len(steps)

        if success:
            self._journal.mark_completed(entry, {
                "steps_completed": completed,
                "steps_total": len(steps),
            })
        else:
            self._journal.mark_failed(entry, "; ".join(errors))

        return TaskResult(
            task_id=task_id,
            success=success,
            steps_completed=completed,
            steps_total=len(steps),
            results=results,
            errors=errors,
            duration_ms=duration,
            journal_entry_id=entry.entry_id,
        )

    def _execute_step(
        self, step: TaskStep, entry: JournalEntry, attempt: int, max_retries: int
    ) -> Dict[str, Any]:
        """Execute a single step with retry."""
        handler = self._tool_handlers.get(step.tool_name)
        if not handler:
            error = f"No handler for tool: {step.tool_name}"
            self._journal.add_step(entry, step.name, "failed", {"error": error})
            return {"success": False, "error": error}

        last_error = ""
        for i in range(max_retries):
            try:
                result = handler(step.tool_args)

                # Validate
                validation = self._validator.validate(
                    step.tool_name, step.tool_args, result
                )

                if validation["valid"]:
                    self._journal.add_step(entry, step.name, "ok", {
                        "attempt": i + 1,
                        "validation": validation["reason"],
                    })
                    result["validation"] = validation
                    result["success"] = True
                    return result
                else:
                    last_error = validation["reason"]
                    self._journal.add_step(entry, step.name, "validation_failed", {
                        "attempt": i + 1,
                        "reason": last_error,
                    })

            except Exception as e:
                last_error = str(e)
                self._journal.add_step(entry, step.name, "exception", {
                    "attempt": i + 1,
                    "error": last_error,
                })

        return {"success": False, "error": last_error}

    @property
    def journal(self) -> ExecutionJournal:
        return self._journal

    def get_available_tools(self) -> List[str]:
        """List registered tool names."""
        return list(self._tool_handlers.keys())
