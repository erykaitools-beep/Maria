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
    if sys.version_info < (3, 10):
        issues.append(f"Python 3.10+ required (got {sys.version})")

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

def _maybe_warm_recover(ctx) -> None:
    """Klocek 9b: on a WARM boot, resume the in-flight strategic plan and log
    the pre-crash mode. Mode is a HINT only -- tick 1 re-derives it from live
    sensors, so a crash caused by a bad mode can NOT be resurrected into a
    crash loop. Flag-gated; OFF (or no fresh snapshot) = cold boot exactly as
    before. Never raises -- a recovery failure must not block the daemon.

    Runs after SystemState init + start_watchdog and BEFORE the first tick, so
    the restored plan is in place before the tactical loop runs, and before the
    tick-0 self-perception snapshot."""
    try:
        from agent_core.homeostasis import recovery
        if not recovery.is_enabled():
            return
        snap = recovery.read_snapshot()
        if not snap:
            logger.info("Warm recovery: no fresh snapshot -> cold boot")
            return

        resumed = False
        sp = getattr(ctx, "strategic_planner", None)
        plan_dict = snap.get("strategic_plan")
        if sp is not None and plan_dict and hasattr(sp, "restore_plan"):
            from agent_core.planner.strategic_plan import StrategicPlan
            plan = StrategicPlan.from_dict(plan_dict)
            # Operational continuity only if the plan is still usable; an
            # expired/exhausted plan is pointless to resume.
            if not plan.is_expired and not plan.is_exhausted:
                sp.restore_plan(plan)
                resumed = True

        prior_mode = snap.get("mode")
        goal_ids = snap.get("active_goal_ids") or []
        logger.info(
            "Warm recovery: prior_mode=%s (hint; sensors re-derive), "
            "plan_resumed=%s, in_flight_goals=%d",
            prior_mode, resumed, len(goal_ids),
        )

        # Audit trail (best-effort; uses the homeostasis event log).
        try:
            core = getattr(ctx, "homeostasis_core", None)
            ev = getattr(core, "event_logger", None) if core else None
            if ev is not None and hasattr(ev, "_write_event"):
                ev._write_event({
                    "timestamp": time.time(),
                    "event": "recovery",
                    "type": "warm_recovery",
                    "prior_mode": prior_mode,
                    "plan_resumed": resumed,
                    "in_flight_goals": len(goal_ids),
                })
        except Exception:
            pass
    except Exception:
        logger.warning("Warm recovery failed -> continuing cold", exc_info=True)


def run_daemon(ctx, registry):
    """Run homeostasis tick loop until shutdown."""
    if not ctx.homeostasis_core:
        logger.error("HomeostasisCore not initialized - daemon cannot start")
        return

    core = ctx.homeostasis_core
    core._running = True
    core.start_watchdog()  # out-of-loop freeze detector (2026-06-02 incident)
    _maybe_warm_recover(ctx)  # Klocek 9b: resume in-flight plan (flag-gated)
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

def _finalize_exit() -> None:
    """Bounded farewell + hard exit (audyt 2026-06-12).

    Pool llm-timeout ma watki NIE-daemonowe (Python 3.9+), wiec zwykle
    sys.exit() czeka na porzucone wywolanie LLM do konca jego timeoutu --
    zaobserwowane 191 s ("Shutdown complete" 17:43:37 -> exit 17:46:48,
    /restart trafil w sesje refleksji). Kolejnosc bezpieczenstwa:
    1. graceful_shutdown() JUZ zapisal checkpoint swiadomosci (przed nami).
    2. Krotka gracja na dokonczenie biezacego wywolania (wynik i tak
       poszedlby do kosza -- proces umiera).
    3. Flush logow i twarde wyjscie: exit 1 = /restart (systemd
       Restart=on-failure podnosi), exit 0 = czysty stop.
    """
    exit_code = 0
    try:
        from agent_core.runtime_flags import restart_requested
        if restart_requested():
            exit_code = 1
    except Exception:
        pass
    try:
        from agent_core.llm.execution_budget import wait_for_llm_workers
        if not wait_for_llm_workers(grace_sec=15.0):
            logger.warning(
                "LLM worker still busy after 15s grace -- exiting hard"
            )
    except Exception:
        pass
    logger.info(f"Exiting (code {exit_code})")
    logging.shutdown()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(exit_code)


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

