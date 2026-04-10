#!/usr/bin/env python3
"""M.A.R.I.A. - Unified Launcher (V3 Phase A, Module 1)

Single entry point for the entire M.A.R.I.A. system.
Starts daemon (homeostasis tick loop) + Web UI in one process.

Usage:
    python maria.py              # Full system (daemon + Web UI)
    python maria.py --daemon     # Daemon only (no Web UI)
    python maria.py --ui         # Web UI only (no daemon)
    python maria.py --check      # Environment check only

Systemd: maria.service (replaces separate maria + maria-ui services)
Signals: SIGTERM/SIGINT -> graceful shutdown
"""

import os
import sys
import signal
import logging
import threading
import time
import argparse
from pathlib import Path

# ── Paths ──
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("maria")

# ── Shutdown ──
_shutdown = threading.Event()


# ====================================================================
# ENVIRONMENT CHECKS
# ====================================================================

def check_environment():
    """Validate runtime environment. Returns (ok: bool, issues: list[str])."""
    issues = []

    # Python version
    if sys.version_info < (3, 8):
        issues.append(f"Python 3.8+ required (got {sys.version})")

    # .env file
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        issues.append(".env file missing (copy from .env.example)")

    # Ollama
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code != 200:
            issues.append("Ollama not responding (run: ollama serve)")
    except Exception:
        issues.append("Ollama not reachable at localhost:11434")

    # Key dependencies
    for mod_name in ["flask", "flask_socketio", "psutil"]:
        try:
            __import__(mod_name)
        except ImportError:
            issues.append(f"Missing dependency: {mod_name} (pip install -r requirements.txt)")

    # Meta data directory
    meta_dir = BASE_DIR / "meta_data"
    if not meta_dir.exists():
        try:
            meta_dir.mkdir(parents=True)
        except Exception:
            issues.append("Cannot create meta_data/ directory")

    return (len(issues) == 0, issues)


def print_startup_banner(mode: str, issues: list):
    """Print startup banner with system state."""
    print()
    print("=" * 60)
    print("  M.A.R.I.A. - Meta Analysis Recalibration Intelligence Architecture")
    print("=" * 60)
    print()

    if issues:
        print("  [!] Environment issues:")
        for issue in issues:
            print(f"      - {issue}")
        print()

    # System info
    try:
        import psutil
        ram = psutil.virtual_memory()
        print(f"  RAM:      {ram.available / (1024**3):.1f} GB available / {ram.total / (1024**3):.1f} GB total")
        print(f"  CPU:      {psutil.cpu_count()} cores")
    except Exception:
        pass

    # Ollama models
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            print(f"  Ollama:   {len(models)} models ({', '.join(models[:4])}{'...' if len(models) > 4 else ''})")
    except Exception:
        print("  Ollama:   not available")

    print(f"  Mode:     {mode}")
    print(f"  Base:     {BASE_DIR}")
    print()


# ====================================================================
# DAEMON (homeostasis tick loop)
# ====================================================================

def run_daemon(ctx, registry):
    """Run homeostasis tick loop until shutdown."""
    if not ctx.homeostasis_core:
        logger.error("HomeostasisCore not initialized - daemon cannot start")
        return

    core = ctx.homeostasis_core
    core._running = True
    logger.info("Daemon: homeostasis tick loop started")

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

    core._running = False
    logger.info("Daemon: tick loop stopped")


# ====================================================================
# WEB UI
# ====================================================================

def run_web_ui():
    """Run Flask-SocketIO Web UI server."""
    try:
        from maria_ui.app import app, socketio
        from maria_ui.config import DEBUG_MODE

        port = int(os.environ.get("MARIA_PORT", "5000"))
        host = os.environ.get("MARIA_HOST", "0.0.0.0")

        logger.info(f"Web UI: starting on http://{host}:{port}")
        socketio.run(
            app,
            host=host,
            port=port,
            debug=False,  # Never debug in unified mode
            allow_unsafe_werkzeug=True,
            log_output=False,
        )
    except Exception as e:
        logger.error(f"Web UI failed: {e}")


# ====================================================================
# GRACEFUL SHUTDOWN
# ====================================================================

def graceful_shutdown(ctx, registry):
    """Cleanup: consciousness checkpoint + module cleanup."""
    logger.info("Graceful shutdown starting...")

    # Stop homeostasis
    if ctx.homeostasis_core:
        ctx.homeostasis_core.stop(reason="shutdown")

    # Consciousness checkpoint
    summary = "Maria session"
    if ctx.conversation_memory and ctx.conversation_memory.get_session_turn_count() > 0:
        try:
            condense_brain = getattr(ctx.brain, 'ollama', ctx.brain)
            condensed = ctx.conversation_memory.condense_session(condense_brain)
            if condensed:
                ctx.conversation_memory.save_summary(condensed)
                summary = condensed.get("summary", summary)
                # Feed user_facts to UserProfile
                user_facts = condensed.get("user_facts", [])
                if user_facts and ctx.user_profile:
                    try:
                        added = ctx.user_profile.learn_from_user_facts(user_facts)
                        if added:
                            logger.info(f"UserProfile learned {added} new facts from session")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Condensation failed: {e}")

    if ctx.consciousness:
        try:
            ctx.consciousness.checkpoint(summary=summary)
            logger.info(f"Consciousness checkpoint saved")
        except Exception as e:
            logger.warning(f"Consciousness checkpoint failed: {e}")

    # Module cleanup
    registry.cleanup_all()
    logger.info("Shutdown complete")


