"""
Routing Rules - Maps task types to model roles.

Rule-based, zero LLM (ADR-013 compliant).
Separates routing intelligence from scheduler mechanics.

When MODEL-04 (TRIAGE) is deployed, heuristic_classify() will be
replaced by MODEL-04 inference. Until then, keyword-based fallback.
"""

import re
from enum import Enum
from typing import Optional

from .model_registry import ModelRole


class TaskType(Enum):
    """Types of tasks that can be routed to different models."""
    CHAT = "chat"              # User conversation
    LEARN = "learn"            # Learning analysis (chunks, exams)
    EXAM = "exam"              # Exam generation/grading
    PLAN = "plan"              # Strategic planning, architecture
    CODE = "code"              # Code generation, patches, refactoring
    CLASSIFY = "classify"      # Intent classification, tagging
    SUMMARIZE = "summarize"    # Memory compression, fact extraction
    GENERAL = "general"        # Catch-all


# Static routing table: task type -> preferred model role
_ROUTE_TABLE = {
    TaskType.CHAT: ModelRole.EXECUTOR,
    TaskType.LEARN: ModelRole.EXTERNAL,    # NIM first, fallback EXECUTOR
    TaskType.EXAM: ModelRole.EXTERNAL,     # NIM first, fallback EXECUTOR
    TaskType.PLAN: ModelRole.PLANNER,
    TaskType.CODE: ModelRole.CODER,
    TaskType.CLASSIFY: ModelRole.TRIAGE,
    TaskType.SUMMARIZE: ModelRole.MEMORY,
    TaskType.GENERAL: ModelRole.EXECUTOR,
}


def route_task(task_type: TaskType) -> ModelRole:
    """
    Map task type to preferred model role.

    Args:
        task_type: Type of task to route

    Returns:
        Preferred ModelRole for this task type
    """
    return _ROUTE_TABLE.get(task_type, ModelRole.EXECUTOR)


# Keyword patterns for heuristic classification
_CODE_KEYWORDS = re.compile(
    r'\b(pytest|def |class |import |\.py|patch|diff|refactor|'
    r'test_|bug|fix|syntax|compile|function|method|variable)\b',
    re.IGNORECASE,
)

_PLAN_KEYWORDS = re.compile(
    r'\b(plan|design|architecture|proposal|strategy|'
    r'multi.?step|reasoning|analyze|evaluate|decision)\b',
    re.IGNORECASE,
)

_SUMMARY_KEYWORDS = re.compile(
    r'\b(summarize|compress|extract|condense|'
    r'brief|summary|key.?points|highlights)\b',
    re.IGNORECASE,
)

_CLASSIFY_KEYWORDS = re.compile(
    r'\b(classify|categorize|tag|label|route|'
    r'intent|type|kind|sort)\b',
    re.IGNORECASE,
)


def heuristic_classify(prompt: str) -> TaskType:
    """
    Cheap keyword-based classification for when MODEL-04 (TRIAGE) is unavailable.

    This is a temporary fallback. When MODEL-04 is deployed after Stage 2
    benchmark, triage inference will replace this function.

    Args:
        prompt: The prompt text to classify

    Returns:
        Best-guess TaskType based on keyword matching
    """
    if not prompt or len(prompt.strip()) < 3:
        return TaskType.GENERAL

    text = prompt[:500]  # only scan first 500 chars

    # Count keyword matches per category
    code_score = len(_CODE_KEYWORDS.findall(text))
    plan_score = len(_PLAN_KEYWORDS.findall(text))
    summary_score = len(_SUMMARY_KEYWORDS.findall(text))
    classify_score = len(_CLASSIFY_KEYWORDS.findall(text))

    scores = {
        TaskType.CODE: code_score,
        TaskType.PLAN: plan_score,
        TaskType.SUMMARIZE: summary_score,
        TaskType.CLASSIFY: classify_score,
    }

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

    return TaskType.GENERAL
