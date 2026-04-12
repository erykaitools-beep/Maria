"""
Digital Hands (Faza 4) - Maria executes real tasks in the digital world.

ExecutionJournal: full audit trail of every action.
TaskExecutor: multi-step task execution with checkpoints.
ResultValidator: post-action verification.
WebResearcher: search + summarize information.
FileManager: create and organize files safely.
"""

from agent_core.hands.execution_journal import ExecutionJournal, JournalEntry
from agent_core.hands.task_executor import TaskExecutor, TaskStep, TaskResult
from agent_core.hands.result_validator import ResultValidator
from agent_core.hands.web_researcher import WebResearcher
from agent_core.hands.file_manager import FileManager

__all__ = [
    "ExecutionJournal",
    "FileManager",
    "JournalEntry",
    "ResultValidator",
    "TaskExecutor",
    "TaskResult",
    "TaskStep",
    "WebResearcher",
]
