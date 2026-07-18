#!/usr/bin/env python3
"""M.A.R.I.A. Daemon - headless mode z pelnym pipeline K1-K5.1.

Uruchamia homeostasis tick loop (1Hz) z:
- Perception (K1), Sandbox (K2), Goals (K3), Evaluation (K4)
- Planner (K5) + Topic-Aware Learning (K5.1)
- Consciousness (osobowosc, sny, pamiec)
- Teacher (autonomiczna nauka przy idle)

Usage:
    python run_maria.py

Note: the shipped systemd unit (scripts/maria.service) runs the unified
launcher `maria.py`; run_maria.py is a headless development entry point.
Signals: SIGTERM/SIGINT -> graceful shutdown
"""

import os
import sys
import signal
import logging
import threading
import time
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

# Logging (journald-friendly)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("maria.daemon")

# Shutdown event - interruptible by signals
_shutdown = threading.Event()


def _graceful_shutdown(ctx, registry):
    """Cleanup: consciousness checkpoint + module cleanup."""
    logger.info("Graceful shutdown starting...")

    # Stop homeostasis loop
    if ctx.homeostasis_core:
        ctx.homeostasis_core.stop(reason="daemon_shutdown")

    # Consciousness checkpoint
    summary = "Daemon session"
    if ctx.conversation_memory and ctx.conversation_memory.get_session_turn_count() > 0:
        try:
            condense_brain = getattr(ctx.brain, 'ollama', ctx.brain)
            condensed = ctx.conversation_memory.condense_session(condense_brain)
            if condensed:
                ctx.conversation_memory.save_summary(condensed)
                summary = condensed.get("summary", summary)
        except Exception as e:
            logger.warning(f"Condensation failed: {e}")

    if ctx.consciousness:
        try:
            ctx.consciousness.checkpoint(summary=summary)
            logger.info(f"Consciousness checkpoint: {summary}")
        except Exception as e:
            logger.warning(f"Consciousness checkpoint failed: {e}")

    # Module cleanup
    registry.cleanup_all()
    logger.info("Daemon stopped")


def main():
    from main import init_brain, register_modules
    from agent_core.registry import ModuleRegistry

    logger.info("M.A.R.I.A. Daemon starting...")

    # 1. Initialize (same as REPL)
    ctx = init_brain()
    logger.info(f"Brain initialized: {ctx.brain_model}")

    registry = ModuleRegistry()
    register_modules(registry)
    registry.init_all(ctx)
    logger.info("All modules initialized")

    # 2. Signal handlers
    def on_signal(signum, frame):
        logger.info(f"Signal {signum} received")
        _shutdown.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    # 3. Verify homeostasis core
    if not ctx.homeostasis_core:
        logger.error("HomeostasisCore not initialized - cannot run daemon")
        registry.cleanup_all()
        sys.exit(1)

    # 4. Run homeostasis loop (blocks until shutdown)
    logger.info("Starting homeostasis tick loop...")

    core = ctx.homeostasis_core
    core._running = True

    while not _shutdown.is_set():
        try:
            tick_start = time.time()
            core._execute_tick()
            core._tick_count += 1

            tick_duration = time.time() - tick_start
            remaining = core.TICK_INTERVAL_SEC - tick_duration
            if remaining > 0:
                _shutdown.wait(timeout=remaining)
            elif tick_duration > core.TICK_WARNING_THRESHOLD_SEC:
                logger.warning(f"Tick overrun: {tick_duration:.2f}s")
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
            _shutdown.wait(timeout=core.TICK_INTERVAL_SEC)

    # 5. Cleanup
    _graceful_shutdown(ctx, registry)


if __name__ == "__main__":
    main()
