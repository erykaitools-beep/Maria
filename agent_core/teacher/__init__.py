"""
Agent Nauczyciel - autonomous learning agent for M.A.R.I.A.

Decides what to learn, how to test, when to review.
Uses NIM for planning, Ollama for heavy learning work.
"""

from agent_core.teacher.teaching_strategy import TeachingStrategy, SpacedRepetitionScheduler
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.teacher.teacher_agent import TeacherAgent

__all__ = [
    "TeachingStrategy",
    "SpacedRepetitionScheduler",
    "KnowledgeAnalyzer",
    "TeacherAgent",
]
