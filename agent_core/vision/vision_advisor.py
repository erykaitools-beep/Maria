"""
VisionAdvisor -- "Maria reacts to what she sees".

When the camera detects real (non-ambient) motion, Maria runs LLaVA in a
BACKGROUND THREAD to describe the scene, then proactively sends the operator
the photo + a short description so they can SEE what she sees.

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
DEFAULT_COOLDOWN_SEC = 180.0

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
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

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
        if not any(
            getattr(e, "event_type", None) in SALIENT_EVENT_TYPES
            for e in (events or [])
        ):
            return False

        now = time.time() if now is None else now
        with self._lock:
            if now - self._last_react_ts < self._cooldown_sec:
                return False
            if self._thread is not None and self._thread.is_alive():
                return False
            self._last_react_ts = now
            # Decide BEFORE spawning whether to record silently (no LLaVA, no
            # ping): either the operator is already present (E3) or it is quiet
            # hours. Inside the lock alongside the other guards so the
            # per-reaction decision is taken atomically.
            suppress = self._should_suppress_ping()
            self._thread = threading.Thread(
                target=self._describe_and_notify, args=(suppress,),
                daemon=True, name="VisionAdvisor",
            )
            self._thread.start()
            return True

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

    def _describe_and_notify(self, suppress: Optional[str] = None) -> None:
        """Background: LLaVA scene description -> photo + caption to operator.

        suppress (str reason, or None to proceed): skip the expensive LLaVA
        describe ENTIRELY and just leave a light trace in VisionMemory, no ping.
        "present" -- the operator is right here (just chatted), so describing is
        redundant. "quiet_hours" -- it is night, no one is watching, and LLaVA
        would only burn CPU. Either way, on this CPU-only box the ~1-2 min
        describe is exactly what we avoid.
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
            logger.info("[VisionAdvisor] motion -> running LLaVA describe...")
            # describe_snapshot (NOT describe_scene_llava): isolated LLaVA call
            # that does not mutate the shared SceneModule, so it can't make the
            # tick run LLaVA inline (tick_overrun). It also saves the frame.
            desc = self._cortex.describe_snapshot(
                prompt=self._prompt, save_path=self._snapshot_path
            )
            if not desc or not str(desc).strip():
                logger.info("[VisionAdvisor] describe returned nothing -> no ping")
                return
            desc = str(desc).strip()
            # LLaVA described in English; render the caption to fluent Polish.
            # Failure/None -> keep the English (honest) rather than block the ping.
            if self._translate_fn is not None:
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
                    self._memory.record(desc, source="motion")
                except Exception as e:
                    logger.debug("VisionAdvisor memory record failed: %s", e)

            # Prefer the photo (operator sees what Maria sees); fall back to text.
            if self._photo_fn is not None and os.path.exists(self._snapshot_path):
                try:
                    if self._photo_fn(self._snapshot_path, caption):
                        logger.info("[VisionAdvisor] sent photo + caption: %s", caption[:60])
                        return
                    logger.warning("[VisionAdvisor] photo send failed -> text fallback")
                except Exception as e:
                    logger.warning(f"VisionAdvisor photo failed: {e}")

            if self._notify_fn is not None:
                try:
                    self._notify_fn(caption)
                    logger.info("[VisionAdvisor] sent text ping: %s", caption[:60])
                except Exception as e:
                    logger.warning(f"VisionAdvisor notify failed: {e}")
        except Exception as e:
            logger.warning(f"VisionAdvisor describe failed: {e}", exc_info=True)
