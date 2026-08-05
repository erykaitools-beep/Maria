"""
Model Scheduler - Manages Ollama model lifecycle for multi-organ stack.

Handles: loading, unloading, idle timeout, RAM budget, heavy-model mutex.
Thread-safe. Called from homeostasis tick loop (~1Hz).

Design:
- ensure_ready(role) is the single entry point for model access
- tick() manages idle timeouts and RAM pressure
- Heavy mutex prevents PLANNER and CODER from running simultaneously
- RAM guard checks psutil.virtual_memory() before loading
"""

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil
import requests

try:
    import ollama as ollama_lib
except ImportError:
    ollama_lib = None

# Timeout-aware client. load/unload/ps run synchronously on the homeostasis tick
# thread (Phase 9.5); with the bare module client (timeout=None) a wedged Ollama
# would block the main loop forever (2026-06-02 freeze class). The shared client's
# httpx read-timeout bounds them so a stall raises instead of hanging the tick.
from .execution_budget import get_ollama_client
from .local_compute import (
    LocalComputeBlocked,
    get_local_compute_coordinator,
)

from .model_registry import (
    ModelRole, ModelSpec, ConcurrencyClass, WarmState,
    get_model, get_heavy_models,
    RAM_EMERGENCY_FREE, LATENCY_UNHEALTHY_COUNT,
)

logger = logging.getLogger(__name__)

# How long a heavy_lease() caller waits for the mutex before giving up.
#
# INVARIANT: this MUST be >= the longest possible HOLD of _heavy_lock, or the
# lease degrades into its fail-open branch and lets a second heavy local model
# onto this GPU-less CPU -- precisely the 447s contention storm the mutex exists
# to prevent. The old default of 120s violated that invariant on day one: the
# synthesis faithfulness judge holds the lease for its own 540s budget PLUS an
# in-lease warm-up of up to 120s, so every competitor timed out and proceeded
# UNGUARDED. The failure was invisible: fail-open only logs a WARNING.
#
# Waiting is safe here -- all five call sites (learning fallback, exam answer,
# exam grader, synthesis answer, synthesis faithfulness) run on transient
# threads (teacher, planner, telegram poll), never on the tick thread, so a
# long wait cannot starve the tick or trip TickWatchdog.
_LONGEST_HEAVY_HOLD_S = 540.0 + 120.0   # faithfulness judge budget + in-lease warm-up
HEAVY_LEASE_ACQUIRE_S = _LONGEST_HEAVY_HOLD_S + 60.0


