"""
StrategicPlanner - LLM-powered strategic planning layer.

Runs periodically (every 30min or on event), asks qwen3:8b
what Maria should focus on. Produces StrategicPlan that
tactical loop (PlannerCore) follows.

Planner v2 Phase B.
"""

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from agent_core.planner.strategic_plan import PlannedAction, StrategicPlan
from agent_core.planner.time_context import TimeContext

logger = logging.getLogger(__name__)

# How often to replan (seconds)
REPLAN_INTERVAL_SEC = 1800  # 30 min

# Events that trigger immediate replan
REPLAN_EVENTS = {
    "goal_achieved", "new_material", "failure_pattern",
    "mode_change", "wake_up", "window_change",
}

SYSTEM_PROMPT = """Jestes strategicznym planista dla Maria - autonomicznego agenta AI do nauki.
Twoje zadanie: zdecyduj co Maria powinna robic w nastepnych 30 minutach.

Zasady:
- W learning window (9-11, 14-16 Berlin): priorytet LEARN/EXAM/REVIEW
- Poza window: priorytet CREATIVE/EVALUATE/IDLE
- Po failed exam: zawsze REVIEW przed retry
- Max 3 proby tej samej akcji, potem skip
- Jesli < 5 min do zamkniecia window: nie zaczynaj nowego LEARN
- Wieczor (18+): lekkie akcje (creative, evaluate)
- Noc (22-7): IDLE

Dostepne akcje: learn, exam, review, fetch, ask_expert, evaluate, creative, self_analyze, critique, validate, idle

Odpowiedz WYLACZNIE w JSON (bez komentarzy):
{
  "plan": [{"action": "...", "goal_id": "...", "reason": "..."}],
  "blocked_until": {"goal_id": "reason do skip"},
  "idle_strategy": "creative|evaluate|wait",
  "notes": "krotkie wyjasnienie"
}"""


def _build_context_prompt(
    time_ctx: TimeContext,
    active_goals: list,
    recent_actions: list,
    knowledge_gaps: list,
    retention_rate: float,
    available_materials: int,
    beliefs_weak: int,
    action_failures: dict,
) -> str:
    """Build user prompt with current system state."""
    goals_list = []
    for g in active_goals[:10]:
        goals_list.append({
            "id": g.get("id", "")[:16],
            "type": g.get("type", ""),
            "topic": g.get("topic", g.get("description", ""))[:40],
            "progress": g.get("progress", 0),
            "age_hours": g.get("age_hours", 0),
        })

    recent_list = []
    for a in recent_actions[:10]:
        recent_list.append({
            "action": a.get("action_type", ""),
            "goal": a.get("goal_id", "")[:16] if a.get("goal_id") else None,
            "result": "ok" if a.get("success") else "fail",
            "ago_min": a.get("ago_min", 0),
        })

    backed_off = [k for k, (c, _) in action_failures.items() if c >= 3]

    ctx = {
        "time": time_ctx.summary(),
        "learning_window": time_ctx.is_learning_window,
        "minutes_to_window_close": time_ctx.minutes_to_window_close,
        "minutes_to_next_window": time_ctx.minutes_to_next_window,
        "time_slot": time_ctx.time_slot,
        "active_goals": goals_list,
        "recent_actions": recent_list,
        "knowledge_gaps": knowledge_gaps[:5],
        "retention_rate": round(retention_rate, 2),
        "available_materials": available_materials,
        "beliefs_weak": beliefs_weak,
        "backed_off_actions": backed_off,
    }

    return json.dumps(ctx, ensure_ascii=False, indent=2)