# ====================================================================
# MAIN
# ====================================================================

def main():
    parser = argparse.ArgumentParser(description="M.A.R.I.A. - Unified Launcher")
    parser.add_argument("--daemon", action="store_true", help="Daemon only (no Web UI)")
    parser.add_argument("--ui", action="store_true", help="Web UI only (no daemon)")
    parser.add_argument("--check", action="store_true", help="Environment check only")
    args = parser.parse_args()

    # Determine mode
    if args.check:
        mode = "check"
    elif args.daemon:
        mode = "daemon"
    elif args.ui:
        mode = "ui"
    else:
        mode = "full"

    # Environment check
    env_ok, issues = check_environment()
    print_startup_banner(mode, issues)

    if mode == "check":
        if env_ok:
            print("  [OK] All checks passed")
        else:
            print("  [FAIL] Fix issues above")
        sys.exit(0 if env_ok else 1)

    if not env_ok:
        critical = [i for i in issues if "Ollama" in i or "Python" in i]
        if critical:
            print("  [FATAL] Cannot start - fix critical issues above")
            sys.exit(1)
        print("  [WARN] Starting with non-critical issues...\n")

    # Signal handlers
    def on_signal(signum, frame):
        logger.info(f"Signal {signum} received - shutting down")
        _shutdown.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    # ── UI-only mode ──
    if mode == "ui":
        print("  Starting Web UI only...\n")
        run_web_ui()
        return

    # ── Initialize brain + modules ──
    from main import init_brain, register_modules
    from agent_core.registry import ModuleRegistry

    print("  Initializing brain...")
    ctx = init_brain()
    print(f"  Brain: {ctx.brain_model}")

    registry = ModuleRegistry()
    register_modules(registry)
    registry.init_all(ctx)
    print("  Modules: initialized")

    # ── V3 Orchestrator (Phase A) ──
    try:
        from agent_core.awareness import ContextBuilder
        from agent_core.orchestrator import (
            UserFacingSelfModel, OnboardingFlow, TaskOrchestrator,
            CostEstimator, TimeEstimator, FreeVsPaidPlanner,
            ExecutionRouter, ToolCapabilityRegistry,
            TaskProgressTracker, LimitationReporter,
        )

        if not ctx.context_builder:
            ctx.context_builder = ContextBuilder()

        self_model = UserFacingSelfModel(ctx)
        ctx.user_facing_self_model = self_model

        onboarding = OnboardingFlow(ctx, self_model)
        ctx.onboarding_flow = onboarding

        if onboarding.should_run() and mode != "daemon":
            result = onboarding.run()
            print(result["text"])
        else:
            logger.debug("Onboarding already completed - skipping")

        # Phase B: Task Pipeline
        task_orch = TaskOrchestrator(ctx)
        ctx.task_orchestrator = task_orch

        # Phase C: Practical Intelligence (estimation engines)
        task_orch._cost_estimator = CostEstimator(ctx)
        task_orch._time_estimator = TimeEstimator(ctx)
        task_orch._resource_planner = FreeVsPaidPlanner(ctx)

        # Phase D+E: Execution Bridge + Product Shell
        from agent_core.orchestrator import ProductShell
        product_shell = ProductShell(ctx)
        ctx.product_shell = product_shell

        logger.info("V3 orchestrator initialized (Phase A-E, all 15 modules)")
    except Exception as e:
        logger.warning(f"V3 orchestrator init failed (non-critical): {e}")

    print()

    # ── Daemon-only mode ──
    if mode == "daemon":
        print("  Starting daemon (tick loop)...\n")
        try:
            run_daemon(ctx, registry)
        finally:
            graceful_shutdown(ctx, registry)
        return

    # ── Full mode: daemon + Web UI ──
    print("  Starting daemon + Web UI...\n")

    # Share vision cortex with Web UI (same process, on-demand LLaVA)
    if getattr(ctx, 'vision_cortex', None):
        try:
            from maria_ui.app import set_vision_cortex
            set_vision_cortex(ctx.vision_cortex)
            logger.info("Vision cortex shared with Web UI")
        except Exception as e:
            logger.debug(f"Could not share vision cortex with Web UI: {e}")

    # Start Web UI in background thread
    ui_thread = threading.Thread(target=run_web_ui, name="web-ui", daemon=True)
    ui_thread.start()
    logger.info("Web UI thread started")

    # Wait a moment for UI to bind
    time.sleep(1)
    port = int(os.environ.get("MARIA_PORT", "5000"))
    print(f"  Web UI:   http://192.168.178.32:{port}")
    print(f"  Daemon:   homeostasis tick loop (1Hz)")
    print(f"  Stop:     Ctrl+C or SIGTERM\n")
    print("=" * 60)
    print()

    # Run daemon in main thread (blocks until shutdown)
    try:
        run_daemon(ctx, registry)
    finally:
        graceful_shutdown(ctx, registry)


if __name__ == "__main__":
    main()
