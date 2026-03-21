"""
Strategy Templates for K8 Deliberation.

Pre-built multi-step strategies as factory functions.
v1: 3 templates for learning domain.
v2 path: register new templates for Smart Home, Code Agent, etc.

Each template is a callable: (goal_id, intent, **kwargs) -> Strategy.
Templates are registered in TEMPLATE_REGISTRY for dynamic lookup.

Kontrakt: docs/CONTRACTS.md - Kontrakt 8: Deliberation
"""

from typing import Any, Callable, Dict, List, Optional

from agent_core.deliberation.strategy import (
    Strategy,
    create_step,
    create_strategy,
)


def build_learn_topic(
    goal_id: str,
    intent: str = "",
    topic: str = "",
    **kwargs,
) -> Strategy:
    """
    Learn a topic from scratch.

    Flow: LEARN -> EXAM -> (pass? COMPLETE : REVIEW -> EXAM)
    """
    params = {"topics": [topic]} if topic else {}
    steps = [
        create_step(
            order=0,
            action_type="learn",
            description=f"Nauka: {topic}" if topic else "Nauka nowego materialu",
            action_params=dict(params),
        ),
        create_step(
            order=1,
            action_type="exam",
            description=f"Egzamin: {topic}" if topic else "Egzamin",
            action_params=dict(params),
        ),
        create_step(
            order=2,
            action_type="review",
            description=f"Powtorka: {topic}" if topic else "Powtorka",
            action_params=dict(params),
            fallback_step_order=None,  # last step, no further fallback
        ),
        create_step(
            order=3,
            action_type="exam",
            description=f"Egzamin po powtorce: {topic}" if topic else "Egzamin po powtorce",
            action_params=dict(params),
            max_retries=2,
            fallback_step_order=2,  # on fail, go back to review
        ),
    ]
    # Step 1 (first exam): on fail, jump to review (step 2)
    steps[1].fallback_step_order = 2

    return create_strategy(
        goal_id=goal_id,
        template_name="learn_topic",
        steps=steps,
        intent=intent or f"Nauka tematu: {topic}",
        metadata={"topic": topic} if topic else {},
    )


def build_explore_new(
    goal_id: str,
    intent: str = "",
    topic: str = "",
    **kwargs,
) -> Strategy:
    """
    Explore new content from the web.

    Flow: FETCH -> LEARN -> EXAM
    If topic is provided, fetch targets that topic specifically
    (used when consolidate is exhausted for a weak topic).
    """
    fetch_params = {}
    learn_params = {}
    if topic:
        fetch_params["topics"] = [topic]
        learn_params["topics"] = [topic]
        fetch_desc = f"Pobieranie materialow o: {topic}"
        learn_desc = f"Nauka materialu o: {topic}"
        exam_desc = f"Egzamin z: {topic}"
    else:
        fetch_desc = "Pobieranie nowych materialow z internetu"
        learn_desc = "Nauka pobranego materialu"
        exam_desc = "Egzamin z nowego materialu"

    steps = [
        create_step(
            order=0,
            action_type="fetch",
            description=fetch_desc,
            action_params=fetch_params,
            max_retries=2,
        ),
        create_step(
            order=1,
            action_type="learn",
            description=learn_desc,
            action_params=learn_params,
        ),
        create_step(
            order=2,
            action_type="exam",
            description=exam_desc,
            action_params=learn_params,
            fallback_step_order=1,  # on fail, re-learn
        ),
    ]
    return create_strategy(
        goal_id=goal_id,
        template_name="explore_new",
        steps=steps,
        intent=intent or (f"Eksploracja materialow o: {topic}" if topic else "Eksploracja nowych materialow z internetu"),
        metadata={"topic": topic} if topic else {},
    )


def build_consolidate(
    goal_id: str,
    intent: str = "",
    topic: str = "",
    **kwargs,
) -> Strategy:
    """
    Consolidate weak knowledge.

    Flow: REVIEW -> EXAM -> EVALUATE
    """
    params = {"topics": [topic]} if topic else {}
    steps = [
        create_step(
            order=0,
            action_type="review",
            description=f"Powtorka slabych tematow: {topic}" if topic else "Powtorka slabych tematow",
            action_params=dict(params),
        ),
        create_step(
            order=1,
            action_type="exam",
            description=f"Egzamin kontrolny: {topic}" if topic else "Egzamin kontrolny",
            action_params=dict(params),
            max_retries=2,
            fallback_step_order=0,  # on fail, review again
        ),
        create_step(
            order=2,
            action_type="evaluate",
            description="Ewaluacja po konsolidacji",
        ),
    ]
    return create_strategy(
        goal_id=goal_id,
        template_name="consolidate",
        steps=steps,
        intent=intent or f"Konsolidacja wiedzy: {topic}" if topic else "Konsolidacja wiedzy",
        metadata={"topic": topic} if topic else {},
    )


def build_experiment(
    goal_id: str,
    intent: str = "",
    proposal_id: str = "",
    **kwargs,
) -> Strategy:
    """
    Run a parameter experiment (K11).

    Flow: EVALUATE (baseline) -> EXPERIMENT -> EVALUATE (result) -> report
    """
    steps = [
        create_step(
            order=0,
            action_type="evaluate",
            description="Ewaluacja bazowa przed eksperymentem",
        ),
        create_step(
            order=1,
            action_type="experiment",
            description=f"Eksperyment: {intent}" if intent else "Eksperyment parametru",
            action_params={"proposal_id": proposal_id} if proposal_id else {},
        ),
        create_step(
            order=2,
            action_type="evaluate",
            description="Ewaluacja po eksperymencie",
        ),
    ]
    return create_strategy(
        goal_id=goal_id,
        template_name="experiment",
        steps=steps,
        intent=intent or "Eksperyment z parametrem",
        metadata={"proposal_id": proposal_id} if proposal_id else {},
    )


# Template type: callable(goal_id, intent, **kwargs) -> Strategy
StrategyTemplate = Callable[..., Strategy]

# Registry of available templates.
# v2 path: add "smart_home_routine", "code_review" etc.
TEMPLATE_REGISTRY: Dict[str, StrategyTemplate] = {
    "learn_topic": build_learn_topic,
    "explore_new": build_explore_new,
    "consolidate": build_consolidate,
    "experiment": build_experiment,
}


def get_template(name: str) -> Optional[StrategyTemplate]:
    """Look up a template by name."""
    return TEMPLATE_REGISTRY.get(name)


def list_templates() -> List[str]:
    """List available template names."""
    return list(TEMPLATE_REGISTRY.keys())
