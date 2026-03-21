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
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil

try:
    import ollama as ollama_lib
except ImportError:
    ollama_lib = None

from .model_registry import (
    ModelRole, ModelSpec, ConcurrencyClass, WarmState,
    get_model, get_heavy_models, list_models,
    RAM_EMERGENCY_FREE, LATENCY_UNHEALTHY_COUNT,
)

logger = logging.getLogger(__name__)


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

        # Triage not yet configured
        if spec.ollama_tag == "TBD":
            return self._try_fallback(spec, start, "Triage not yet configured")

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
            try:
                result = self._do_load(spec, start)
            finally:
                # Release mutex only if load failed
                # On success, mutex stays held until release() is called
                if not result.success:
                    self._heavy_lock.release()
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
            try:
                self._heavy_lock.release()
            except RuntimeError:
                pass  # Already released

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

        # Release heavy mutex if needed
        spec = get_model(role)
        if spec and spec.concurrency_class == ConcurrencyClass.HEAVY:
            try:
                self._heavy_lock.release()
            except RuntimeError:
                pass

        return success

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
        if ollama_lib is None:
            logger.warning("[ModelScheduler] ollama library not available")
            return False

        try:
            ollama_lib.generate(
                model=ollama_tag,
                prompt=" ",
                options={"num_predict": 1},
                keep_alive="10m",
            )
            return True
        except Exception as e:
            logger.warning(f"[ModelScheduler] Failed to load {ollama_tag}: {e}")
            return False

    def _ollama_unload(self, ollama_tag: str) -> bool:
        """
        Unload a model from Ollama memory.

        Uses ollama.generate with keep_alive=0 to release memory.

        Returns:
            True if unloaded successfully
        """
        if ollama_lib is None:
            return False

        try:
            ollama_lib.generate(
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
        if ollama_lib is None:
            return []

        try:
            result = ollama_lib.ps()
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
