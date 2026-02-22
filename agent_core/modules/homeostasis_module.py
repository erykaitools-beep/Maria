"""Homeostasis REPL commands: /homeostasis [status|start|stop|events|summary]."""

import threading
import time
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import Mode
from agent_core.homeostasis.event_logger import get_event_logger
from agent_core.memory.manager import MemoryManager
from agent_core.llm.manager import LLMManager


class HomeostasisModule(MariaModule):
    """Homeostasis monitoring and control."""

    name = "homeostasis"
    description = "Autonomous regulation loop (sensors, mode, alerts)"

    def __init__(self):
        self._thread = None
        self._running = False

    def init(self, ctx) -> bool:
        self.ctx = ctx

        # Initialize homeostasis core if not already done
        if ctx.homeostasis_core is None:
            try:
                memory_manager = MemoryManager()
                llm_manager = LLMManager()
                ctx.homeostasis_core = HomeostasisCore(
                    memory_manager=memory_manager,
                    llm_manager=llm_manager,
                    executor=None,
                )
                print("[Homeostasis] [OK] Initialized")
            except Exception as e:
                print(f"[Homeostasis] [WARN] Init failed: {e}")
                return False

        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/homeostasis", self._cmd_homeostasis,
                "  /homeostasis           - pokaz status homeostazy\n"
                "  /homeostasis start     - uruchom petle homeostazy w tle\n"
                "  /homeostasis stop      - zatrzymaj petle homeostazy\n"
                "  /homeostasis events N  - pokaz ostatnie N zdarzen (domyslnie 10)\n"
                "  /homeostasis summary   - pokaz podsumowanie sesji",
                "[HEART] HOMEOSTASIS",
            ),
        ]

    def _cmd_homeostasis(self, args):
        """Handle /homeostasis commands."""
        core = self.ctx.homeostasis_core
        if not core:
            print("[Homeostasis] [ERROR] Not initialized")
            return

        subcommand = args[0].lower() if args else "status"

        if subcommand == "status":
            self._show_status(core)
        elif subcommand == "start":
            self._start_loop(core)
        elif subcommand == "stop":
            self._stop_loop(core)
        elif subcommand == "events":
            limit = 10
            if len(args) > 1:
                try:
                    limit = int(args[1])
                except ValueError:
                    pass
            self._show_events(limit)
        elif subcommand == "summary":
            self._show_summary()
        else:
            print(f"[Homeostasis] Unknown subcommand: {subcommand}")
            print("  Usage: /homeostasis [status|start|stop|events|summary]")

    def _show_status(self, core):
        state = core.state
        telemetry = core.get_telemetry()

        print("\n" + "=" * 50)
        print("[HEART] HOMEOSTASIS STATUS")
        print("=" * 50)
        print(f"  Mode:         {state.mode.value.upper()}")
        print(f"  Health Score: {state.health_score:.1%}")
        print(f"  Mode Duration: {state.mode_duration_seconds:.0f}s")
        print(f"  Idle Seconds: {state.idle_seconds:.0f}s")

        if state.alerts:
            print(f"\n  [WARN] Alerts ({len(state.alerts)}):")
            for alert in state.alerts[-5:]:
                print(f"    - {alert}")
        else:
            print(f"\n  [OK] No alerts")

        if telemetry.get("resource_headroom"):
            rh = telemetry["resource_headroom"]
            print(f"\n  Resources:")
            print(f"    RAM:  {rh.get('ram_pct', 0):.0f}% available")
            print(f"    CPU:  {rh.get('cpu_pct', 0):.0f}% available")
            print(f"    Disk: {rh.get('disk_pct', 0):.0f}% available")

        print(f"\n  Loop Running: {'Yes' if self._running else 'No'}")
        print("=" * 50 + "\n")

    def _start_loop(self, core):
        if self._running:
            print("[Homeostasis] Already running")
            return

        def loop():
            self._running = True
            print("[Homeostasis] [START] Starting monitoring loop...")

            while self._running:
                try:
                    core._execute_tick()

                    if core.state.mode != Mode.ACTIVE:
                        print(f"[Homeostasis] [WARN] Mode: {core.state.mode.value}")

                    time.sleep(1.0)
                except Exception as e:
                    print(f"[Homeostasis] [WARN] Error: {e}")
                    time.sleep(5.0)

            print("[Homeostasis] [STOP] Loop stopped")

        self._thread = threading.Thread(
            target=loop, daemon=True, name="HomeostasisLoop"
        )
        self._thread.start()
        print("[Homeostasis] [OK] Monitoring started")

    def _stop_loop(self, core):
        if not self._running:
            print("[Homeostasis] Not running")
            return

        self._running = False
        core.stop(reason="user_request")
        print("[Homeostasis] Stopping...")

    def _show_events(self, limit):
        event_logger = get_event_logger()
        events = event_logger.get_recent_events(limit=limit)

        print("\n" + "=" * 70)
        print(f"[EVENTS] HOMEOSTASIS EVENTS (last {len(events)})")
        print("=" * 70)

        if not events:
            print("  No events recorded yet.")
        else:
            for event in events:
                ts = event.get("timestamp", event.get("ts", 0))
                dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                event_type = event.get("event", event.get("event_type", "?"))

                if event_type == "mode_change":
                    from_m = event.get("from_mode", event.get("from", "?"))
                    to_m = event.get("to_mode", event.get("to", "?"))
                    trigger = event.get("trigger", {})
                    constraint = trigger.get("constraint", "?")
                    value = trigger.get("value")
                    threshold = trigger.get("threshold")
                    duration = event.get("duration_in_prev_mode_sec", 0)

                    print(f"\n  [{dt}] MODE CHANGE: {from_m} -> {to_m}")
                    print(f"      Trigger: {constraint}")
                    if value is not None:
                        print(f"      Value: {value} (threshold: {threshold})")
                    print(f"      Duration in {from_m}: {duration:.0f}s")

                elif event_type == "alert":
                    severity = event.get("severity", "?")
                    alert_type = event.get("alert_type", "?")
                    message = event.get("message", "")
                    print(f"\n  [{dt}] {severity}: {alert_type}")
                    print(f"      {message}")

                elif event_type == "state_snapshot":
                    mode = event.get("mode", "?")
                    health = event.get("health_score", 0)
                    metrics = event.get("metrics", {})
                    ram = metrics.get("ram_available_pct", 0)
                    cpu = metrics.get("cpu_load", 0)
                    print(f"\n  [{dt}] SNAPSHOT: mode={mode}, health={health:.0%}")
                    print(f"      RAM: {ram:.0f}%, CPU: {cpu:.0f}%")

                elif event_type == "startup":
                    print(f"\n  [{dt}] STARTUP: {event.get('message', '')}")

                elif event_type == "shutdown":
                    reason = event.get("reason", "?")
                    uptime = event.get("uptime_sec", 0)
                    print(f"\n  [{dt}] SHUTDOWN: reason={reason}, uptime={uptime:.0f}s")

                else:
                    print(f"\n  [{dt}] {event_type}: {event}")

        print("\n" + "=" * 70)
        print(f"  Log file: {event_logger.log_path}")
        print("=" * 70 + "\n")

    def _show_summary(self):
        event_logger = get_event_logger()
        summary = event_logger.get_session_summary()

        print("\n" + "=" * 50)
        print("[SUMMARY] HOMEOSTASIS SESSION SUMMARY")
        print("=" * 50)
        print(f"  Uptime:        {summary['uptime_sec']:.0f}s ({summary['uptime_sec']/3600:.1f}h)")
        print(f"  Total Events:  {summary['total_events']}")
        print(f"  Mode Changes:  {summary['mode_changes']}")
        print(f"  Modes Visited: {', '.join(summary['modes_visited']) or 'none'}")
        print(f"\n  Alerts:")
        print(f"    CRITICAL: {summary['alerts']['CRITICAL']}")
        print(f"    ALERT:    {summary['alerts']['ALERT']}")
        print(f"    WARNING:  {summary['alerts']['WARNING']}")
        print(f"\n  Log File: {summary['log_file']}")
        print("=" * 50 + "\n")

    def cleanup(self):
        if self._running:
            self._running = False
