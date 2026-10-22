"""
VisionAdvisor -- "Maria reacts to what she sees".

When the camera detects real (non-ambient) motion, Maria first uses a fast
YOLO26 description when the event contains recognized objects. Unknown scenes
fall back to LLaVA in a BACKGROUND THREAD. She then sends the operator the photo
+ a short description so they can SEE what she sees.

Design constraints (deliberate):
- LLaVA is ~30-120s/call -> it must NEVER run inline in the tick (it would
  freeze the homeostasis loop). maybe_react() only checks cheap guards and
  spawns a thread; it returns immediately.
- Motion fires every tick while something moves -> a cooldown stops the ping
  from flooding the operator.
- R1/K7-safe: this only NOTIFIES (advisory). It never creates a goal (R1) and
  never emits an effector action (K7).
"""

import logging
import os
import threading
import time
from typing import Any, Callable, List, Optional

from agent_core.llm.work_priority import WorkPurpose, work_purpose

logger = logging.getLogger(__name__)

# Vision event types worth a closer (LLaVA) look.
SALIENT_EVENT_TYPES = ("vision_motion", "vision_alert")

# E3 cross-organ: when armed, downgrade the motion ping to a SILENT record (keep
# VisionMemory warm, skip the Telegram notification) if the operator is already
# present -- i.e. they were just active in chat, so "I saw motion" is redundant.
# Flag-gated (default OFF, observe -> cutover, like SELF_CONTEXT_CHAT_ENABLED).
SUPPRESS_WHEN_PRESENT_FLAG = "VISION_SUPPRESS_WHEN_PRESENT"