def _cleanup_stale_processes():
    """Kill stale ccd-cli and pytest processes from old Claude Code sessions.

    These accumulate when SSH sessions disconnect without cleanup,
    eating 300-500MB RAM each. Safe to kill: they have no open files
    or network connections that Maria depends on.
    """
    import subprocess
    my_pid = os.getpid()
    killed = 0
    freed_mb = 0

    try:
        # Find stale ccd-cli processes (old Claude Code sessions)
        result = subprocess.run(
            ["pgrep", "-u", "maria", "-f", "ccd-cli"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().split("\n"):
            if not pid_str.strip():
                continue
            pid = int(pid_str.strip())
            if pid == my_pid:
                continue
            try:
                # Check age: only kill processes older than 2 hours
                stat = Path(f"/proc/{pid}/stat").read_text().split()
                # Get RSS in pages (field 23), page size = 4KB
                rss_pages = int(stat[23])
                rss_mb = rss_pages * 4 / 1024
                os.kill(pid, 9)
                killed += 1
                freed_mb += rss_mb
            except (OSError, IndexError, ValueError):
                continue

        # Find stale pytest processes
        result = subprocess.run(
            ["pgrep", "-u", "maria", "-f", "pytest"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().split("\n"):
            if not pid_str.strip():
                continue
            pid = int(pid_str.strip())
            if pid == my_pid:
                continue
            try:
                stat = Path(f"/proc/{pid}/stat").read_text().split()
                rss_pages = int(stat[23])
                rss_mb = rss_pages * 4 / 1024
                os.kill(pid, 9)
                killed += 1
                freed_mb += rss_mb
            except (OSError, IndexError, ValueError):
                continue

        if killed > 0:
            logger.info(
                f"Startup cleanup: killed {killed} stale processes, "
                f"freed ~{freed_mb:.0f}MB RAM"
            )
    except Exception as e:
        logger.debug(f"Stale process cleanup skipped: {e}")


def _force_recompile_pyc():
    """Hardening for the C3 incident (2026-04-24).

    Force-recompile every ``.py`` in ``agent_core/`` and ``maria_core/``.
    During the C3 audit a ``git checkout`` preserved the .py mtime of an
    older revision while leaving an even older ``.pyc`` cached — Python's
    bytecode freshness check (mtime equality) considered the stale cache
    valid and ran an outdated function for hours. ``compileall.force=True``
    rewrites every cache so every restart is guaranteed to run the .py
    that's actually on disk right now.

    Skipped when ``MARIA_SKIP_PYC_RECOMPILE=1`` (e.g. unit tests, CI) and
    swallows errors silently — boot must never fail because of cache work.
    """
    if os.environ.get("MARIA_SKIP_PYC_RECOMPILE", "").lower() in ("1", "true", "yes"):
        return
    try:
        import compileall

        targets = [BASE_DIR / "agent_core", BASE_DIR / "maria_core"]
        recompiled_dirs = 0
        start = time.time()
        for target in targets:
            if not target.exists():
                continue
            try:
                compileall.compile_dir(
                    str(target),
                    force=True,      # rewrite even if mtime says cache is fresh
                    quiet=2,         # silent on success
                    workers=0,       # auto worker count
                )
                recompiled_dirs += 1
            except Exception as e:
                logger.debug(f"compileall failed for {target}: {e}")
        elapsed_ms = (time.time() - start) * 1000
        logger.info(
            f"Startup hardening: pyc force-recompile of {recompiled_dirs} "
            f"package(s) in {elapsed_ms:.0f}ms"
        )
    except Exception as e:
        logger.debug(f"pyc recompile skipped: {e}")


def main():
    def _thread_excepthook(args):
        logger.critical(
            "Unhandled exception in thread %s: %s",
            getattr(args.thread, "name", "unknown"),
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook

    def _sys_excepthook(exc_type, exc_value, exc_tb):
        logger.critical(
            "Unhandled exception: %s",
            exc_value,
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _sys_excepthook

    # Cleanup stale processes from old Claude Code sessions
    _cleanup_stale_processes()

    # C3 hardening: force-recompile .pyc to defeat stale-cache attacks
    # like the 2026-04-24 git-checkout drift incident.
    _force_recompile_pyc()

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

    # Expose ConsciousnessCore process-wide so the Web UI (which lives in
    # the same process but doesn't share the SharedContext object) can emit
    # personality signals like `conversation_turn` (C6 fix).
    if ctx.consciousness:
        try:
            from agent_core.consciousness import set_global_consciousness
            set_global_consciousness(ctx.consciousness)
        except Exception as e:
            logger.warning(f"Could not register global consciousness: {e}")

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

        if onboarding.should_run() and mode != "daemon" and sys.stdin.isatty():
            result = onboarding.run(input_fn=input)
            if result.get("text"):
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
        # /restart -> exit 1 (systemd podnosi), czysty stop -> exit 0;
        # twarde wyjscie z gracja, patrz _finalize_exit.
        _finalize_exit()

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

    # Share live SelfContext (Super-META E2) so the chat brain consults the SAME
    # situational picture the daemon builds (fresh vision memory, mode). The chat
    # tail stays dormant until SELF_CONTEXT_CHAT_ENABLED is armed.
    if getattr(ctx, 'self_context', None):
        try:
            from maria_ui.app import set_self_context
            set_self_context(ctx.self_context)
            logger.info("SelfContext shared with Web UI (Super-META E2)")
        except Exception as e:
            logger.debug(f"Could not share SelfContext with Web UI: {e}")

    # Share the live approval stores with the Web UI so in-app approve/reject
    # (Skrzynka layer 2) writes through the SAME store instances as the tick +
    # Telegram threads -- one lock per store, no cross-instance race.
    try:
        from maria_ui.app import set_approval_stores
        set_approval_stores(
            outbox=getattr(ctx, "outbox_store", None),
            conductor=getattr(ctx, "maria_conductor", None),
            bulletin=getattr(ctx, "bulletin_store", None),
        )
        logger.info("Approval stores shared with Web UI")
    except Exception as e:
        logger.debug(f"Could not share approval stores with Web UI: {e}")

    # Start Web UI in background thread
    ui_thread = threading.Thread(target=run_web_ui, name="web-ui", daemon=True)
    ui_thread.start()
    logger.info("Web UI thread started")

    # Wait a moment for UI to bind
    time.sleep(1)
    port = int(os.environ.get("MARIA_PORT", "5000"))
    print(f"  Web UI:   http://localhost:{port}")
    print(f"  Daemon:   homeostasis tick loop (1Hz)")
    print(f"  Stop:     Ctrl+C or SIGTERM\n")
    print("=" * 60)
    print()

    # Run daemon in main thread (blocks until shutdown)
    try:
        run_daemon(ctx, registry)
    finally:
        graceful_shutdown(ctx, registry)

    # /restart -> exit 1 (systemd podnosi), czysty stop -> exit 0;
    # twarde wyjscie z gracja, patrz _finalize_exit.
    _finalize_exit()


if __name__ == "__main__":
    main()
