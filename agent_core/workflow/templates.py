"""
Pre-built workflow templates - reusable multi-step sequences.

Per roadmap: "Workflow kodem/konfiguracja, nie visual editor."
Start simple: linear sequences. Each returns List[WorkflowStep].
"""

from typing import List

from agent_core.workflow.workflow_model import FailPolicy, WorkflowStep


def research_workflow(topic: str) -> List[WorkflowStep]:
    """
    Research a topic: fetch from web, learn, exam.
    3 steps, ~10min estimated.
    """
    return [
        WorkflowStep(
            order=0,
            action="fetch",
            params={"topic": topic, "source": "wikipedia"},
            description=f"Fetch materials about '{topic}' from Wikipedia",
            on_fail=FailPolicy.SKIP,  # Continue even if fetch fails
            max_retries=2,
        ),
        WorkflowStep(
            order=1,
            action="learn",
            params={"topic": topic, "max_iterations": 3},
            description=f"Learn about '{topic}' from available materials",
            on_fail=FailPolicy.STOP,
        ),
        WorkflowStep(
            order=2,
            action="exam",
            params={"topic": topic},
            description=f"Test knowledge about '{topic}'",
            on_fail=FailPolicy.SKIP,  # Exam fail is informational
        ),
    ]


def deep_learn_workflow(topic: str) -> List[WorkflowStep]:
    """
    Deep learning: fetch, learn, exam, review, exam again.
    5 steps, ~20min estimated. Mirrors K8 learn_topic template.
    """
    return [
        WorkflowStep(
            order=0,
            action="fetch",
            params={"topic": topic, "source": "wikipedia"},
            description=f"Fetch materials about '{topic}'",
            on_fail=FailPolicy.SKIP,
            max_retries=2,
        ),
        WorkflowStep(
            order=1,
            action="learn",
            params={"topic": topic, "max_iterations": 5},
            description=f"Study '{topic}' in depth",
            on_fail=FailPolicy.STOP,
        ),
        WorkflowStep(
            order=2,
            action="exam",
            params={"topic": topic},
            description=f"First knowledge test: '{topic}'",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=3,
            action="review",
            params={"topic": topic},
            description=f"Review weak areas of '{topic}'",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=4,
            action="exam",
            params={"topic": topic},
            description=f"Final test: '{topic}'",
            on_fail=FailPolicy.SKIP,
        ),
    ]


def daily_review_workflow() -> List[WorkflowStep]:
    """
    Daily maintenance: evaluate, critique, review weak topics.
    3 steps, ~5min estimated.
    """
    return [
        WorkflowStep(
            order=0,
            action="evaluate",
            params={},
            description="Generate evaluation report",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=1,
            action="critique",
            params={},
            description="Run knowledge quality critique",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=2,
            action="review",
            params={"mode": "spaced_repetition"},
            description="Review topics due for repetition",
            on_fail=FailPolicy.SKIP,
        ),
    ]


def system_health_workflow() -> List[WorkflowStep]:
    """
    System health check: evaluate, self-analyze, maintenance.
    3 steps, ~5min estimated.
    """
    return [
        WorkflowStep(
            order=0,
            action="evaluate",
            params={},
            description="Generate system evaluation report",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=1,
            action="self_analyze",
            params={},
            description="Run self-analysis (K12)",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=2,
            action="maintenance",
            params={"type": "health_check"},
            description="Run maintenance tasks",
            on_fail=FailPolicy.SKIP,
        ),
    ]


def full_audit_workflow() -> List[WorkflowStep]:
    """
    Full system audit: evaluate, critique, validate, self-analyze.
    4 steps, ~15min estimated.
    """
    return [
        WorkflowStep(
            order=0,
            action="evaluate",
            params={},
            description="Generate comprehensive evaluation",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=1,
            action="critique",
            params={},
            description="Run knowledge critique (7 dimensions)",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=2,
            action="validate",
            params={},
            description="Cross-validate learned knowledge",
            on_fail=FailPolicy.SKIP,
        ),
        WorkflowStep(
            order=3,
            action="self_analyze",
            params={},
            description="Self-analysis with recommendations",
            on_fail=FailPolicy.SKIP,
        ),
    ]


# Template registry for lookup by name
WORKFLOW_TEMPLATES = {
    "research": {
        "factory": research_workflow,
        "description": "Research a topic (fetch + learn + exam)",
        "needs_topic": True,
        "estimated_minutes": 10,
    },
    "deep_learn": {
        "factory": deep_learn_workflow,
        "description": "Deep learning (fetch + learn + exam + review + exam)",
        "needs_topic": True,
        "estimated_minutes": 20,
    },
    "daily_review": {
        "factory": daily_review_workflow,
        "description": "Daily review (evaluate + critique + review)",
        "needs_topic": False,
        "estimated_minutes": 5,
    },
    "health_check": {
        "factory": system_health_workflow,
        "description": "System health (evaluate + self-analyze + maintenance)",
        "needs_topic": False,
        "estimated_minutes": 5,
    },
    "full_audit": {
        "factory": full_audit_workflow,
        "description": "Full audit (evaluate + critique + validate + self-analyze)",
        "needs_topic": False,
        "estimated_minutes": 15,
    },
}
