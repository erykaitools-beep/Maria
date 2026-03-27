"""Conversation-Driven Learning bridge.

Detects learning intents from user messages and creates LEARNING goals.
Called from REPL and WebUI before brain.think().

Flow:
    User: "Poczytaj o genetyce"
    -> detect_learning_intent() finds topic="genetyce", action="learn"
    -> PerceptionEvent(user_message) pushed to buffer
    -> LEARNING goal created (PROPOSED) in GoalStore
    -> Planner picks it up -> TeacherAgent fetches/learns

Zero LLM - rule-based intent detection.
"""

import logging
from typing import Any, Dict, Optional

from agent_core.perception.learning_intent import detect_learning_intent

logger = logging.getLogger(__name__)


def process_user_message(text: str, ctx, channel: str = "repl") -> Optional[Dict[str, Any]]:
    """Process user message for learning intent.

    Call this before brain.think() to detect learning requests.
    Creates PerceptionEvent and LEARNING goal if intent found.

    Args:
        text: User message text.
        ctx: SharedContext with perception_buffer, goal_store.
        channel: Source channel ("repl" or "webui").

    Returns:
        Dict with intent info if learning detected, None otherwise.
    """
    # 1. Push user message to perception buffer (always, not just learning)
    if ctx.perception_buffer:
        try:
            from agent_core.perception.adapters.user_adapter import UserAdapter
            event = UserAdapter.from_message(text, channel=channel)
            ctx.perception_buffer.push(event)
        except Exception as e:
            logger.debug(f"[CDL] Failed to push perception event: {e}")

    # 2. Detect learning intent
    intent = detect_learning_intent(text)
    if not intent:
        return None

    topic = intent["topic"]
    action = intent["action"]
    logger.info(f"[CDL] Learning intent detected: '{topic}' (action={action})")

    # 3. Create LEARNING goal in GoalStore
    goal_id = None
    if ctx.goal_store:
        try:
            from agent_core.goals.goal_model import (
                GoalType, GoalStatus, create_goal,
            )

            goal = create_goal(
                goal_type=GoalType.LEARNING,
                description=f"Nauka: {topic}",
                priority=0.8,  # User-requested = high priority
                status=GoalStatus.PENDING,  # Skip PROPOSED, user explicitly asked
                created_by="user_conversation",
                metadata={
                    "source": "conversation",
                    "channel": channel,
                    "action": action,
                    "topic": topic,
                    "topics": [topic],  # Planner reads this for topic filtering
                    "original_text": text[:200],
                },
            )
            goal_id = ctx.goal_store.create(goal)
            ctx.goal_store.save()
            logger.info(f"[CDL] Created LEARNING goal: {goal_id} -> '{topic}'")
        except Exception as e:
            logger.warning(f"[CDL] Failed to create goal: {e}")

    # 4. Index topic in semantic memory for future retrieval
    if ctx.semantic_search and topic:
        try:
            ctx.semantic_search.index_text(
                "knowledge",
                f"user_request:{topic[:50]}",
                f"Operator poprosil o nauke: {topic}",
                {"source": "user_conversation", "channel": channel},
            )
        except Exception:
            pass

    return {
        "topic": topic,
        "action": action,
        "goal_id": goal_id,
        "confidence": intent["confidence"],
    }