def _flag_on(name: str) -> bool:
    """Live os.environ feature-flag read (.env loads at start; arm via restart)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")

# Minimum seconds between reactions (LLaVA is slow; also rate-limits pings).
# Raised 180 -> 900 (2026-07-18): a camera on a window/street was firing ~20
# "Widze ruch" pings/day -- at 3 min it can ping on every passing car. 15 min
# still catches a genuinely lingering visitor. Env-overridable (VISION_ADVISOR_
# COOLDOWN_SEC) so the operator can retune without a code change; restart to arm.
def _default_cooldown_sec() -> float:
    raw = os.environ.get("VISION_ADVISOR_COOLDOWN_SEC", "").strip()
    try:
        val = float(raw)
        return val if val > 0 else 900.0
    except (TypeError, ValueError):
        return 900.0

DEFAULT_COOLDOWN_SEC = _default_cooldown_sec()


# How often the change gate may look INSIDE the cooldown window (seconds).
# The cooldown answers "has enough time passed?", which cannot distinguish the
# same street again from the camera now pointing at someone new -- it silences
# both for 15 minutes. This is the floor on asking the better question.
#
# Bound probe frequency independently of detector tick frequency. The public
# gate compares images with OpenCV; it never starts a model subprocess.
def _default_gate_probe_sec() -> float:
    raw = os.environ.get("VISION_GATE_PROBE_SEC", "").strip()
    try:
        val = float(raw)
        return val if val > 0 else 120.0
    except (TypeError, ValueError):
        return 120.0


DEFAULT_GATE_PROBE_SEC = _default_gate_probe_sec()

# How many gate-driven pings may fire before the cooldown has to elapse the
# ordinary way. Without this the probe path has no ceiling: someone moving
# around the room for an hour makes every probe see "a different scene", and at
# one probe per 120s that is ~30 pings/hour -- worse than the ~20/day this whole
# mechanism exists to fix. With a budget of 2 the worst case is 3 pings per
# cooldown window instead of 1, which is a controlled increase and only when the
# scene genuinely keeps changing.
#
# 0 disables the probe path entirely without touching code -- the escape hatch
# if it misbehaves live.
def _default_max_probe_pings() -> int:
    raw = os.environ.get("VISION_MAX_PROBE_PINGS", "").strip()
    try:
        val = int(raw)
        return val if val >= 0 else 2
    except (TypeError, ValueError):
        return 2


DEFAULT_MAX_PROBE_PINGS = _default_max_probe_pings()

# Prompt LLaVA in ENGLISH -- its strength. The previous Polish prompt ("Opisz
# krotko po polsku...") made the small CPU LLaVA 7B write BROKEN Polish (invented
# words like "trzebownik"/"pekacz", English fragments "backyard of a dwor",
# mangled grammar). LLaVA describes reliably in English; the operator-facing
# caption is then rendered to fluent Polish by translate_fn (NIM dracarys).
# A bare "describe what you see" reliably yields a real scene description (an
# over-specified prompt made it answer ABOUT the instructions instead).
DEFAULT_PROMPT = "Describe in one or two factual sentences what is visible in this image."

# Where the described frame is written so it can be sent as a photo.
DEFAULT_SNAPSHOT_PATH = "meta_data/vision_advisor_snapshot.jpg"

# E3 silent mode: the light trace left in VisionMemory when the operator is
# present, instead of a full LLaVA description. Keeps "co ostatnio widzialas?"
# honest (there WAS motion) without burning ~1-2 min of CPU next to active chat.
SILENT_PLACEHOLDER = "ruch wykryty (operator obecny)"

# Quiet-hours silent mode: at night we neither ping nor run LLaVA -- the operator
# is asleep and describing for no one would only burn CPU (which, on this
# CPU-only box, is itself a source of the mode_change alerts we just quieted).
# The motion still leaves a trace so "co widzialas w nocy?" stays answerable.
QUIET_PLACEHOLDER = "ruch wykryty (cisza nocna)"


class VisionAdvisor:
    """Salient motion -> threaded LLaVA describe -> photo + caption to operator."""

    def __init__(
        self,
        cortex: Any,
        notify_fn: Optional[Any] = None,
        photo_fn: Optional[Any] = None,
        cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
        prompt: Optional[str] = None,
        snapshot_path: Optional[str] = None,
        translate_fn: Optional[Any] = None,
        memory: Optional[Any] = None,
        operator_present_fn: Optional[Callable[[], bool]] = None,
        quiet_hours_fn: Optional[Callable[[], bool]] = None,
        gate_probe_sec: float = DEFAULT_GATE_PROBE_SEC,
        max_probe_pings: int = DEFAULT_MAX_PROBE_PINGS,
    ):
        """
        Args:
            cortex: VisionCortex exposing describe_snapshot(prompt, save_path).
            notify_fn: callable(text) -> Any, text-only fallback ping
                (e.g. TelegramNotifier.send_raw).
            photo_fn: callable(path, caption) -> bool, preferred delivery so the
                operator sees the frame (e.g. TelegramBot.send_photo). Falls back
                to notify_fn if absent / fails.
            cooldown_sec: minimum seconds between reactions.
            prompt: LLaVA prompt override (defaults to a clean one-sentence ask).
            snapshot_path: where the described frame is written for sending.
        """
        self._cortex = cortex
        self._notify_fn = notify_fn
        self._photo_fn = photo_fn
        self._cooldown_sec = float(cooldown_sec)
        self._prompt = prompt or DEFAULT_PROMPT
        # callable(english_text) -> polish_text. LLaVA describes in English; this
        # renders the caption to fluent Polish (None -> send the English as-is,
        # which is still honest, unlike broken LLaVA Polish).
        self._translate_fn = translate_fn
        # VisionMemory (Super-META E1): remember what was seen so "co ostatnio
        # widzialas?" has a real answer. Optional -> advisor still works without it.
        self._memory = memory
        # E3: callable() -> bool, "is the operator present right now?" (e.g. they
        # were just active in chat). Read via SelfContext so vision HEARS the chat
        # organ. None -> presence never suppresses (the pre-E3 always-ping behaviour).
        self._operator_present_fn = operator_present_fn
        # callable() -> bool, "is it the operator's quiet window now?" (same
        # predicate the Telegram notifier uses). None -> night never suppresses.
        self._quiet_hours_fn = quiet_hours_fn
        self._snapshot_path = snapshot_path or DEFAULT_SNAPSHOT_PATH
        self._last_react_ts = 0.0
        # Separate clock from _last_react_ts on purpose: a probe that finds the
        # same scene must NOT consume the ping cooldown, or one look would lock
        # the next quarter hour without anyone ever being told anything.
        self._last_gate_probe_ts = 0.0
        self._gate_probe_sec = float(gate_probe_sec)
        self._max_probe_pings = int(max_probe_pings)
        # Throttle state for refusal logging (see _refused).
        self._last_refusal_reason: Optional[str] = None
        self._last_refusal_log_ts = 0.0
        # Probe-driven pings since the last ordinary (clock-driven) reaction.
        self._probe_pings = 0
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # The optional OpenCV image gate is constructed lazily on first use.
        self._change_gate = None

    def set_notify_fn(self, fn: Any) -> None:
        self._notify_fn = fn

    def set_photo_fn(self, fn: Any) -> None:
        self._photo_fn = fn

    def set_memory(self, memory: Any) -> None:
        self._memory = memory

    def set_operator_present_fn(self, fn: Optional[Callable[[], bool]]) -> None:
        self._operator_present_fn = fn

    def set_quiet_hours_fn(self, fn: Optional[Callable[[], bool]]) -> None:
        self._quiet_hours_fn = fn

    def maybe_react(self, events: List[Any], now: Optional[float] = None) -> bool:
        """Tick-safe entry point: on salient motion, spawn a describe+notify thread.

        Returns True iff a reaction was started. Cheap and non-blocking -- the
        cooldown + is_alive guards keep it from stacking LLaVA calls, and the
        actual (slow) LLaVA work happens off the tick thread.
        """
        if self._cortex is None or (self._notify_fn is None and self._photo_fn is None):
            return False
        salient_events = [
            e for e in (events or [])
            if getattr(e, "event_type", None) in SALIENT_EVENT_TYPES
        ]
        if not salient_events:
            return False

        # The adapter binds this deterministic caption to the same percept that
        # triggered the motion event. Empty means YOLO saw nothing confidently,
        # so the open-ended VLM remains the honest fallback.
        fast_description = None
        for event in salient_events:
            payload = getattr(event, "payload", None)
            if isinstance(payload, dict) and payload.get("objects_summary"):
                fast_description = str(payload["objects_summary"]).strip()
                break

        now = time.time() if now is None else now
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False

            elapsed = now - self._last_react_ts
            probe = False
            if elapsed < self._cooldown_sec:
                # Inside the cooldown. Normally that is the end of it -- but a
                # time lock cannot tell "the same street again" from "the room
                # now points at someone new", and it silences both. When the
                # gate is armed we spend ~20s asking, instead of ~15min not
                # asking. The gate CANNOT be called here (this runs on the tick
                # thread); the answer is deferred to the background thread and
                # binds there.
                if not self._probe_allowed(now, elapsed):
                    return False
                probe = True
                self._last_gate_probe_ts = now
            else:
                self._last_react_ts = now
                # An ordinary reaction means the clock had its say; the probe
                # budget starts over for the new window.
                self._probe_pings = 0

            # Decide BEFORE spawning whether to record silently (no LLaVA, no
            # ping): either the operator is already present (E3) or it is quiet
            # hours. Inside the lock alongside the other guards so the
            # per-reaction decision is taken atomically.
            suppress = self._should_suppress_ping()
            # Freeze the frame with the triggering YOLO event. A background
            # thread may start after the next tick has replaced the live frame.
            snapshot_image = None
            if fast_description and not suppress:
                image = getattr(self._cortex, "_last_frame_image", None)
                if image is not None:
                    snapshot_image = image.copy()
            self._thread = threading.Thread(
                target=self._describe_and_notify,
                args=(suppress, probe, fast_description, snapshot_image),
                daemon=True, name="VisionAdvisor",
            )
            self._thread.start()
            return True

    def _probe_allowed(self, now: float, elapsed: float) -> bool:
        """May we spend a gate check inside the cooldown window?

        Three guards, because this is the direction that can bring back the ~20
        pings/day the cooldown was raised to stop:

        1. ONLY in gate mode "on". With off/observe the cooldown behaves exactly
           as it always has -- observe must never change behaviour, or it is not
           an observation.
        2. A floor since the last ping: even a genuinely new scene waits this
           long, so a burst cannot become a burst of pings.
        3. A floor since the last probe: motion can fire every detector tick;
           repeated image comparisons must remain bounded too.

        Both floors are the same constant -- one number to reason about.
        """
        try:
            from agent_core.vision.change_gate import gate_mode
            if gate_mode() != "on":
                return self._refused(now, "brama_off", "")
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("VisionAdvisor probe check failed: %s", e)
            return False
        if self._probe_pings >= self._max_probe_pings:
            return self._refused(now, "budzet_wyczerpany",
                                 f"{self._probe_pings}/{self._max_probe_pings}")
        if elapsed < self._gate_probe_sec:
            return self._refused(now, "za_wczesnie_po_pingu",
                                 f"{elapsed:.0f}s < {self._gate_probe_sec:.0f}s")
        since_probe = now - self._last_gate_probe_ts
        if since_probe < self._gate_probe_sec:
            return self._refused(now, "za_wczesnie_po_sondzie",
                                 f"{since_probe:.0f}s < {self._gate_probe_sec:.0f}s")
        return True

    def _refused(self, now: float, category: str, detail: str = "") -> bool:
        """Log WHY a probe was declined, then decline it.

        Refusals used to be silent, which made "there was no motion" and "there
        was motion but I said no" indistinguishable in the journal -- Eryk posed
        in front of the camera and neither of us could tell which had happened.

        INFO, not debug: the daemon runs at INFO, so debug would be invisible
        exactly when it is wanted. Throttled instead, because motion fires every
        tick while anything moves.

        CATEGORY is the throttle key; DETAIL only decorates the message. The
        first version threw the whole formatted string -- numbers included -- at
        the throttle, and the numbers tick: "za_wczesnie_po_pingu (20s < 120s)",
        then 21s, then 22s. Every second looked like a NEW reason, so the
        throttle never fired once: 54 lines, 54 unique strings, one per second.
        A live counter must never sit in a de-duplication key.

        (The unit test missed it by passing a CONSTANT elapsed value in a loop,
        where production has a clock -- the test's conditions did not match
        production's.)
        """
        if (category != self._last_refusal_reason
                or (now - self._last_refusal_log_ts) >= self._gate_probe_sec):
            suffix = f" ({detail})" if detail else ""
            logger.info("[ChangeGate] sonda odrzucona: %s%s", category, suffix)
            self._last_refusal_reason = category
            self._last_refusal_log_ts = now
        return False

    def _should_suppress_ping(self) -> Optional[str]:
        """Return why the ping should be a silent record, or None to ping.

        Two reasons: quiet hours (always applies at night) and operator-present
        (E3, flag-gated). Fail-open -- any error / missing signal -> None (ping
        normally), so vision is never silenced by accident. Quiet hours is
        checked first: night applies regardless of the presence flag.
        """
        if self._quiet_hours_fn is not None:
            try:
                if self._quiet_hours_fn():
                    return "quiet_hours"
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("VisionAdvisor quiet-hours check failed: %s", e)
        if _flag_on(SUPPRESS_WHEN_PRESENT_FLAG) and self._operator_present_fn is not None:
            try:
                if self._operator_present_fn():
                    return "present"
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("VisionAdvisor presence check failed: %s", e)
        return None

    def _build_frame_gate(self):
        """Returns a callable(path) -> bool for describe_snapshot, or None.

        Three modes (VISION_CHANGE_GATE):
          off      -- None, describe_snapshot behaves exactly as before
          observe  -- measure and log, ALWAYS return True. Same behaviour as
                      off, but the journal fills with "would have skipped",
                      which is the data needed before trusting the threshold.
          on       -- act on the verdict.

        Observe DOES advance the gate's reference, exactly as "on" would. The
        first version did not, reasoning that watching must not change what is
        watched -- and that made observe useless: with no reference every frame
        logged "brak_odniesienia" and no similarity was ever computed. Caught by
        running the real path before arming it. The reference is the gate's
        memory; without it there is no measurement, and advancing it is also the
        only way the logged verdicts match what "on" would really have decided.
        """
        from agent_core.vision.change_gate import create_change_gate, gate_mode
        mode = gate_mode()
        if mode == "off":
            return None
        if self._change_gate is None:
            # Configuration/import failures are explicit errors. They must not
            # silently turn an armed gate into an unfiltered description path.
            self._change_gate = create_change_gate()
            logger.info("[ChangeGate] backend=%s", type(self._change_gate).__name__)

        gate, acting = self._change_gate, (mode == "on")

        def _gate(path: str) -> bool:
            # remember=True in BOTH modes: observe has to keep a reference or it
            # measures nothing at all.
            decision = gate.evaluate(path, remember=True)
            logger.info("[ChangeGate] backend=%s tryb=%s %s",
                        type(gate).__name__, mode, decision.to_dict())
            # observe: report, never veto.
            return True if not acting else decision.is_new

        return _gate

    def _arm_cooldown_after_probe(self, probe: bool) -> None:
        """Start the ping cooldown for a probe that actually delivered.

        On the normal path maybe_react already stamped _last_react_ts before
        spawning. A probe deliberately did not: it may find the same scene and
        send nothing, and charging it the full cooldown for looking would mean
        one silent look buys fifteen minutes of silence. So the clock starts
        here instead -- at the moment the operator was really told something.
        """
        if not probe:
            return
        with self._lock:
            self._last_react_ts = time.time()
            self._probe_pings += 1
        logger.info("[VisionAdvisor] probe przebil cooldown -> zegar wystartowany")

    @work_purpose(WorkPurpose.WORLD_EVENT)
    def _describe_and_notify(self, suppress: Optional[str] = None,
                             probe: bool = False,
                             fast_description: Optional[str] = None,
                             snapshot_image: Optional[Any] = None) -> None:
        """Background: YOLO26 or LLaVA description -> photo/caption.

        suppress (str reason, or None to proceed): skip the expensive LLaVA
        describe ENTIRELY and just leave a light trace in VisionMemory, no ping.
        "present" -- the operator is right here (just chatted), so describing is
        redundant. "quiet_hours" -- it is night, no one is watching, and LLaVA
        would only burn CPU. Either way, on this CPU-only box the ~1-2 min
        describe is exactly what we avoid.

        probe: this run started INSIDE the cooldown, so the gate -- not the
        clock -- decides. maybe_react did not touch _last_react_ts for it; the
        cooldown restarts here, and only if something was actually sent. A probe
        that finds the same scene costs one gate check and leaves the clock
        alone, so the next probe may look again in _gate_probe_sec.
        """
        if suppress:
            placeholder = QUIET_PLACEHOLDER if suppress == "quiet_hours" else SILENT_PLACEHOLDER
            if self._memory is not None:
                try:
                    self._memory.record(placeholder, source="motion_suppressed")
                except Exception as e:
                    logger.debug("VisionAdvisor silent record failed: %s", e)
            logger.info("[VisionAdvisor] suppress=%s -> light record only, no describe/ping", suppress)
            return

        try:
            # The public image gate can filter a detector frame directly,
            # without waking a generative vision model.
            from agent_core.vision.change_gate import change_gate_backend
            light_gate = change_gate_backend() == "opencv"
            desc = None
            used_fast_path = bool(fast_description and (not probe or light_gate))
            fast_snapshot_ready = False
            if used_fast_path:
                desc = str(fast_description).strip()
                try:
                    snapshot_args = {} if snapshot_image is None else {"image": snapshot_image}
                    fast_snapshot_ready = bool(
                        self._cortex.save_last_frame(self._snapshot_path, **snapshot_args)
                    )
                except (AttributeError, TypeError):
                    logger.debug("[VisionAdvisor] cortex cannot save last YOLO frame")
                if light_gate:
                    if probe and not fast_snapshot_ready:
                        logger.info("[VisionAdvisor] no fresh probe frame -> no ping")
                        return
                    if fast_snapshot_ready:
                        gate_fn = self._build_frame_gate()
                        if gate_fn is not None and not gate_fn(self._snapshot_path):
                            logger.info("[VisionAdvisor] repeated YOLO frame -> no ping")
                            return
                logger.info("[VisionAdvisor] motion -> YOLO26 fast description")

            if not used_fast_path:
                logger.info("[VisionAdvisor] motion -> running LLaVA describe...")
                # describe_snapshot (NOT describe_scene_llava): isolated LLaVA
                # call that cannot make the tick run LLaVA inline. The kwarg is
                # passed only when the gate is armed for old duck-typed cortexes.
                gate_fn = self._build_frame_gate()
                if gate_fn is None:
                    desc = self._cortex.describe_snapshot(
                        prompt=self._prompt, save_path=self._snapshot_path
                    )
                else:
                    try:
                        desc = self._cortex.describe_snapshot(
                            prompt=self._prompt, save_path=self._snapshot_path,
                            frame_gate=gate_fn,
                        )
                    except TypeError:
                        # An older cortex that cannot gate: describe anyway rather
                        # than lose the ping.
                        logger.warning("[VisionAdvisor] cortex nie wspiera frame_gate "
                                       "-- opisuje bez bramki")
                        desc = self._cortex.describe_snapshot(
                            prompt=self._prompt, save_path=self._snapshot_path
                        )
            if not desc or not str(desc).strip():
                logger.info("[VisionAdvisor] describe returned nothing -> no ping")
                return
            desc = str(desc).strip()
            # LLaVA described in English; render the caption to fluent Polish.
            # Failure/None -> keep the English (honest) rather than block the ping.
            if not used_fast_path and self._translate_fn is not None:
                try:
                    pl = self._translate_fn(desc)
                    if pl and str(pl).strip():
                        desc = str(pl).strip()
                except Exception as e:
                    logger.warning(f"VisionAdvisor translate failed: {e}")
            caption = f"Widzę ruch — {desc}"

            # E1: remember what was seen (the description, sans caption prefix) so
            # SelfContext / chat / /lastseen can answer "co ostatnio widzialas?".
            if self._memory is not None:
                try:
                    self._memory.record(
                        desc, source="motion_yolo26" if used_fast_path else "motion"
                    )
                except Exception as e:
                    logger.debug("VisionAdvisor memory record failed: %s", e)

            # Prefer the photo (operator sees what Maria sees); fall back to text.
            snapshot_ready = os.path.exists(self._snapshot_path) and (
                not used_fast_path or fast_snapshot_ready
            )
            if self._photo_fn is not None and snapshot_ready:
                try:
                    if self._photo_fn(self._snapshot_path, caption):
                        logger.info("[VisionAdvisor] sent photo + caption: %s", caption[:60])
                        self._arm_cooldown_after_probe(probe)
                        return
                    logger.warning("[VisionAdvisor] photo send failed -> text fallback")
                except Exception as e:
                    logger.warning(f"VisionAdvisor photo failed: {e}")

            if self._notify_fn is not None:
                try:
                    self._notify_fn(caption)
                    logger.info("[VisionAdvisor] sent text ping: %s", caption[:60])
                    self._arm_cooldown_after_probe(probe)
                except Exception as e:
                    logger.warning(f"VisionAdvisor notify failed: {e}")
        except Exception as e:
            logger.warning(f"VisionAdvisor describe failed: {e}", exc_info=True)
