"""
Code Agent - Autonomous coding capability for M.A.R.I.A.

Orchestrates the full coding workflow: design -> generate -> write -> test -> fix.
Uses Claude/Codex for code generation, OpenClaw for file I/O and test execution.

Phase: V3 Code Agent
"""

from agent_core.code_agent.models import (
    PlannedFile,
    GeneratedFile,
    WrittenFile,
    TestResult,
    ApprovalCheckpoint,
)
from agent_core.code_agent.session import CodeSession, CodeSessionStatus
from agent_core.code_agent.prompt_builder import CodePromptBuilder

__all__ = [
    "PlannedFile",
    "GeneratedFile",
    "WrittenFile",
    "TestResult",
    "ApprovalCheckpoint",
    "CodeSession",
    "CodeSessionStatus",
    "CodePromptBuilder",
]