def _mutex_enforced() -> bool:
    """Whether heavy_lease() actively serializes (env flag, default OFF).

    Ships inert so the lease wiring lands as a no-op and is enabled + OBSERVED
    in production before becoming the default (rollout guardrail: flag -> observe
    -> cutover). Set SCHEDULER_ENFORCE_MUTEX=1 (and restart) to activate.
    """
    return os.environ.get("SCHEDULER_ENFORCE_MUTEX", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


@dataclass
class LoadedModel:
    """Tracks a currently loaded model in Ollama."""
    role: ModelRole
    ollama_tag: str
    loaded_at: float           # time.time() when loaded
    last_used: float           # time.time() of last request
    latency_violations: int = 0
    total_requests: int = 0
    healthy: bool = True


@dataclass
class EnsureResult:
    """Result of ensure_ready() call."""
    success: bool
    ollama_tag: str = ""
    role: ModelRole = ModelRole.EXECUTOR
    fallback_used: bool = False
    reason: str = ""
    wait_time_s: float = 0.0


# Health save interval (in ticks, ~1Hz)
_HEALTH_SAVE_INTERVAL = 60


class ModelScheduler:
    """
    Manages Ollama model lifecycle: load, unload, idle tracking, RAM guard.

    Thread-safe. Uses threading.Lock for state mutations and
    threading.Lock as heavy-model mutex (PLANNER/CODER never simultaneous).
    """

    def __init__(self, health_path: Optional[str] = None):
        self._loaded: Dict[ModelRole, LoadedModel] = {}
        self._lock = threading.Lock()
        self._heavy_lock = threading.Lock()
        # Thread that currently holds _heavy_lock, or None.
        #
        # threading.Lock has NO owner: release() from a thread that never
        # acquired it SUCCEEDS. release() and force_unload() released the heavy
        # mutex unconditionally for HEAVY roles, so the tick thread's idle
        # sweep, or any router finally-block, could free a lock held by the
        # learning/exam thread mid-inference. The invariant "at most one heavy
        # local model at a time" therefore never actually held -- and because
        # nobody ever waited, the fail-open warning never fired either. Observed
        # 2026-07-26: three runners at once, 388% + 233% + 99% CPU, 15.3 GB RSS.
        self._heavy_owner: Optional[int] = None
        # Per-thread reentrancy flag for heavy_lease(): _heavy_lock is a plain
        # (non-reentrant) Lock, so a lease nested inside another lease on the
        # SAME thread must skip re-acquiring instead of self-deadlocking.
        self._lease_local = threading.local()

        self._health_path = Path(health_path or "meta_data/model_health.json")
        self._tick_count = 0
        self._ram_pressure_events = 0
        self._incidents: List[Dict] = []

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def ensure_ready(
        self, role: ModelRole, timeout_s: float = 60.0
    ) -> EnsureResult:
        """
        Ensure a model for the given role is loaded and ready.

        1. If already loaded and healthy -> return OK
        2. Check RAM budget
        3. Check heavy mutex
        4. Try to free RAM if needed
        5. Load via Ollama
        6. If load fails -> try fallback role

        Args:
            role: Which model role is needed
            timeout_s: Max time to wait for loading

        Returns:
            EnsureResult with status and actual model tag
        """
        start = time.time()
        spec = get_model(role)

        if spec is None:
            return EnsureResult(
                success=False, reason=f"Unknown role: {role.value}"
            )

        # External models (NIM) are always "ready" - handled by NIMClient
        if spec.warm_state == WarmState.EXTERNAL:
            return EnsureResult(
                success=True, ollama_tag="", role=role,
                reason="External model (NIM)"
            )

        # Model without ollama_tag (rule-based triage or unconfigured)
        if not spec.ollama_tag:
            if spec.fallback_role is not None:
                return self._try_fallback(spec, start, "No ollama_tag configured")
            # Rule-based (no fallback needed) - always ready
            return EnsureResult(
                success=True, ollama_tag="", role=role,
                reason="Rule-based (no model needed)",
                wait_time_s=time.time() - start,
            )

        # Thermal cooling is fail-closed.  Do not turn a rejected role into a
        # second local-model fallback: every Ollama role shares the same CPU.
        if get_local_compute_coordinator().cooling:
            return EnsureResult(
                success=False,
                role=role,
                reason="Thermal cooling active; local model load blocked",
                wait_time_s=time.time() - start,
            )

        # Already loaded and healthy?
        with self._lock:
            loaded = self._loaded.get(role)
            if loaded and loaded.healthy:
                loaded.last_used = time.time()
                return EnsureResult(
                    success=True, ollama_tag=loaded.ollama_tag, role=role,
                    reason="Already loaded",
                    wait_time_s=time.time() - start,
                )

        # Can we load it?
        can_load, reason = self._can_load(spec)
        if not can_load:
            # Try freeing RAM first
            if "RAM" in reason:
                freed = self._try_free_ram(spec.ram_estimate_gb)
                if freed:
                    can_load, reason = self._can_load(spec)

            if not can_load:
                return self._try_fallback(spec, start, reason)

        # Heavy model mutex
        if spec.concurrency_class == ConcurrencyClass.HEAVY:
            acquired = self._heavy_lock.acquire(timeout=timeout_s)
            if not acquired:
                return self._try_fallback(
                    spec, start, "Heavy mutex timeout"
                )
            self._claim_heavy()
            try:
                result = self._do_load(spec, start)
            finally:
                # Release mutex only if load failed
                # On success, mutex stays held until release() is called
                if not result.success:
                    self._release_heavy_if_owner("ensure_ready")
            return result
        else:
            return self._do_load(spec, start)

    def release(self, role: ModelRole) -> None:
        """
        Mark model as no longer actively needed.

        Resets idle timer. For heavy models, releases the heavy mutex.
        """
        with self._lock:
            loaded = self._loaded.get(role)
            if loaded:
                loaded.last_used = time.time()

        spec = get_model(role)
        if spec and spec.concurrency_class == ConcurrencyClass.HEAVY:
            self._release_heavy_if_owner("release")

    def _claim_heavy(self) -> None:
        """Record this thread as the heavy-mutex owner. Call right AFTER acquire."""
        self._heavy_owner = threading.get_ident()

    def _release_heavy_if_owner(self, who: str) -> bool:
        """Release the heavy mutex only if THIS thread holds it.

        Returns True if released. A foreign-thread attempt is refused and logged
        instead of silently stealing the lock from an in-flight inference.
        """
        me = threading.get_ident()
        if self._heavy_owner != me:
            if self._heavy_owner is not None:
                logger.warning(
                    "[ModelScheduler] %s tried to release the heavy mutex held "
                    "by another thread (owner=%s, caller=%s) -- refused",
                    who, self._heavy_owner, me,
                )
            return False
        # Clear ownership BEFORE unlocking: once the lock is free another thread
        # may claim it immediately, and clearing afterwards would erase its mark.
        self._heavy_owner = None
        try:
            self._heavy_lock.release()
        except RuntimeError:
            pass  # already released
        return True

    @contextmanager
    def heavy_lease(self, label: str = "", timeout_s: float = HEAVY_LEASE_ACQUIRE_S):
        """Serialize a heavy LOCAL inference that calls Ollama OUTSIDE ask_as_role().

        ensure_ready()/ask_as_role() hold _heavy_lock across inference so two heavy
        local models never share the GPU-less CPU (invariant: <=1 LOCAL_HEAVY at a
        time -- the cure for the contention storms). But the heavy paths that call
        Ollama directly -- the exam STUDENT answer, the exam author/grader local
        fallback, and the learn/_ask_once local fallback -- bypassed that lock and
        so could run a second heavy model concurrently (the confirmed 447s-storm
        mechanism: teacher-thread exam answer || planner-thread K12, both heavy
        local, no shared lock). This context manager wraps those direct calls in
        the SAME _heavy_lock, so they serialize against every other heavy local
        caller. NIM (off-CPU/EXTERNAL) and light (nomic embed) paths must NOT use
        it -- they are meant to run in parallel.

        Behavior:
        - No-op (just yields) unless SCHEDULER_ENFORCE_MUTEX is set, so the wiring
          ships inert and is enabled + observed before cutover.
        - Reentrant-safe: a lease already held on THIS thread yields without
          re-acquiring (the non-reentrant Lock would otherwise self-deadlock).
        - Degrades on timeout: if the mutex cannot be acquired within timeout_s it
          logs a WARNING and proceeds UNGUARDED rather than blocking the tick/
          teacher thread forever. A residual overlap is logged, never a deadlock.
        """
        if not _mutex_enforced():
            yield
            return

        # Reentrancy: a heavy_lease already active on this thread holds the lock.
        if getattr(self._lease_local, "held", False):
            yield
            return

        t0 = time.time()
        acquired = self._heavy_lock.acquire(timeout=timeout_s)
        if not acquired:
            logger.warning(
                "[ModelScheduler] heavy_lease(%s) could not acquire mutex in %.0fs "
                "-> proceeding UNGUARDED (heavy overlap possible)",
                label or "?", timeout_s,
            )
            yield
            return

        waited = time.time() - t0
        self._lease_local.held = True
        self._claim_heavy()
        if waited > 0.5:
            # The OBSERVED signal: this heavy local waited for another to finish
            # instead of thrashing the CPU -- proof the mutex prevented an overlap.
            logger.info(
                "[ModelScheduler] heavy_lease(%s) waited %.1fs for mutex "
                "(serialized -- prevented CPU overlap)",
                label or "?", waited,
            )
        try:
            yield
        finally:
            self._lease_local.held = False
            self._release_heavy_if_owner("heavy_lease")

    def force_unload(self, role: ModelRole) -> bool:
        """
        Force unload a model from Ollama.

        Args:
            role: Role to unload

        Returns:
            True if unloaded successfully
        """
        with self._lock:
            loaded = self._loaded.pop(role, None)

        if loaded is None:
            return False

        success = self._ollama_unload(loaded.ollama_tag)
        if success:
            logger.info(f"[ModelScheduler] Unloaded {role.value} ({loaded.ollama_tag})")

        # Release heavy mutex if needed. force_unload() is called from the TICK
        # thread's idle sweep, so this is the main place the lock used to be
        # stolen from an in-flight learning/exam inference.
        spec = get_model(role)
        if spec and spec.concurrency_class == ConcurrencyClass.HEAVY:
            self._release_heavy_if_owner("force_unload")

        return success

    def emergency_unload_all(self) -> Dict[str, List[str]]:
        """Best-effort unload of every model Maria may have loaded locally.

        Thermal handling runs on the 1 Hz tick, so it must not inherit the
        normal 240-second Ollama read timeout.  Short, parallel control calls
        bound the whole action to roughly six seconds even when Ollama is busy.
        The coordinator has already rejected new inference before this runs.
        """
        with self._lock:
            tags = {loaded.ollama_tag for loaded in self._loaded.values()}
            self._loaded.clear()

        # Direct learning, embedding, and vision calls bypass the scheduler's
        # registry, but the process-wide lease records whichever one is active.
        active_model = get_local_compute_coordinator().snapshot().get("active_model")
        if active_model:
            tags.add(str(active_model))

        # Include other models that are genuinely resident. Never issue unload
        # calls for every registry tag: Ollama may load a cold model in order to
        # honour such a request, which is the opposite of an emergency stop.
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            response = requests.get(
                f"{base_url.rstrip('/')}/api/ps",
                timeout=(1.0, 2.0),
            )
            if response.status_code == 200:
                for item in response.json().get("models", []):
                    tag = item.get("name") or item.get("model")
                    if tag:
                        tags.add(str(tag))
        except Exception as exc:
            logger.warning("[ModelScheduler] Emergency /api/ps failed: %s", exc)

        tags = {tag for tag in tags if tag}

        results: Dict[str, bool] = {}
        results_lock = threading.Lock()

        def _stop(tag: str) -> None:
            ok = self._ollama_unload(tag, emergency=True)
            with results_lock:
                results[tag] = ok

        threads = [
            threading.Thread(
                target=_stop,
                args=(tag,),
                name=f"thermal-unload-{tag}",
                daemon=True,
            )
            for tag in sorted(tags)
        ]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 6.0
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

        requested = sorted(tags)
        unloaded = sorted(tag for tag, ok in results.items() if ok)
        failed = sorted(tag for tag in tags if not results.get(tag, False))
        logger.warning(
            "[ModelScheduler] Thermal unload requested=%s unloaded=%s failed=%s",
            requested, unloaded, failed,
        )
        return {"requested": requested, "unloaded": unloaded, "failed": failed}

    def record_request(self, role: ModelRole, latency_s: float) -> None:
        """
        Record a completed request for health tracking.

        Marks model unhealthy after LATENCY_UNHEALTHY_COUNT violations.
        """
        spec = get_model(role)
        if spec is None:
            return

        with self._lock:
            loaded = self._loaded.get(role)
            if loaded is None:
                return

            loaded.total_requests += 1
            loaded.last_used = time.time()

            if latency_s > spec.latency_budget_s:
                loaded.latency_violations += 1
                if loaded.latency_violations >= LATENCY_UNHEALTHY_COUNT:
                    loaded.healthy = False
                    logger.warning(
                        f"[ModelScheduler] {role.value} marked unhealthy "
                        f"({loaded.latency_violations} latency violations)"
                    )

    # ------------------------------------------------------------------
    # Tick (called from homeostasis ~1Hz)
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """
        Periodic maintenance. Called from homeostasis tick loop.

        - Check idle timeouts, unload expired models
        - Check RAM pressure, emergency unload if needed
        - Save health periodically
        """
        self._tick_count += 1

        self._check_idle_timeouts()
        self._check_ram_pressure()

        if self._tick_count % _HEALTH_SAVE_INTERVAL == 0:
            self.save_health()

    def _check_idle_timeouts(self) -> None:
        """Unload models that have been idle longer than their timeout."""
        now = time.time()
        to_unload = []

        with self._lock:
            for role, loaded in self._loaded.items():
                spec = get_model(role)
                if spec is None:
                    continue

                # Warm models don't idle-unload
                if spec.idle_unload_s <= 0:
                    continue

                idle_s = now - loaded.last_used
                if idle_s > spec.idle_unload_s:
                    to_unload.append(role)

        for role in to_unload:
            logger.info(f"[ModelScheduler] Idle timeout: unloading {role.value}")
            self.force_unload(role)

    def _check_ram_pressure(self) -> None:
        """Emergency unload if free RAM drops below threshold."""
        free_gb = self._get_free_ram_gb()
        if free_gb >= RAM_EMERGENCY_FREE:
            return

        self._ram_pressure_events += 1
        logger.warning(
            f"[ModelScheduler] RAM pressure! Free: {free_gb:.1f} GB "
            f"(threshold: {RAM_EMERGENCY_FREE} GB)"
        )

        # Unload cold models, prioritize by longest idle
        self._try_free_ram(RAM_EMERGENCY_FREE - free_gb)

    # ------------------------------------------------------------------
    # RAM management
    # ------------------------------------------------------------------

    def _get_free_ram_gb(self) -> float:
        """Get current free RAM in GB."""
        mem = psutil.virtual_memory()
        return mem.available / (1024 ** 3)

    def _get_total_loaded_ram_gb(self) -> float:
        """Sum of ram_estimate_gb for all loaded models."""
        total = 0.0
        with self._lock:
            for role in self._loaded:
                spec = get_model(role)
                if spec:
                    total += spec.ram_estimate_gb
        return total

    def _can_load(self, spec: ModelSpec) -> Tuple[bool, str]:
        """
        Check if a model can be loaded safely.

        Returns:
            (ok, reason) tuple
        """
        # External models don't need RAM
        if spec.warm_state == WarmState.EXTERNAL:
            return True, "External"

        # Check free RAM
        free_gb = self._get_free_ram_gb()
        if free_gb < spec.min_free_ram_gb:
            return False, (
                f"RAM insufficient: {free_gb:.1f} GB free, "
                f"need {spec.min_free_ram_gb} GB"
            )

        # Check heavy mutex
        if spec.block_if_heavy_active:
            with self._lock:
                for role, loaded in self._loaded.items():
                    other_spec = get_model(role)
                    if (other_spec and
                            other_spec.concurrency_class == ConcurrencyClass.HEAVY and
                            role != spec.role):
                        return False, (
                            f"Heavy model {role.value} already active "
                            f"(mutex conflict)"
                        )

        return True, "OK"

    def _try_free_ram(self, needed_gb: float) -> bool:
        """
        Try to free RAM by unloading idle cold models.

        Priority: MEMORY first (background), then longest-idle cold model.

        Returns:
            True if enough RAM was freed
        """
        freed = 0.0

        # Collect unload candidates (cold models only, sorted by idle time)
        candidates = []
        now = time.time()
        with self._lock:
            for role, loaded in self._loaded.items():
                spec = get_model(role)
                if spec is None:
                    continue
                # Don't unload warm models unless emergency
                if spec.warm_state == WarmState.WARM:
                    continue
                idle_s = now - loaded.last_used
                candidates.append((role, spec.ram_estimate_gb, idle_s))

        # Sort: MEMORY/BACKGROUND first, then by longest idle
        candidates.sort(key=lambda x: (-x[2],))  # longest idle first

        for role, ram_gb, _ in candidates:
            if freed >= needed_gb:
                break
            if self.force_unload(role):
                freed += ram_gb

        return freed >= needed_gb

    # ------------------------------------------------------------------
    # Ollama integration
    # ------------------------------------------------------------------

    def _ollama_load(self, ollama_tag: str) -> bool:
        """
        Load a model into Ollama memory.

        Uses ollama.generate with keep_alive to force model loading.

        Returns:
            True if loaded successfully
        """
        client = get_ollama_client()
        if client is None:
            logger.warning("[ModelScheduler] ollama library not available")
            return False

        try:
            with get_local_compute_coordinator().lease(
                "model_load", model=ollama_tag, timeout_s=60.0,
            ):
                client.generate(
                    model=ollama_tag,
                    prompt=" ",
                    options={"num_predict": 1},
                    keep_alive="10m",
                )
            return True
        except LocalComputeBlocked as e:
            logger.info("[ModelScheduler] Load blocked for %s: %s", ollama_tag, e)
            return False
        except Exception as e:
            logger.warning(f"[ModelScheduler] Failed to load {ollama_tag}: {e}")
            return False

    def _ollama_unload(self, ollama_tag: str, emergency: bool = False) -> bool:
        """
        Unload a model from Ollama memory.

        Uses ollama.generate with keep_alive=0 to release memory.

        Returns:
            True if unloaded successfully
        """
        if emergency:
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
            try:
                response = requests.post(
                    f"{base_url.rstrip('/')}/api/generate",
                    json={
                        "model": ollama_tag,
                        "prompt": "",
                        "stream": False,
                        "keep_alive": 0,
                        "options": {"num_predict": 1},
                    },
                    timeout=(1.0, 5.0),
                )
                return response.status_code == 200
            except Exception as e:
                logger.warning(
                    "[ModelScheduler] Emergency unload failed for %s: %s",
                    ollama_tag, e,
                )
                return False

        client = get_ollama_client()
        if client is None:
            return False

        try:
            client.generate(
                model=ollama_tag,
                prompt="",
                options={"num_predict": 1},
                keep_alive="0",
            )
            return True
        except Exception as e:
            logger.warning(f"[ModelScheduler] Failed to unload {ollama_tag}: {e}")
            return False

    def _ollama_list_running(self) -> List[str]:
        """List currently running models in Ollama."""
        client = get_ollama_client()
        if client is None:
            return []

        try:
            result = client.ps()
            models = result.get("models", [])
            return [m.get("name", "") for m in models if m.get("name")]
        except Exception as e:
            logger.debug(f"[ModelScheduler] ps() failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_load(self, spec: ModelSpec, start_time: float) -> EnsureResult:
        """Actually load a model via Ollama."""
        success = self._ollama_load(spec.ollama_tag)
        now = time.time()

        if not success:
            return self._try_fallback(
                spec, start_time, f"Ollama load failed for {spec.ollama_tag}"
            )

        with self._lock:
            self._loaded[spec.role] = LoadedModel(
                role=spec.role,
                ollama_tag=spec.ollama_tag,
                loaded_at=now,
                last_used=now,
            )

        logger.info(
            f"[ModelScheduler] Loaded {spec.role.value} "
            f"({spec.ollama_tag}, ~{spec.ram_estimate_gb}GB)"
        )

        return EnsureResult(
            success=True,
            ollama_tag=spec.ollama_tag,
            role=spec.role,
            reason="Loaded on demand",
            wait_time_s=now - start_time,
        )

    def _try_fallback(
        self, spec: ModelSpec, start_time: float, reason: str
    ) -> EnsureResult:
        """Try loading the fallback model for a role."""
        if spec.fallback_role is None:
            return EnsureResult(
                success=False, role=spec.role,
                reason=f"{reason} (no fallback)",
                wait_time_s=time.time() - start_time,
            )

        fallback_spec = get_model(spec.fallback_role)
        if fallback_spec is None:
            return EnsureResult(
                success=False, role=spec.role,
                reason=f"{reason} (fallback {spec.fallback_role.value} not found)",
                wait_time_s=time.time() - start_time,
            )

        # Check if fallback is already loaded
        with self._lock:
            loaded = self._loaded.get(spec.fallback_role)
            if loaded and loaded.healthy:
                loaded.last_used = time.time()
                return EnsureResult(
                    success=True,
                    ollama_tag=loaded.ollama_tag,
                    role=spec.fallback_role,
                    fallback_used=True,
                    reason=f"{reason} -> fallback to {spec.fallback_role.value}",
                    wait_time_s=time.time() - start_time,
                )

        # Try loading fallback
        fb_result = self._do_load(fallback_spec, start_time)
        if fb_result.success:
            fb_result.fallback_used = True
            fb_result.reason = (
                f"{reason} -> fallback to {spec.fallback_role.value}"
            )
        return fb_result

    # ------------------------------------------------------------------
    # Status & health
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Full status dict for REPL/Web UI/homeostasis."""
        with self._lock:
            loaded_info = {}
            for role, lm in self._loaded.items():
                spec = get_model(role)
                loaded_info[role.value] = {
                    "ollama_tag": lm.ollama_tag,
                    "loaded_at": lm.loaded_at,
                    "last_used": lm.last_used,
                    "idle_s": round(time.time() - lm.last_used, 1),
                    "total_requests": lm.total_requests,
                    "latency_violations": lm.latency_violations,
                    "healthy": lm.healthy,
                    "ram_estimate_gb": spec.ram_estimate_gb if spec else 0,
                }

        return {
            "loaded_models": loaded_info,
            "loaded_count": len(loaded_info),
            "total_loaded_ram_gb": self._get_total_loaded_ram_gb(),
            "free_ram_gb": round(self._get_free_ram_gb(), 1),
            "ram_pressure_events": self._ram_pressure_events,
            "tick_count": self._tick_count,
        }

    def get_health_metrics(self) -> Dict:
        """Metrics for homeostasis sensor integration."""
        with self._lock:
            models = {
                role.value: {
                    "healthy": lm.healthy,
                    "requests": lm.total_requests,
                    "violations": lm.latency_violations,
                }
                for role, lm in self._loaded.items()
            }

        return {
            "models": models,
            "loaded_count": len(models),
            "ram_pressure_events": self._ram_pressure_events,
            "free_ram_gb": round(self._get_free_ram_gb(), 1),
        }

    def save_health(self) -> None:
        """Persist model health to JSON."""
        data = {
            "last_updated": time.time(),
            "ram_pressure_events": self._ram_pressure_events,
            "models": {},
        }

        with self._lock:
            for role, lm in self._loaded.items():
                data["models"][role.value] = {
                    "ollama_tag": lm.ollama_tag,
                    "total_requests": lm.total_requests,
                    "latency_violations": lm.latency_violations,
                    "healthy": lm.healthy,
                    "loaded_at": lm.loaded_at,
                }

        try:
            self._health_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._health_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"[ModelScheduler] Failed to save health: {e}")

    def load_health(self) -> None:
        """Restore model health from JSON on startup."""
        if not self._health_path.exists():
            return

        try:
            with open(self._health_path, "r") as f:
                data = json.load(f)
            self._ram_pressure_events = data.get("ram_pressure_events", 0)
            logger.info(
                f"[ModelScheduler] Health loaded "
                f"(ram_pressure_events={self._ram_pressure_events})"
            )
        except Exception as e:
            logger.warning(f"[ModelScheduler] Failed to load health: {e}")

    def register_running_model(self, role: ModelRole, ollama_tag: str) -> None:
        """
        Register a model that is already running in Ollama.

        Used during startup to register MODEL-02 (EXECUTOR) which
        is loaded by OllamaBrain before the scheduler is created.
        """
        now = time.time()
        with self._lock:
            self._loaded[role] = LoadedModel(
                role=role,
                ollama_tag=ollama_tag,
                loaded_at=now,
                last_used=now,
            )
        logger.info(
            f"[ModelScheduler] Registered running model: "
            f"{role.value} ({ollama_tag})"
        )
