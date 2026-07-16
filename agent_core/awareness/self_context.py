"""
SelfContext - Super-META E0: read-only situational self-awareness aggregator.

Welds together what Maria ALREADY knows -- scattered across separate organs --
into ONE "situational picture" that any organ can consult. This is the founding
brick of the Super-META subcategory (Digital Human Roadmap): NOT a new organ and
NOT new data, just a single read-only merge of existing sources:

  - WHO       (operator)         -> OperatorModel.get_context_for_prompt()
  - SELF      (state/capabilities) -> SelfPerception latest snapshot
  - KNOWLEDGE (learning/code/system) -> ContextBuilder.build()
  - MISSION   (META learning goal + active goals) -> GoalStore

Each source is wrapped defensively (like ContextBuilder's per-source try/except):
a failure in one organ degrades to an empty slot, never breaks the whole picture.
The merged context is cached for CACHE_TTL seconds because organs may consult it
often (chat tail in E2, cross-organ reads in E3, awareness loop in E4).

E1 will add a VISION-memory slot (last things Maria saw). E2-E4 wire this object
into the chat prompt, cross-organ reads, and the periodic Super-META loop.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Perpetual scaffolding goals that are always-active and so are NOT a useful
# answer to "what is Maria working on right now?".
_SCAFFOLD_GOAL_TYPES = {"META", "MAINTENANCE"}


class SelfContext:
    """
    Read-only aggregator merging Maria's existing self-awareness organs into one
    situational picture. See module docstring.

    Usage:
        sc = SelfContext(ctx)
        picture = sc.build()              # structured dict
        text = sc.format_for_telegram()   # human-readable /selfcontext view
    """

    CACHE_TTL = 45.0  # seconds

    # E3 cross-organ presence: if the operator chatted within this many seconds
    # we treat them as still present, so an organ (e.g. vision) can skip a
    # redundant "I saw motion" ping while the operator is clearly around.
    PRESENCE_WINDOW_SEC = 300.0

    # E3 rung2 cross-organ focus: how long a planner-published "what I'm working
    # on" stays the reported focus before we fall back to guessing from GoalStore
    # priorities. The planner cycle is intermittent (idle/sleep gaps), so a focus
    # older than this is treated as stale.
    ACTIVE_FOCUS_TTL = 1800.0  # 30 min

    def __init__(self, ctx: Any, context_builder: Optional[Any] = None):
        """
        Args:
            ctx: SharedContext (provides operator_model, self_perception,
                 goal_store, optionally context_builder).
            context_builder: Optional explicit ContextBuilder override (tests);
                 otherwise reuses ctx.context_builder or lazily makes its own.
        """
        self._ctx = ctx
        self._context_builder = context_builder
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0.0
        # E3 rung2: the planner's published "what I'm working on right now"
        # (replace-on-write, one live focus, guarded -- the planner writes from
        # its own thread while chat/tick/vision read).
        self._focus: Optional[Dict[str, Any]] = None
        self._focus_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, force: bool = False) -> Dict[str, Any]:
        """
        Build (or return cached) the merged situational picture.

        Returns a dict with keys: timestamp, iso, who, self, knowledge, mission.
        Always returns a dict; missing/broken organs degrade to empty slots.
        """
        now = time.time()
        if (
            not force
            and self._cache is not None
            and (now - self._cache_time) < self.CACHE_TTL
        ):
            return self._cache

        picture = {
            "timestamp": now,
            "iso": datetime.fromtimestamp(now).replace(microsecond=0).isoformat(),
            "who": self._who(),
            "self": self._self_state(),
            "knowledge": self._knowledge(),
            "mission": self._mission(),
            "vision": self._vision(),
        }

        self._cache = picture
        self._cache_time = now
        return picture

    def invalidate(self) -> None:
        """Force a fresh merge on the next build() call."""
        self._cache_time = 0.0

    # ------------------------------------------------------------------
    # E3 cross-organ presence API (the hub other organs consult)
    # ------------------------------------------------------------------

    def seconds_since_operator_seen(self) -> Optional[float]:
        """Seconds since the operator was last active in ANY chat channel (E3).

        Reads OperatorModel.last_seen -- the both-channel SSoT (Web UI chat
        record_interaction('web') + Telegram poll record_interaction('telegram'))
        -- LIVE, deliberately NOT through the 45s build() cache, so cross-organ
        presence checks see fresh activity (not a snapshot up to 45s stale).

        Returns None when unknown (no operator model / no last_seen / unparseable)
        so callers can fail-open: treat the operator as ABSENT rather than act on
        a silently-wrong value.

        Known cosmetic edge: isoformat() drops the DST fold bit, so a last_seen
        written in the autumn fall-back repeated hour can read ~3600s too OLD for
        ~1h/year. That direction is safe here (operator reads as absent -> vision
        over-pings, never wrongly silenced), so it is left as-is.
        """
        om = getattr(self._ctx, "operator_model", None)
        if om is None or not hasattr(om, "get_stats"):
            return None
        try:
            last_seen = (om.get_stats() or {}).get("last_seen")
            if not last_seen:
                return None
            # last_seen is datetime.now().isoformat() -- a NAIVE, system-local
            # (Europe/Warsaw) timestamp with no offset. fromisoformat().timestamp()
            # interprets a naive value as local time, matching time.time(), so no
            # manual TZ math is needed (avoids the 2h dobowa-logic bug class).
            seen_epoch = datetime.fromisoformat(str(last_seen)).timestamp()
            return time.time() - seen_epoch
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("SelfContext.seconds_since_operator_seen error: %s", e)
            return None

    def operator_active_recently(self, window_s: Optional[float] = None) -> bool:
        """True iff the operator chatted within window_s seconds (E3 presence).

        Fail-open: unknown last_seen -> False (operator ABSENT), so a cold/blank
        profile never silences an organ that consults this. Tolerates small clock
        skew (a last_seen up to 60s in the future still counts as present).
        """
        window = self.PRESENCE_WINDOW_SEC if window_s is None else float(window_s)
        secs = self.seconds_since_operator_seen()
        if secs is None:
            return False
        return -60.0 <= secs <= window

    def set_active_focus(
        self,
        goal_id: Optional[str] = None,
        description: Optional[str] = None,
        action: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> None:
        """E3 rung2 WRITE side: the planner publishes the goal it is ACTUALLY
        working on, so readers report the real focus instead of guessing from
        GoalStore priorities. Thread-safe replace-on-write (one live focus).

        Stored outside the 45s build() cache; read via _active_focus(). Fail-soft
        for the caller is the caller's job -- this never raises on normal input.
        """
        with self._focus_lock:
            self._focus = {
                "goal_id": goal_id,
                "description": description,
                "action": action,
                "ts": time.time() if ts is None else ts,
            }

    def _active_focus(self, max_age_s: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """The planner's published focus if still fresh, else None (-> fall back
        to the GoalStore heuristic). Fresh = published within max_age_s."""
        max_age = self.ACTIVE_FOCUS_TTL if max_age_s is None else float(max_age_s)
        with self._focus_lock:
            f = self._focus
        if not f:
            return None
        ts = f.get("ts")
        if not isinstance(ts, (int, float)) or (time.time() - ts) > max_age:
            return None
        return dict(f)

    def format_for_telegram(self) -> str:
        """Compact Polish summary of the whole situation for /selfcontext."""
        c = self.build()
        who = c.get("who", {}) or {}
        st = c.get("self", {}) or {}
        mission = c.get("mission", {}) or {}
        vision = c.get("vision", {}) or {}
        knowledge = c.get("knowledge", "") or ""

        kto = f"Kto: {who.get('name', 'nieznany')}"
        seen_str = self._humanize_age(who.get("last_seen_age_s"))
        if seen_str:
            kto += f" -- aktywny{seen_str}"
        lines: List[str] = [
            f"[Kontekst Marii] {c.get('iso', '')}",
            kto,
        ]

        if st:
            age = st.get("snapshot_age_s")
            age_str = (
                f", snapshot {int(age)}s temu"
                if isinstance(age, (int, float))
                else " (brak snapshotu)"
            )
            lines.append(
                f"Ja: tryb {st.get('mode_label', '?')}, "
                f"{st.get('capabilities_total', 0)} zdolnosci "
                f"({st.get('free', 0)} swobodnych), "
                f"serwisy {st.get('services', '?')}, "
                f"limity {st.get('limitations_critical', 0)} krytycznych{age_str}"
            )

        if mission:
            meta_str = "aktywna" if mission.get("meta_active") else "NIEAKTYWNA"
            lines.append(
                f"Misja META: {meta_str}, "
                f"{mission.get('active_goals', 0)} aktywnych celow"
            )
            top = mission.get("top_goal")
            if top:
                extra = ""
                if mission.get("focus_source") == "planner":
                    act = mission.get("current_action")
                    extra = f" [planista{f': {act}' if act else ''}]"
                lines.append(f"  Glowny cel: {top}{extra}")

        seen = vision.get("latest")
        if seen:
            age = vision.get("age_s")
            age_str = f" ({int(age)}s temu)" if isinstance(age, (int, float)) else ""
            lines.append(f"Wzrok{age_str}: {seen}")

        if knowledge:
            lines.append(f"Wiedza: {knowledge}")

        return "\n".join(lines)

    def format_for_chat(self) -> str:
        """Compact first-person situational cue for the chat prompt tail (E2).

        Unlike format_for_telegram (a diagnostic dump), this is a short, natural
        block so the chat model answers as ONE situated self: who it is talking
        to, what it last saw, and its current state/focus. Leads with vision --
        the one piece no other chat-tail part carries. Returns '' when there is
        nothing worth adding.

        MUST be consumed in the situational TAIL (never the cached prefix): it
        changes per turn (vision, mode), so in the prefix it would bust the warm
        KV cache. See OllamaBrain._build_situational_tail.
        """
        c = self.build()
        who = c.get("who") or {}
        vision = c.get("vision") or {}
        st = c.get("self") or {}
        mission = c.get("mission") or {}

        lines: List[str] = []

        name = who.get("name")
        if name and name not in ("nieznany", "Operator"):
            lines.append(f"Rozmawiasz teraz z operatorem: {name}.")

        seen = vision.get("latest")
        if seen:
            # One verbose LLaVA caption can be ~200 chars; cap it so it never
            # dominates the (CPU-prefilled, capped) chat tail.
            seen = str(seen).strip()
            if len(seen) > 160:
                seen = seen[:160].rstrip() + "..."
            when = self._humanize_age(vision.get("age_s"))
            lines.append(f"Ostatnio widzialas{when}: {seen}")

        state_bits: List[str] = []
        if st.get("mode_label"):
            state_bits.append(f"tryb {st['mode_label']}")
        top = mission.get("top_goal")
        if top:
            state_bits.append(f"glowny watek: {top}")
        if state_bits:
            lines.append("Twoj stan: " + ", ".join(state_bits) + ".")

        if not lines:
            return ""
        return "[Twoja sytuacja]\n" + "\n".join(lines)

    @staticmethod
    def _humanize_age(age_s: Any) -> str:
        """Human 'X temu' suffix for the chat tail, or '' if age is unknown."""
        if not isinstance(age_s, (int, float)) or age_s < 0:
            return ""
        if age_s < 90:
            return f" ({int(age_s)}s temu)"
        if age_s < 5400:  # under 90 min -> minutes
            return f" ({int(age_s / 60)} min temu)"
        return f" ({int(age_s / 3600)}h temu)"

    # ------------------------------------------------------------------
    # Private: per-organ readers (each degrades to empty on failure)
    # ------------------------------------------------------------------

    def _who(self) -> Dict[str, Any]:
        """Operator identity from OperatorModel."""
        om = getattr(self._ctx, "operator_model", None)
        if om is None:
            return {}
        try:
            name = (
                om.get_name()
                if hasattr(om, "get_name")
                else om.get_fact_value("name", "Operator")
            )
            brief = om.get_context_for_prompt() if hasattr(om, "get_context_for_prompt") else ""
            return {
                "name": name,
                "brief": brief,
                # E3: how long since the operator was last active in chat (None if
                # unknown) -- lets the chat tail / vision know if they're present.
                "last_seen_age_s": self.seconds_since_operator_seen(),
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("SelfContext._who error: %s", e)
            return {}

    def _self_state(self) -> Dict[str, Any]:
        """Mode, capabilities, services, limitations from the latest snapshot."""
        sp = getattr(self._ctx, "self_perception", None)
        if sp is None:
            return {}
        try:
            snap = sp.get_latest()
            if not snap:
                return {"snapshot_age_s": None}

            caps = snap.get("capabilities", {}) or {}
            services = snap.get("external_services", []) or []
            available = sum(
                1
                for s in services
                if isinstance(s, dict) and s.get("status") == "available"
            )
            severity = (snap.get("limitations", {}) or {}).get("by_severity", {}) or {}

            ts = snap.get("timestamp")
            age = (
                time.time() - float(ts)
                if isinstance(ts, (int, float))
                else None
            )

            return {
                "mode": snap.get("mode"),
                "mode_label": snap.get("mode_label"),
                "capabilities_total": int(caps.get("total", 0) or 0),
                "free": int(caps.get("free", 0) or 0),
                "guarded": int(caps.get("guarded", 0) or 0),
                "services": f"{available}/{len(services)}",
                "limitations_critical": int(severity.get("critical", 0) or 0),
                "limitations_warning": int(severity.get("warning", 0) or 0),
                "snapshot_age_s": age,
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("SelfContext._self_state error: %s", e)
            return {}

    def _knowledge(self) -> str:
        """Learning/code/system one-liner from ContextBuilder (reused or lazy)."""
        cb = self._get_context_builder()
        if cb is None:
            return ""
        try:
            return cb.build() or ""
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("SelfContext._knowledge error: %s", e)
            return ""

    def _get_context_builder(self) -> Optional[Any]:
        """Reuse an injected/ctx ContextBuilder, else lazily build our own once."""
        if self._context_builder is not None:
            return self._context_builder
        cb = getattr(self._ctx, "context_builder", None)
        if cb is not None:
            self._context_builder = cb
            return cb
        try:
            from agent_core.awareness.context_builder import ContextBuilder

            self._context_builder = ContextBuilder()
            return self._context_builder
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("SelfContext: ContextBuilder unavailable: %s", e)
            return None

    def _mission(self) -> Dict[str, Any]:
        """META mission status + active-goal summary + current real focus."""
        gs = getattr(self._ctx, "goal_store", None)
        if gs is None:
            return {}
        try:
            meta = gs.get("goal-meta-learn") if hasattr(gs, "get") else None
            active = (gs.get_active() if hasattr(gs, "get_active") else []) or []
            work = [g for g in active if self._goal_type_name(g) not in _SCAFFOLD_GOAL_TYPES]

            # E3 rung2: prefer the planner's PUBLISHED live focus (what it is
            # ACTUALLY working on this cycle) over guessing top_goal from GoalStore
            # priorities -- but ONLY while that goal is still active.
            focus = self._active_focus()
            current_action = None
            top = None
            focus_source = "heuristic"
            if focus and focus.get("description"):
                # Liveness gate: trust the focus only if its goal is STILL active.
                # Otherwise the planner finished/abandoned it and went idle (common
                # -- "74% no_goals"), and the lingering focus would misreport a done
                # goal as current. Then fall through to the GoalStore heuristic.
                fid = focus.get("goal_id")
                active_ids = {getattr(g, "id", None) for g in active}
                if fid is not None and fid in active_ids:
                    top = focus["description"]
                    current_action = focus.get("action")
                    focus_source = "planner"
            if top is None:
                # "Top goal" = highest-priority active goal that is NOT perpetual
                # scaffolding (META mission / MAINTENANCE).
                if work:
                    top_goal = max(work, key=lambda g: getattr(g, "priority", 0) or 0)
                    top = getattr(top_goal, "description", None)

            return {
                "meta_active": bool(getattr(meta, "is_active", False)) if meta is not None else False,
                "active_goals": len(active),
                "active_work_goals": len(work),
                "top_goal": top,
                "current_action": current_action,
                "focus_source": focus_source,
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("SelfContext._mission error: %s", e)
            return {}

    def _vision(self) -> Dict[str, Any]:
        """Last thing Maria saw, from VisionMemory (Super-META E1)."""
        vm = getattr(self._ctx, "vision_memory", None)
        if vm is None:
            return {}
        try:
            latest = vm.latest() if hasattr(vm, "latest") else None
            if not latest:
                return {"latest": None}
            ts = latest.get("timestamp")
            age = (
                time.time() - float(ts)
                if isinstance(ts, (int, float))
                else None
            )
            return {
                "latest": latest.get("description"),
                "age_s": age,
                "iso": latest.get("iso"),
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("SelfContext._vision error: %s", e)
            return {}

    @staticmethod
    def _goal_type_name(goal: Any) -> str:
        """Best-effort enum name of a goal's type (e.g. 'META', 'LEARNING')."""
        t = getattr(goal, "type", None)
        if t is None:
            return ""
        return getattr(t, "name", str(t))