def _parse_llm_response(text: str) -> Optional[dict]:
    """Parse LLM JSON response with fallback extraction."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON block from markdown
    for start_marker in ["```json", "```"]:
        if start_marker in text:
            start = text.index(start_marker) + len(start_marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

    # Try finding first { ... }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Strategic planner: could not parse LLM response")
    return None


class StrategicPlanner:
    """LLM-powered strategic planning layer."""

    def __init__(self):
        self._llm_fn: Optional[Callable] = None  # ask_as_role(role, prompt)
        self._goal_store = None
        self._knowledge_analyzer = None
        self._evaluation_observer = None

        self._current_plan: Optional[StrategicPlan] = None
        self._last_plan_ts: float = 0
        self._time_ctx = TimeContext()

        # Recent actions log (ring buffer, last 20)
        self._recent_actions: List[dict] = []
        self._MAX_RECENT = 20

    # -- Dependency injection --

    def set_llm_fn(self, fn: Callable) -> None:
        """Set LLM function: fn(role, prompt) -> str."""
        self._llm_fn = fn

    def set_goal_store(self, store) -> None:
        self._goal_store = store

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._knowledge_analyzer = analyzer

    def set_evaluation_observer(self, observer) -> None:
        self._evaluation_observer = observer

    # -- Public API --

    @property
    def current_plan(self) -> Optional[StrategicPlan]:
        if self._current_plan and self._current_plan.is_expired:
            return None
        return self._current_plan

    def restore_plan(self, plan: StrategicPlan) -> None:
        """Re-seed a plan rehydrated from a warm-recovery snapshot (Klocek 9b).

        The caller is responsible for freshness/expiry checks before calling;
        this only sets the in-flight plan back so the tactical loop resumes it
        instead of starting plan-less after a restart."""
        self._current_plan = plan
        # Reset the replan clock to now. Otherwise _last_plan_ts stays 0 and
        # should_replan()'s time branch (elapsed = now - 0 >> interval) fires on
        # the very first tick, discarding the just-restored plan before it is
        # ever used -- which would make the whole resume a no-op when the
        # strategist drives (STRATEGIC_PLANNER_DRIVES). The resumed plan gets a
        # normal replan interval to actually run; expiry already capped it.
        self._last_plan_ts = time.time()

    def should_replan(self, event: Optional[str] = None) -> bool:
        """Check if strategic replanning is needed."""
        if self._llm_fn is None:
            return False

        # Event-driven replan
        if event and event in REPLAN_EVENTS:
            return True

        # Time-based replan
        elapsed = time.time() - self._last_plan_ts
        if elapsed > REPLAN_INTERVAL_SEC:
            return True

        # Current plan exhausted
        if self._current_plan and self._current_plan.is_exhausted:
            return True

        return False

    def record_action(self, action_type: str, goal_id: Optional[str],
                      success: bool, duration_ms: float = 0) -> None:
        """Record executed action for context in next planning session."""
        self._recent_actions.append({
            "action_type": action_type,
            "goal_id": goal_id,
            "success": success,
            "ago_min": 0,
            "ts": time.time(),
        })
        if len(self._recent_actions) > self._MAX_RECENT:
            self._recent_actions = self._recent_actions[-self._MAX_RECENT:]

    def plan(self, action_failures: Optional[dict] = None) -> Optional[StrategicPlan]:
        """Run strategic planning session with LLM.

        Args:
            action_failures: PlannerCore._action_failures dict for backoff context

        Returns:
            StrategicPlan or None if LLM unavailable/failed.
        """
        if self._llm_fn is None:
            return None

        context = self._gather_context(action_failures or {})
        prompt = _build_context_prompt(self._time_ctx, **context)

        try:
            logger.info("[Strategic] Requesting plan from qwen3:8b...")
            start = time.time()
            response = self._llm_fn("planner", f"{SYSTEM_PROMPT}\n\nAktualny stan:\n{prompt}")
            elapsed_ms = (time.time() - start) * 1000
            logger.info(f"[Strategic] LLM responded in {elapsed_ms:.0f}ms")

            parsed = _parse_llm_response(response)
            if parsed is None:
                logger.warning("[Strategic] Failed to parse LLM response, using rule-based fallback")
                return self._rule_based_fallback()

            plan = self._build_plan(parsed)
            self._current_plan = plan
            self._last_plan_ts = time.time()

            logger.info(f"[Strategic] Plan created: {len(plan.action_queue)} actions, "
                        f"idle={plan.idle_strategy}")
            return plan

        except Exception as e:
            logger.warning(f"[Strategic] LLM call failed: {e}, using fallback")
            return self._rule_based_fallback()

    # -- Internal --

    def _gather_context(self, action_failures: dict) -> dict:
        """Gather current system state for prompt."""
        active_goals = []
        if self._goal_store:
            for g in self._goal_store.get_active():
                active_goals.append({
                    "id": g.id,
                    "type": g.type.value,
                    "description": g.description,
                    "topic": g.metadata.get("topic", g.description),
                    "progress": g.progress,
                    "age_hours": round((time.time() - g.created_at) / 3600, 1),
                })

        # Update ago_min for recent actions
        now = time.time()
        for a in self._recent_actions:
            a["ago_min"] = round((now - a.get("ts", now)) / 60)

        retention = 0.0
        if self._evaluation_observer:
            try:
                report = self._evaluation_observer.generate_report()
                retention = report.metrics.get("retention_rate", 0.0)
            except Exception:
                pass

        available = 0
        gaps = []
        beliefs_weak = 0
        if self._knowledge_analyzer:
            try:
                snap = self._knowledge_analyzer.get_knowledge_snapshot()
                available = len(snap.get("files_by_status", {}).get("new", []))
                # gaps from world model would be here
            except Exception:
                pass

        return {
            "active_goals": active_goals,
            "recent_actions": list(self._recent_actions),
            "knowledge_gaps": gaps,
            "retention_rate": retention,
            "available_materials": available,
            "beliefs_weak": beliefs_weak,
            "action_failures": action_failures,
        }

    def _build_plan(self, parsed: dict) -> StrategicPlan:
        """Build StrategicPlan from parsed LLM JSON."""
        actions = []
        for item in parsed.get("plan", []):
            action_type = item.get("action", item.get("action_type", ""))
            if not action_type:
                continue
            # Validate goal_id exists if referenced
            goal_id = item.get("goal_id")
            if goal_id and self._goal_store:
                if not self._goal_store.get(goal_id):
                    goal_id = None  # LLM hallucinated, drop it
            actions.append(PlannedAction(
                action_type=action_type,
                goal_id=goal_id,
                reason=item.get("reason", ""),
            ))

        return StrategicPlan(
            valid_until=time.time() + REPLAN_INTERVAL_SEC,
            action_queue=actions,
            blocked_goals=parsed.get("blocked_until", {}),
            idle_strategy=parsed.get("idle_strategy", "wait"),
            notes=parsed.get("notes", ""),
            model_used="qwen3:8b",
        )

    def _rule_based_fallback(self) -> StrategicPlan:
        """Fallback plan when LLM is unavailable."""
        tc = self._time_ctx
        actions = []

        if tc.is_learning_window:
            # Learning time - generic learn/exam cycle (is_learning_window already
            # encodes the day rule from PROFILE_LEARNING; no separate weekday gate).
            actions.append(PlannedAction(action_type="learn", reason="learning window active"))
            actions.append(PlannedAction(action_type="exam", reason="test after learning"))
            actions.append(PlannedAction(action_type="review", reason="consolidate"))
            idle = "evaluate"
        elif tc.is_quiet_hours:
            idle = "wait"
        else:
            # Evening/midday - light work
            actions.append(PlannedAction(action_type="creative", reason="reflection time"))
            actions.append(PlannedAction(action_type="evaluate", reason="periodic check"))
            idle = "wait"

        plan = StrategicPlan(
            valid_until=time.time() + REPLAN_INTERVAL_SEC,
            action_queue=actions,
            idle_strategy=idle,
            notes="rule-based fallback (LLM unavailable)",
            model_used="rules",
        )
        self._current_plan = plan
        self._last_plan_ts = time.time()
        return plan
