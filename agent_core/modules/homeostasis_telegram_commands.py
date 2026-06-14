"""Telegram command handlers for operator interaction.

Extracted verbatim from homeostasis_module (2026-06-13 god-file split):
register_telegram_commands(bridge, ctx) wires every operator command. Behaviour
is identical to the in-module function it replaced; init() now imports and calls
it. Module-level dependencies (measured by AST scan): datetime, os, threading,
time, logger, _propose_outbox_status_note.
"""

import logging
import os
import threading
import time
from datetime import datetime

from agent_core.modules.homeostasis_outbox import _propose_outbox_status_note

logger = logging.getLogger(__name__)


def register_telegram_commands(bridge, ctx):
    """Register Telegram command handlers for operator interaction."""

    def _cmd_status(args):
        """Return system status summary."""
        parts = []
        if ctx.homeostasis_core:
            state = ctx.homeostasis_core.get_state()
            parts.append(f"Mode: {state.mode.value}")
            parts.append(f"Health: {state.health_score:.0%}")
            if state.alerts:
                parts.append(f"Alerts: {len(state.alerts)}")

        if ctx.planner_core:
            status = ctx.planner_core.get_status()
            parts.append(f"Planner cycles: {status['total_cycles']}")
            parts.append(f"Plans executed: {status['total_plans_executed']}")

        if ctx.knowledge_analyzer:
            try:
                snap = ctx.knowledge_analyzer.get_knowledge_snapshot()
                if snap:
                    by_status = snap.get("files_by_status", {})
                    completed = len(by_status.get("completed", []))
                    total = snap.get("total_files", 0)
                    parts.append(f"Knowledge: {completed}/{total} completed")
            except Exception:
                pass

        if ctx.goal_store:
            try:
                stats = ctx.goal_store.stats()
                parts.append(f"Goals: {stats.get('active', 0)} active, {stats.get('proposed', 0)} proposed")
            except Exception:
                pass

        return "\n".join(parts) if parts else "System OK"

    def _cmd_selfstatus(args):
        """Show current Self-Perception snapshot."""
        sp = getattr(ctx, "self_perception", None)
        if sp is None:
            return "Brak SelfPerception (modul nie wired)."
        return sp.format_status_for_telegram()

    def _cmd_strategic(args):
        """#9: toggle/inspect whether StrategicPlanner drives the tactical loop.

        /strategic        -> status + current plan summary
        /strategic on     -> let the strategist steer (runtime, resets on restart)
        /strategic off    -> back to pure rule-based selection
        """
        planner = ctx.planner_core
        if planner is None:
            return "Brak planner_core (modul nie wired)."
        arg = (args or "").strip().lower()
        if arg in {"on", "true", "1", "start"}:
            planner.set_strategic_drives(True)
            return (
                "StrategicPlanner DRIVES = ON (runtime; reset po restarcie).\n"
                "Strateg steruje petla: blocked_goals / focus / idle_strategy.\n"
                "Bramy BHP (okno/feasibility/tryb/K7) zostaja w rdzeniu.\n"
                "/strategic -> podglad planu, /strategic off -> cofnij."
            )
        if arg in {"off", "false", "0", "stop"}:
            planner.set_strategic_drives(False)
            return "StrategicPlanner DRIVES = OFF (powrot do rule-based)."
        return planner.strategic_status_text()

    def _cmd_fs_write(args):
        """B2: toggle/seed the first real effector action (sandboxed file write).

        /fs_write        -> status (flag + open file_exists goals)
        /fs_write on     -> let the planner write (runtime, resets on restart)
        /fs_write off    -> stop
        /fs_write seed   -> create the demonstration goal (a file to write)
        """
        planner = ctx.planner_core
        if planner is None:
            return "Brak planner_core (modul nie wired)."
        arg = (args or "").strip().lower()
        if arg in {"on", "true", "1", "start"}:
            planner.set_fs_write_enabled(True)
            return (
                "FS_WRITE = ON (runtime; reset po restarcie).\n"
                "Planner zapisze plik dla celu z kryterium file_exists,\n"
                "K10 sprawdzi ze plik istnieje, cel domknie sie NA DOWODZIE.\n"
                "/fs_write seed -> stworz cel-demo, /fs_write off -> cofnij."
            )
        if arg in {"off", "false", "0", "stop"}:
            planner.set_fs_write_enabled(False)
            return "FS_WRITE = OFF (planner nie wykonuje akcji)."
        if arg == "seed":
            store = ctx.goal_store
            if store is None:
                return "Brak goal_store (modul nie wired)."
            try:
                from agent_core.routing.handlers import seed_first_action_goal
                gid = seed_first_action_goal(store)
            except Exception as e:
                return f"Seed blad: {e}"
            if not gid:
                return "Nie udalo sie stworzyc celu-demo."
            return (
                f"Cel-demo utworzony: {gid} (ACTIVE).\n"
                "Kryterium: plik meta_data/fs_sandbox/maria_first_action.txt.\n"
                "Wlacz /fs_write on -> planner go zapisze i domknie cel."
            )
        # status (default)
        state = "ON" if getattr(planner, "_fs_write_enabled", False) else "OFF"
        lines = [f"FS_WRITE (pierwsza realna akcja): {state}"]
        store = ctx.goal_store
        if store is not None:
            try:
                open_crit = sum(
                    1 for g in store.get_active()
                    if any(isinstance(c, dict) and c.get("type") == "file_exists"
                           for c in (getattr(g, "success_criteria", None) or []))
                )
                lines.append(f"Cele z kryterium file_exists (otwarte): {open_crit}")
            except Exception:
                pass
        lines.append("/fs_write on|off|seed")
        return "\n".join(lines)

    def _cmd_heldout(args):
        """B4: toggle/seed the first goal closed by an INDEPENDENT exam.

        /heldout             -> status (flag + open exam_independent goals)
        /heldout on          -> planner re-examines files behind exam_independent
                                criteria; exams grade held-out (runtime)
        /heldout off         -> stop
        /heldout seed [file] -> create the demo goal (default web_wiki_chemia.txt)
        """
        import os as _os
        planner = ctx.planner_core
        if planner is None:
            return "Brak planner_core (modul nie wired)."
        parts = (args or "").strip().split()
        arg = parts[0].lower() if parts else ""
        if arg in {"on", "true", "1", "start"}:
            # env drives the exam pipeline's use_heldout; flag drives the planner
            # to actively re-examine exam_independent goals. Set together.
            _os.environ["HELDOUT_GRADER_ENABLED"] = "1"
            planner.set_heldout_enabled(True)
            return (
                "HELDOUT = ON (runtime; reset po restarcie).\n"
                "Planner re-egzaminuje plik celu z kryterium exam_independent,\n"
                "egzamin oceniany NIEZALEZNIE (heldout:static@v1, zero LLM),\n"
                "cel domyka sie NA DOWODZIE (grader_independent w exam_results).\n"
                "/heldout seed -> cel-demo, /heldout off -> cofnij."
            )
        if arg in {"off", "false", "0", "stop"}:
            _os.environ["HELDOUT_GRADER_ENABLED"] = "0"
            planner.set_heldout_enabled(False)
            return "HELDOUT = OFF (planner nie wymusza egzaminu; grader wraca do LLM)."
        if arg == "seed":
            store = ctx.goal_store
            if store is None:
                return "Brak goal_store (modul nie wired)."
            file_id = parts[1] if len(parts) > 1 else "web_wiki_chemia.txt"
            try:
                from agent_core.routing.handlers import seed_heldout_exam_goal
                gid = seed_heldout_exam_goal(store, file_id=file_id)
            except Exception as e:
                return f"Seed blad: {e}"
            if not gid:
                return "Nie udalo sie stworzyc celu-demo."
            return (
                f"Cel-demo utworzony: {gid} (ACTIVE).\n"
                f"Kryterium: exam_independent na '{file_id}' (prog 0.6).\n"
                "Wlacz /heldout on -> planner zegzaminuje i domknie cel na dowodzie."
            )
        # status (default)
        state = "ON" if getattr(planner, "_heldout_enabled", False) else "OFF"
        env_on = _os.environ.get("HELDOUT_GRADER_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on"}
        lines = [f"HELDOUT (niezalezny egzamin): planner={state} grader_env={'1' if env_on else '0'}"]
        store = ctx.goal_store
        if store is not None:
            try:
                open_crit = sum(
                    1 for g in store.get_active()
                    if any(isinstance(c, dict) and c.get("type") == "exam_independent"
                           for c in (getattr(g, "success_criteria", None) or []))
                )
                lines.append(f"Cele z kryterium exam_independent (otwarte): {open_crit}")
            except Exception:
                pass
        lines.append("/heldout on|off|seed [plik]")
        return "\n".join(lines)

    def _cmd_list_repairs(args):
        """List pending self-repair tasks."""
        conductor = getattr(ctx, "maria_conductor", None)
        if conductor is None:
            return "Brak maria_conductor (modul nie wired)."
        tasks = conductor.get_pending_repair_tasks()
        if not tasks:
            return "Brak otwartych self-repair tasks."

        lines = [f"Otwarte self-repair tasks ({len(tasks)}):"]
        now = time.time()
        for task in sorted(tasks, key=lambda item: item.created_at):
            artifacts = task.artifacts or {}
            repair_kind = artifacts.get("repair_kind", "?")
            subject = (
                artifacts.get("repair_subject")
                or _repair_subject_from_evidence(artifacts.get("evidence_summary", {}))
                or "-"
            )
            age = _format_repair_age(now - float(task.created_at))
            expires = _format_repair_expiry(artifacts.get("expires_at"))
            lines.append(
                f"  {task.task_id} | {repair_kind} | {subject} | "
                f"{age} temu | wygasnie {expires}"
            )
        lines.append("Zatwierdz: /approve_repair <task_id>")
        return "\n".join(lines)

    def _cmd_approve_repair(args):
        """Acknowledge a self-repair task: operator owns it -> close it.

        Self-repair alerts have no clean autonomous fix -- dispatching Codex at
        the live repo dead-ends on the dirty-workspace safeguard and the task
        zombifies (BLOCKED forever). Approval now means "operator is handling
        this": the task is marked DONE and its bulletin resolved, so the queue
        stays clean and the next task can start.
        """
        conductor = getattr(ctx, "maria_conductor", None)
        task_ref = args.strip() if isinstance(args, str) else str(args).strip()
        if conductor is None or not task_ref:
            return "Uzycie: /approve_repair <task_id>"

        matches = [
            task for task in conductor.get_pending_repair_tasks()
            if _repair_task_matches(task.task_id, task_ref)
        ]
        if len(matches) != 1:
            return f"Nie znaleziono PENDING self-repair task: {task_ref}"

        task = matches[0]
        conductor.mark_done(
            task.task_id,
            notes="acknowledged + closed by operator (/approve_repair)",
        )
        from agent_core.self_repair.expiry import _close_linked_bulletin
        _close_linked_bulletin(
            getattr(ctx, "bulletin_store", None),
            task.task_id,
            reason="operator_acknowledged",
        )

        message = (
            f"[Self-repair] Task {task.task_id} acknowledged by operator "
            "-> closed."
        )
        try:
            bridge.bot.send_message(message)
        except Exception:
            logger.debug("approve_repair notification failed", exc_info=True)

        return (
            f"Zatwierdzono i zamknieto {task.task_id}. Bulletin rozwiazany, "
            "kolejka czysta."
        )

    def _cmd_drill_repair(args):
        """Live drill for self-repair (Plank 6): create a synthetic repair task
        through the REAL RepairTaskCreator so the whole chain runs in production
        -- gate -> task -> bulletin -> TASK_BOARD -> Telegram notify. Self-repair
        has never fired in vivo (0x live); this proves the wiring end to end.

        The task is marked drill=True + approval_required=True (the autonomous
        dispatcher refuses approval_required), so it is harmless: close it with
        /approve_repair or let expiry sweep it after 24h. It never dispatches Codex.

        /drill_repair        respect the creation gate (realistic; refused outside
                             ACTIVE/REDUCED or with NIM down, reason reported).
        /drill_repair force  bypass the gate -- exercise the chain on demand.
        """
        creator = getattr(ctx, "repair_task_creator", None)
        if creator is None:
            return "Brak repair_task_creator (modul self-repair nie wired)."

        arg = args.strip().lower() if isinstance(args, str) else ""
        force = arg == "force"

        from agent_core.self_repair.detectors import RepairCandidate
        candidate = RepairCandidate(
            repair_kind="drill",
            summary="DRILL - synthetic self-repair live test (safe, no real failure)",
            evidence_summary={
                "drill": True,
                "note": "manual /drill_repair -- exercises the real creation chain",
                "subject": "drill",
            },
            detected_at=time.time(),
        )
        try:
            task_id = creator.create(candidate, snapshot_id="drill", bypass_gate=force)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("drill_repair create failed", exc_info=True)
            return f"Drill blad: {exc}"

        if task_id is None:
            return (
                "Drill ODMOWIONY przez gate (mode != ACTIVE/REDUCED, NIM down, "
                "stale snapshot lub cooldown). To JEST realne zachowanie self-repair "
                "-- nie tworzy taskow poza ACTIVE/REDUCED. Uzyj '/drill_repair force' "
                "by przetestowac sam lancuch tworzenia teraz, albo odpal w ACTIVE."
            )

        return (
            f"Drill OK -> {task_id} (drill, approval_required). Powiadomienie TG "
            f"powinno przyjsc. Sprawdz: /list_repairs | zamknij: /approve_repair "
            f"{task_id} (expiry sprzatnie po 24h)."
        )

    def _cmd_drill_heartbeat(args):
        """Live drill for the 7b heartbeat detector: run the REAL thread-liveness
        detector against a SYNTHETIC dead thread so the whole chain fires in
        production -- get_thread_health -> detect_thread_unhealthy -> task ->
        bulletin -> TASK_BOARD -> Telegram. No real thread is touched.

        Like /drill_repair, the task is drill=True + approval_required (the
        autonomous dispatcher refuses approval_required), so it is harmless:
        close it with /approve_repair or let expiry sweep it after 24h. Proves
        the heartbeat path end to end (the detector ships behind a flag, OFF).

        /drill_heartbeat        respect the creation gate (realistic).
        /drill_heartbeat force  bypass the gate -- exercise the chain on demand.
        """
        creator = getattr(ctx, "repair_task_creator", None)
        if creator is None:
            return "Brak repair_task_creator (modul self-repair nie wired)."

        arg = args.strip().lower() if isinstance(args, str) else ""
        force = arg == "force"

        from agent_core.self_repair.detectors import detect_thread_unhealthy

        # Real thread health, best-effort, for context in the reply.
        real_health = []
        core = getattr(ctx, "homeostasis_core", None)
        if core is not None and hasattr(core, "get_thread_health"):
            try:
                real_health = core.get_thread_health()
            except Exception:
                logger.debug("drill_heartbeat get_thread_health failed", exc_info=True)

        # A synthetic dead persistent thread drives the REAL detector, which
        # produces a genuine thread_unhealthy candidate. No real thread dies.
        synthetic = [{
            "name": "DRILL_TickWatchdog",
            "kind": "persistent",
            "alive": False,
            "age_sec": None,
        }]
        candidates = detect_thread_unhealthy(synthetic, lambda kind, subject: False)
        if not candidates:
            return "Heartbeat drill blad: detektor nie wygenerowal kandydata (regresja?)."

        candidate = candidates[0]
        candidate.evidence_summary["drill"] = True
        candidate.evidence_summary["note"] = (
            "manual /drill_heartbeat -- synthetic dead thread, no real failure"
        )

        try:
            task_id = creator.create(candidate, snapshot_id="drill", bypass_gate=force)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("drill_heartbeat create failed", exc_info=True)
            return f"Heartbeat drill blad: {exc}"

        real_summary = ", ".join(
            f"{h['name']}={'alive' if h.get('alive') else 'DEAD'}"
            for h in real_health
        ) or "(core niedostepny)"

        if task_id is None:
            return (
                "Heartbeat drill ODMOWIONY przez gate (mode != ACTIVE/REDUCED, "
                "NIM down, stale snapshot lub cooldown). To realne zachowanie "
                f"self-repair. Realny stan watkow: {real_summary}. Uzyj "
                "'/drill_heartbeat force' by przetestowac sam lancuch teraz."
            )

        return (
            f"Heartbeat drill OK -> {task_id} (thread_unhealthy, drill, "
            f"approval_required). Realny stan watkow: {real_summary}. "
            f"Powiadomienie TG powinno przyjsc. Zamknij: /approve_repair {task_id}."
        )

    def _cmd_drill_outbox(args):
        """On-demand outbox proposal (Rung 2 hands, mirror /drill_repair):
        compose a status note + PROPOSE it now. NOTHING is written until
        /approve_note -- the write is operator-gated."""
        rec = _propose_outbox_status_note(ctx, reason="drill")
        if rec is None:
            return ("Outbox drill: brak propozycji (modul nie wired, juz jest "
                    "pending, albo blad). Sprawdz /list_notes.")
        return (
            f"Outbox drill OK -> {rec['id']} ({rec['filename']}.txt) PENDING. "
            f"Zapis DOPIERO po: /approve_note {rec['id']}."
        )

    def _cmd_list_notes(args):
        store = getattr(ctx, "outbox_store", None)
        if store is None:
            return "Brak outbox_store (modul nie wired)."
        pend = store.list_pending()
        if not pend:
            return "Brak oczekujacych notatek outbox."
        lines = [f"Oczekujace notatki outbox ({len(pend)}):"]
        for r in pend[:10]:
            lines.append(f"- {r['id']} ({r['filename']}.txt) reason={r.get('reason', '')}")
        lines.append("Zatwierdz: /approve_note <id> | odrzuc: /reject_note <id>")
        return "\n".join(lines)

    def _cmd_approve_note(args):
        store = getattr(ctx, "outbox_store", None)
        if store is None:
            return "Brak outbox_store (modul nie wired)."
        pid = (args or "").strip()
        if not pid:
            return "Uzycie: /approve_note <id> (zobacz /list_notes)"
        res = store.approve(pid)
        if not res.get("ok"):
            err = res.get("error") or (res.get("result") or {}).get("error") or "?"
            return f"Approve nieudane: {err}"
        path = res["result"]["path"]
        return (
            f"Zapisano -> {path}\n"
            f"To pierwsza prawdziwa akcja Marii na swiat (outbox, za Twoja zgoda)."
        )

    def _cmd_reject_note(args):
        store = getattr(ctx, "outbox_store", None)
        if store is None:
            return "Brak outbox_store (modul nie wired)."
        pid = (args or "").strip()
        if not pid:
            return "Uzycie: /reject_note <id>"
        res = store.reject(pid)
        return f"Odrzucono {pid}." if res.get("ok") else f"Nie udalo sie: {res.get('error')}"

    def _repair_task_matches(task_id, ref):
        token = ref.strip()
        return task_id == token or task_id.startswith(token) or task_id.endswith(token)

    def _repair_subject_from_evidence(evidence):
        if not isinstance(evidence, dict):
            return None
        return (
            evidence.get("service_name")
            or evidence.get("project")
            or evidence.get("subject")
        )

    def _format_repair_age(seconds):
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}min"
        hours = minutes // 60
        return f"{hours}h"

    def _format_repair_expiry(expires_at):
        if not isinstance(expires_at, (int, float)):
            return "?"
        try:
            from zoneinfo import ZoneInfo

            dt = datetime.fromtimestamp(float(expires_at), ZoneInfo("Europe/Berlin"))
        except Exception:
            dt = datetime.fromtimestamp(float(expires_at))
        return dt.strftime("%H:%M")

    def _cmd_goals(args):
        """List active and proposed goals."""
        if not ctx.goal_store:
            return "GoalStore not available"

        lines = []
        active = ctx.goal_store.get_active()
        if active:
            lines.append(f"*Active ({len(active)}):*")
            for g in active[:20]:
                lines.append(f"  [{g.id[:8]}] pri={g.priority:.2f} {g.description[:65]}")

        proposed = ctx.goal_store.get_proposed()
        if proposed:
            lines.append(f"\n*Proposed ({len(proposed)}):*")
            for g in sorted(proposed, key=lambda x: x.priority, reverse=True)[:10]:
                lines.append(f"  [{g.id[:8]}] pri={g.priority:.2f} {g.description[:65]}")

        # Stats
        stats = ctx.goal_store.stats()
        abandoned = stats["by_status"].get("abandoned", 0)
        achieved = stats["by_status"].get("achieved", 0)
        if abandoned or achieved:
            lines.append(f"\nZakonczone: {achieved} achieved, {abandoned} abandoned")

        return "\n".join(lines) if lines else "Brak celow"

    def _cmd_approve(args):
        """Approve a proposed goal by ID prefix."""
        if not ctx.goal_store or not args:
            return "Uzycie: approve <id-prefix>"
        prefix = args.strip()
        proposed = ctx.goal_store.get_proposed()
        match = [g for g in proposed if g.id.startswith(prefix)]
        if not match:
            return f"Nie znaleziono celu: {prefix}"
        if len(match) > 1:
            return f"Wiele dopasowani ({len(match)}), podaj dluzszy prefix"
        goal = match[0]
        ctx.goal_store.confirm(goal.id)
        ctx.goal_store.save()
        return f"Zatwierdzono: {goal.description[:80]}"

    def _cmd_reject(args):
        """Reject a proposed goal by ID prefix."""
        if not ctx.goal_store or not args:
            return "Uzycie: reject <id-prefix>"
        prefix = args.strip()
        proposed = ctx.goal_store.get_proposed()
        match = [g for g in proposed if g.id.startswith(prefix)]
        if not match:
            return f"Nie znaleziono celu: {prefix}"
        if len(match) > 1:
            return f"Wiele dopasowani ({len(match)}), podaj dluzszy prefix"
        goal = match[0]
        ctx.goal_store.reject(goal.id)
        ctx.goal_store.save()
        return f"Odrzucono: {goal.description[:80]}"

    def _cmd_test_propose(args):
        """[DEBUG] Inject a stub PROPOSED goal to verify GOAL_PROPOSED Phase 13 alert.

        Usage: /test_propose [opis]
        Phase 13 tick (~60s) zauwazy nowe id i wysle GOAL_PROPOSED alert.
        """
        if not ctx.goal_store:
            return "GoalStore not available"
        from agent_core.goals.goal_model import (
            GoalStatus,
            GoalType,
            create_goal,
        )
        desc = (args or "").strip() or (
            "TEST stub PROPOSED goal — weryfikacja powiadomienia GOAL_PROPOSED"
        )
        goal = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description=desc,
            priority=0.5,
            status=GoalStatus.PROPOSED,
            created_by="test_propose_cmd",
            metadata={"debug": True, "test_stub": True},
        )
        goal_id = ctx.goal_store.propose(goal)
        if goal_id is None:
            return "propose() returned None (displaced lub capacity)"
        ctx.goal_store.save()
        return (
            f"Stub PROPOSED utworzony: {goal_id[:8]}\n"
            f"Czekaj ~60s na alert Phase 13 (GOAL_PROPOSED)."
        )

    def _cmd_restart(args):
        """Restart Maria gracefully (systemd brings her back in ~10s).

        Old behaviour was os._exit(1), which skipped the SIGTERM/SIGINT
        signal handlers and therefore graceful_shutdown(), so the
        consciousness checkpoint never ran and personality_experiences.jsonl
        never got flushed. Now we mark a restart flag, send SIGTERM to
        ourselves, let maria.py's signal handler trigger graceful_shutdown,
        and exit 1 from the launcher so systemd Restart=on-failure picks
        us back up.
        """
        import os
        import signal as _signal

        # Uczciwa zapowiedz (audyt 2026-06-12): gdy restart trafia w biezaca
        # prace (planner/teacher/egzamin/wywolanie LLM), zamkniecie dokancza
        # ja z gracja (maria._finalize_exit, cap 15s) -- operator ma wiedziec,
        # ze to potrwa, zamiast myslec ze restart nie zaszedl.
        _busy = any(
            t.is_alive() and t.name in (
                "PlannerCycle", "TeacherAutoSession", "TgExamOnDemand",
            )
            for t in threading.enumerate()
        )
        if not _busy:
            try:
                from agent_core.llm.execution_budget import llm_workers_busy
                _busy = llm_workers_busy() > 0
            except Exception:
                pass
        if _busy:
            bridge.notifier.send_raw(
                "Restarting M.A.R.I.A. ... wlasnie nad czyms pracuje -- "
                "dokonczam, zapisuje i wracam (~30-60s)"
            )
        else:
            bridge.notifier.send_raw("Restarting M.A.R.I.A. ... (wraca za ~10s)")

        def _delayed_graceful_exit():
            time.sleep(2)
            try:
                from agent_core.runtime_flags import request_restart
                request_restart()
            except Exception:
                pass
            # SIGTERM is caught by maria.py main(); _shutdown.set() then
            # makes run_daemon() return, which runs graceful_shutdown().
            os.kill(os.getpid(), _signal.SIGTERM)

        t = threading.Thread(target=_delayed_graceful_exit, daemon=True)
        t.start()
        return None  # Message already sent via send_raw

    def _cmd_priority(args):
        """Set priority for a goal: /priority <id-prefix> <0.0-1.0>"""
        from agent_core.goals.goal_model import AuditEntry
        if not ctx.goal_store or not args:
            return "Uzycie: /priority <id-prefix> <0.0-1.0>"
        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            return "Uzycie: /priority <id-prefix> <0.0-1.0>"
        prefix = parts[0]
        try:
            new_pri = float(parts[1])
        except ValueError:
            return f"Nieprawidlowy priorytet: {parts[1]}"
        if not (0.0 <= new_pri <= 1.0):
            return "Priorytet musi byc 0.0-1.0"

        # Search in proposed + active goals
        candidates = ctx.goal_store.get_proposed() + ctx.goal_store.get_active()
        match = [g for g in candidates if g.id.startswith(prefix)]
        if not match:
            return f"Nie znaleziono celu: {prefix}"
        if len(match) > 1:
            return f"Wiele dopasowani ({len(match)}), podaj dluzszy prefix"
        goal = match[0]
        old_pri = goal.priority
        goal.priority = new_pri
        goal.updated_at = time.time()
        goal.audit_trail.append(AuditEntry(
            timestamp=time.time(),
            old_status=goal.status.value,
            new_status=goal.status.value,
            reason=f"priority {old_pri:.2f} -> {new_pri:.2f} (operator)",
            actor="operator",
        ))
        ctx.goal_store._mark_dirty(goal.id)
        ctx.goal_store.save()
        return f"Priorytet {goal.description[:60]}: {old_pri:.2f} -> {new_pri:.2f}"

    def _cmd_learn(args):
        """Create a learning goal from Telegram: /learn <topic>"""
        if not args or not args.strip():
            return "Uzycie: /learn <temat>\nPrzyklad: /learn fizyka kwantowa"
        topic = args.strip()
        try:
            from agent_core.perception.conversation_learning import process_user_message
            result = process_user_message(f"naucz sie o {topic}", ctx, channel="telegram")
            if result and result.get("goal_id"):
                return f"Dodam do nauki: '{result['topic']}'"
            else:
                return f"Nie udalo sie utworzyc celu dla: '{topic}'"
        except Exception as e:
            return f"Blad: {e}"

    def _cmd_codexwrite(args):
        """Ask Codex (ChatGPT) to write a Polish article into input/codex_<slug>.txt.

        Operator-gated; rate-limited via CodexClient (10 calls/h).
        """
        if not args or not args.strip():
            return (
                "Uzycie: /codexwrite <temat>\n"
                "Przyklad: /codexwrite mechanika kwantowa\n"
                "Codex napisze artykul (~600-1200 slow) i zostanie on "
                "dodany do input/ jako codex_<slug>.txt do dalszej nauki."
            )
        topic = args.strip()

        import threading
        from pathlib import Path as _Path

        def _run_codex_write():
            try:
                from agent_core.llm.codex_client import CodexClient
                from agent_core.web_source.codex_writer import request_codex_article
                from agent_core.web_source.content_writer import ContentWriter
                from agent_core.web_source.fetch_registry import FetchRegistry

                codex = CodexClient(timeout_s=300)
                registry = FetchRegistry()
                writer = ContentWriter(fetch_registry=registry)

                bridge.bot.send_message(
                    f"[Codex Write] Pracuje nad artykulem: {topic[:80]}...\n"
                    f"(timeout 5 min, limit 10/h)"
                )

                outcome = request_codex_article(
                    topic=topic,
                    codex_client=codex,
                    writer=writer,
                    semantic_search=getattr(ctx, "semantic_search", None),
                    operator="telegram",
                )

                if outcome["ok"]:
                    bridge.bot.send_message(
                        f"[Codex Write] Zapisano: {outcome['filename']} "
                        f"({outcome['chars']} znakow, "
                        f"{outcome['duration_ms']/1000:.1f}s).\n"
                        f"Maria pobierze do nauki w nastepnym cyklu."
                    )
                else:
                    bridge.bot.send_message(
                        f"[Codex Write] Nie zapisano: {outcome['reason']} "
                        f"(temat: {topic[:80]})"
                    )
            except Exception as exc:
                logger.exception("[Codex Write] failed")
                try:
                    bridge.bot.send_message(f"[Codex Write] Blad: {exc}")
                except Exception:
                    pass

        threading.Thread(target=_run_codex_write, daemon=True).start()
        return f"[Codex Write] zaczynam pisac: {topic[:80]}..."

    def _cmd_trace(args):
        """Show recent decision traces."""
        trace_store = getattr(ctx, 'trace_store', None)
        if not trace_store:
            return "TraceStore niedostepny."

        args = args.strip()
        # /trace <episode_id> - show specific trace
        if args and args.startswith("ep-"):
            t = trace_store.get_by_episode_id(args)
            if not t:
                return f"Trace {args} nie znaleziony."
            steps_text = ""
            for s in t.get("steps", [])[:8]:
                steps_text += f"  {s['subsystem']}: {s['action']} -> {s['result']}\n"
            return (
                f"*Trace {t['episode_id'][-8:]}*\n"
                f"Action: {t.get('action_type', '?')}\n"
                f"Goal: {t.get('goal_description', '-')[:40]}\n"
                f"K7: {t.get('k7_decision', '-')}\n"
                f"Success: {t.get('success')}\n"
                f"Duration: {t.get('duration_ms', 0):.0f}ms\n"
                f"LLM calls: {t.get('total_llm_calls', 0)}\n"
                f"Steps:\n{steps_text}"
            )

        # /trace stats - aggregate stats
        if args == "stats":
            stats = trace_store.get_stats()
            at = stats.get("action_types", {})
            at_text = ", ".join(f"{k}:{v}" for k, v in sorted(at.items(), key=lambda x: -x[1])[:5])
            return (
                f"*Trace stats* (last {stats['total']})\n"
                f"OK: {stats.get('success', 0)} | FAIL: {stats.get('failed', 0)}\n"
                f"K7 blocks: {stats.get('k7_blocks', 0)}\n"
                f"Avg: {stats.get('avg_duration_ms', 0):.0f}ms\n"
                f"LLM: {stats.get('total_llm_calls', 0)} calls\n"
                f"Actions: {at_text}"
            )

        # /trace failed - recent failures
        if args == "failed":
            failed = trace_store.get_failed(limit=5)
            if not failed:
                return "Brak ostatnich bledow."
            lines = []
            for t in failed:
                eid = t.get("episode_id", "?")[-8:]
                action = t.get("action_type", "?")
                k7 = t.get("k7_decision", "")
                summary = t.get("result_summary", "")[:40]
                lines.append(f"[{eid}] {action} K7:{k7} - {summary}")
            return "*Ostatnie bledy:*\n" + "\n".join(lines)

        # /trace - show last N traces (default 5)
        limit = 5
        if args.isdigit():
            limit = min(int(args), 10)
        recent = trace_store.get_recent(limit=limit)
        if not recent:
            return "Brak traces."
        lines = []
        for t in recent:
            eid = t.get("episode_id", "?")[-8:]
            action = t.get("action_type", "?")
            ok = "OK" if t.get("success") else "FAIL"
            dur = t.get("duration_ms", 0)
            goal = (t.get("goal_description") or "-")[:25]
            lines.append(f"[{eid}] {action} {ok} {dur:.0f}ms - {goal}")
        return "*Ostatnie trace:*\n" + "\n".join(lines)

    def _cmd_memory(args):
        """Query Maria's knowledge about a topic."""
        topic = args.strip()
        if not topic:
            return "Uzycie: /memory <temat>\nNp. /memory fizyka\n/memory gaps"

        memory_query = getattr(ctx, 'memory_query', None)
        if not memory_query:
            return "MemoryQuery niedostepny."

        try:
            # /memory gaps - knowledge gap analysis
            if topic.lower() == "gaps":
                gaps = memory_query.get_knowledge_gaps(top_k=5)
                if not gaps:
                    return "Brak luk w wiedzy."
                lines = ["*Luki w wiedzy:*"]
                for g in gaps:
                    lines.append(f"- {g['topic']}: {g['confidence']:.0%} ({g['reason']})")
                return "\n".join(lines)

            # /memory <topic> - query knowledge
            summary = memory_query.get_topic_summary(topic)
            if not summary.get("known"):
                return f"Nie mam wiedzy o: {topic}"

            results = memory_query.query_topic(topic, top_k=5)
            lines = [
                f"*Wiedza o '{topic}':*",
                f"Pliki: {summary.get('files_count', 0)}, przekonania: {summary.get('beliefs_count', 0)}",
                f"Pewnosc: {summary.get('avg_confidence', 0):.0%}, swiezosc: {summary.get('freshness', 0):.0%}",
                "",
            ]
            for r in results[:5]:
                src = r.source.value[:4]
                lines.append(f"[{src}] {r.content[:60]}")

            return "\n".join(lines)
        except Exception as e:
            return f"Blad: {e}"

    # -- Phase 5: Effector commands --

    def _cmd_do(args):
        """Parse a free-form task description and submit it to the
        ApprovalQueue as an effector request.

        Usage: /do <task description>
        Example: /do napisz plik /tmp/test.txt z trescia 'hello'
        """
        if not args or not args.strip():
            from agent_core.effector.intent_detector import TaskIntentDetector
            lines = ["*Uzycie:* /do <opis zadania>", "", "*Przyklady:*"]
            for ex in TaskIntentDetector().help_examples():
                lines.append(f"  /do {ex}")
            return "\n".join(lines)

        # T-IR-002: IntentRouter cheap-first dispatch. When INTENT_ROUTER_ENABLED
        # is false, router.route() always returns openclaw_raw and we fall
        # through to the legacy ApprovalQueue path unchanged.
        router = getattr(ctx, 'intent_router', None)
        if router is not None:
            try:
                match = router.route(args.strip())
                if match.path == "local":
                    return router.route_and_execute(args.strip())
            except Exception as e:
                logger.warning(f"IntentRouter route failed, falling through: {e}")

        queue = getattr(ctx, 'approval_queue', None)
        if queue is None:
            return "Blad: ApprovalQueue niedostepna (Phase 5 nie zainicjalizowany?)"

        from agent_core.effector.intent_detector import TaskIntentDetector
        from agent_core.effector.tool_specs import validate_args, is_tool_allowed

        detector = TaskIntentDetector()
        intent = detector.detect(args.strip())
        if intent is None:
            examples = "\n".join(f"  /do {ex}" for ex in detector.help_examples())
            return f"Nie rozumiem zadania. Sprobuj:\n{examples}"

        if not is_tool_allowed(intent.tool_name):
            return f"Narzedzie '{intent.tool_name}' nie jest dozwolone."

        valid, reason = validate_args(intent.tool_name, intent.tool_args)
        if not valid:
            return f"Niepoprawne argumenty dla {intent.tool_name}: {reason}"

        # Submit to queue — operator approves via /efapprove.
        request = queue.submit(
            plan_id=f"do-{int(time.time())}",
            tool_name=intent.tool_name,
            tool_args=intent.tool_args,
            goal_description=f"[/do] {args.strip()[:120]}",
            authority_level="operator_request",
        )

        if request.status == "rejected":
            return "ApprovalQueue pelna — odrzucono zgloszenie. Zwolnij miejsce (/efstatus)."

        # Notify operator via Telegram so they get the /efapprove shortcut.
        notifier = getattr(ctx, 'telegram_notifier', None)
        if notifier and hasattr(notifier, 'notify_effector_approval'):
            try:
                notifier.notify_effector_approval(
                    tool_name=intent.tool_name,
                    tool_args=intent.tool_args,
                    goal_description=request.goal_description,
                    authority_level=request.authority_level,
                    request_id=request.request_id,
                )
            except Exception as e:
                logger.debug(f"notify_effector_approval failed: {e}")

        prefix = request.request_id[:12]
        return (
            f"Zgloszono: {intent.tool_name} ({intent.pattern_id})\n"
            f"ID: {prefix}\n"
            f"Zatwierdz: /efapprove {prefix}\n"
            f"Odrzuc:    /efreject {prefix}"
        )

    def _cmd_efapprove(args):
        """Approve a pending effector request."""
        queue = getattr(ctx, 'approval_queue', None)
        if not queue or not args:
            return "Uzycie: /efapprove <request-id-prefix>"
        prefix = args.strip()
        approved = queue.approve(prefix)
        if not approved:
            return f"Nie znaleziono oczekujacego requestu: {prefix}"
        return f"Zatwierdzono efektor: {approved.tool_name} ({approved.request_id[:12]})"

    def _cmd_efreject(args):
        """Reject a pending effector request."""
        queue = getattr(ctx, 'approval_queue', None)
        if not queue or not args:
            return "Uzycie: /efreject <request-id-prefix>"
        prefix = args.strip()
        rejected = queue.reject(prefix)
        if not rejected:
            return f"Nie znaleziono oczekujacego requestu: {prefix}"
        return f"Odrzucono efektor: {rejected.tool_name} ({rejected.request_id[:12]})"

    def _cmd_efstatus(args):
        """Show effector authority status and pending requests."""
        parts = []

        auth_mgr = getattr(ctx, 'authority_manager', None)
        if auth_mgr:
            status = auth_mgr.get_status()
            parts.append(f"*Authority level:* {status['authority_level']}")

        queue = getattr(ctx, 'approval_queue', None)
        if queue:
            stats = queue.get_stats()
            parts.append(f"Pending: {stats['pending']}, Approved: {stats['approved']}")
            pending = queue.get_pending()
            for p in pending[:5]:
                parts.append(f"  [{p.request_id[:8]}] {p.tool_name} - {p.goal_description[:40]}")

        budget = getattr(ctx, 'tool_budget', None)
        if budget:
            bstats = budget.get_stats()
            for tool, ts in bstats.items():
                if ts['consecutive_failures'] > 0 or ts['locked']:
                    parts.append(f"  {tool}: {ts['invocations_this_window']}/{ts['rate_limit']} "
                                 f"fails={ts['consecutive_failures']} locked={ts['locked']}")

        return "\n".join(parts) if parts else "Brak danych efektora"

    def _cmd_authority(args):
        """Change effector authority level."""
        from agent_core.autonomy.authority_level import AuthorityLevel

        auth_mgr = getattr(ctx, 'authority_manager', None)
        if not auth_mgr:
            return "AuthorityManager niedostepny"

        arg = args.strip().lower()
        if not arg:
            level = auth_mgr.get_level()
            return (
                f"*Aktualny level:* {level.value}\n"
                "Dostepne: observe, suggest, confirm, bounded\n"
                "Uzycie: /authority <level>"
            )

        try:
            new_level = AuthorityLevel(arg)
        except ValueError:
            return f"Nieznany level: {arg}. Dostepne: observe, suggest, confirm, bounded"

        ok = auth_mgr.set_level(new_level)
        if not ok:
            return f"Nie mozna ustawic: {arg} (max: bounded)"

        # On downgrade, reject pending approvals
        queue = getattr(ctx, 'approval_queue', None)
        if queue and new_level.value in ("observe", "suggest"):
            rejected = queue.reject_all_pending("authority_downgrade")
            if rejected > 0:
                return f"Authority: {new_level.value} (odrzucono {rejected} oczekujacych)"

        return f"Authority: {new_level.value}"

    def _cmd_trust(args):
        """Show trust scores and promotion status."""
        scorer = getattr(ctx, 'trust_scorer', None)
        if not scorer:
            return "TrustScorer niedostepny"

        arg = args.strip().lower()

        if arg == "incidents":
            mem = getattr(ctx, 'incident_memory', None)
            if not mem:
                return "IncidentMemory niedostepny"
            stats = mem.get_stats()
            recent = mem.get_recent(limit=5)
            lines = [
                f"*Incydenty:* {stats['total']} (nierozwiazane: {stats['unresolved']}, 7d: {stats['recent_7d']})",
            ]
            for inc in reversed(recent):
                age = inc.age_days()
                lines.append(f"  [{inc.severity}] {inc.action_type}: {inc.error_type} ({age:.1f}d ago)")
            return "\n".join(lines)

        if arg == "promotion":
            promo = getattr(ctx, 'auto_promotion', None)
            if not promo:
                return "AutoPromotion niedostepny"
            status = promo.get_status()
            lines = [
                f"*AutoPromotion:*",
                f"Pending: {status['pending_goal_id'] or 'brak'}",
                f"Probacja: {'tak' if status['in_probation'] else 'nie'}",
            ]
            if status['in_probation']:
                lines.append(f"Pozostalo: {status['probation_remaining_days']:.1f} dni")
            history = promo.get_history(limit=3)
            if history:
                lines.append("Ostatnie:")
                for h in reversed(history):
                    lines.append(f"  {h['event_type']}: {h['from_level']}->{h['to_level']} (trust:{h['trust_score']:.2f})")
            return "\n".join(lines)

        # Default: show dashboard
        dash = scorer.get_dashboard()
        lines = [
            f"*Trust Dashboard:*",
            f"Authority: {dash['current_authority']}",
            f"Sredni trust: {dash['average_trust']:.3f}",
            f"Probacja: {'tak' if dash['in_probation'] else 'nie'}",
        ]
        if dash['promotion_available'] and dash['promotion']:
            p = dash['promotion']
            lines.append(f"Awans dostepny: {p['current_level']}->{p['proposed_level']} (trust:{p['trust_score']:.2f})")

        scores = dash.get('trust_scores', {})
        if scores:
            lines.append("Wyniki per typ:")
            for at, ts in sorted(scores.items()):
                marker = "+" if ts['has_enough_data'] else "?"
                lines.append(f"  {marker} {at}: {ts['score']:.3f} ({ts['total_actions']} akcji)")

        return "\n".join(lines)

    def _cmd_validate(args):
        """Show cross-validation stats and disputes."""
        cv = getattr(ctx, 'cross_validator', None)
        dl = getattr(ctx, 'dispute_log', None)

        args = args.strip()

        # /validate disputes - recent disputes
        if args == "disputes":
            if not dl:
                return "DisputeLog niedostepny."
            recent = dl.get_recent(limit=10)
            if not recent:
                return "Brak sporow."
            lines = []
            for d in recent:
                rec = d if isinstance(d, dict) else d.to_dict()
                fid = rec.get("file_id", "?")[:20]
                dim = rec.get("dimension", "?")
                sev = rec.get("severity", "?")
                lines.append(f"  [{fid}] {dim} (sev={sev})")
            return "*Ostatnie spory:*\n" + "\n".join(lines)

        # /validate unresolved - unresolved disputes
        if args == "unresolved":
            if not dl:
                return "DisputeLog niedostepny."
            unresolved = dl.get_unresolved()
            if not unresolved:
                return "Brak nierozwiazanych sporow."
            lines = []
            for d in unresolved[:10]:
                rec = d if isinstance(d, dict) else d.to_dict()
                fid = rec.get("file_id", "?")[:20]
                dim = rec.get("dimension", "?")
                lines.append(f"  [{fid}] {dim}")
            return f"*Nierozwiazane ({len(unresolved)}):*\n" + "\n".join(lines)

        # /validate - stats overview (default)
        parts = ["*Cross-Validation (Faza F):*"]
        if cv:
            stats = cv.get_stats()
            parts.append(
                f"Validated: {stats.get('chunks_validated', 0)} chunks\n"
                f"Agreed: {stats.get('chunks_agreed', 0)}\n"
                f"Disputed: {stats.get('chunks_disputed', 0)}\n"
                f"Avg confidence: {stats.get('avg_confidence', 0):.2f}"
            )
        else:
            parts.append("CrossValidator niedostepny (brak NIM?).")

        if dl:
            dl_stats = dl.get_stats()
            parts.append(
                f"\n*Disputes:*\n"
                f"Total: {dl_stats.get('total', 0)}\n"
                f"Unresolved: {dl_stats.get('unresolved', 0)}"
            )

        return "\n".join(parts)

    def _cmd_nauka(args):
        """Show learning goals and their progress."""
        gs = getattr(ctx, 'goal_store', None)
        if not gs:
            return "GoalStore niedostepny."

        args = args.strip()

        # /nauka <topic> - search by topic
        if args:
            goals = gs.find_by_topic(args)
            if not goals:
                return f"Brak celow nauki o '{args}'."
            lines = [f"*Nauka: {args}*"]
            for g in goals[:5]:
                status = g.status.value
                progress = f"{g.progress:.0%}"
                age = time.time() - g.created_at
                age_str = f"{age/3600:.0f}h" if age < 86400 else f"{age/86400:.0f}d"
                line = f"  [{g.id[:8]}] {status} | {progress} | {age_str} temu"
                if g.outcome:
                    score = g.outcome.get("final_score", 0)
                    line += f" | wynik: {score:.0%}"
                lines.append(line)
            return "\n".join(lines)

        # /nauka - list all LEARNING goals
        from agent_core.goals.goal_model import GoalType
        all_goals = [g for g in gs._goals.values() if g.type == GoalType.LEARNING]
        if not all_goals:
            return "Brak celow nauki."

        active = [g for g in all_goals if g.is_active]
        done = [g for g in all_goals if g.status.value == "achieved"]

        lines = [f"*Cele nauki: {len(active)} aktywnych, {len(done)} ukonczonych*"]
        for g in sorted(active, key=lambda x: x.priority, reverse=True)[:8]:
            topic = g.metadata.get("topic", g.description[:25])
            lines.append(f"  [{g.id[:8]}] {topic} | {g.progress:.0%} | pri={g.priority:.1f}")

        if done:
            lines.append(f"\n*Ukonczone ({len(done)}):*")
            for g in sorted(done, key=lambda x: x.updated_at, reverse=True)[:5]:
                topic = g.metadata.get("topic", g.description[:25])
                score = ""
                if g.outcome:
                    score = f" | wynik: {g.outcome.get('final_score', 0):.0%}"
                lines.append(f"  [{g.id[:8]}] {topic}{score}")

        return "\n".join(lines)

    def _cmd_beliefs(args):
        """Show belief store stats and run maintenance."""
        wm = getattr(ctx, 'world_model', None)
        if not wm:
            return "WorldModel niedostepny."

        args = args.strip()

        # /beliefs maintain - run full maintenance. Passes the LIVE semantic
        # memory (ctx.semantic_search) so the operator's manual verification
        # path exercises the same semantic-dedup phase as the planner's
        # post-EVALUATE maintain() -- a bare call here would silently skip
        # the semantic phase and look like the feature is dead (2026-06-10).
        # Safe concurrently: WorldModel._maintenance_lock makes the loser
        # skip with {"skipped": "maintenance_in_progress"}.
        if args == "maintain":
            try:
                results = wm.maintain(
                    semantic_memory=getattr(ctx, "semantic_search", None)
                )
                parts = ["*Belief maintenance complete:*"]
                for k, v in results.items():
                    parts.append(f"  {k}: {v}")
                return "\n".join(parts)
            except Exception as e:
                return f"Blad maintenance: {e}"

        # /beliefs gaps - weakest topics
        if args == "gaps":
            try:
                gaps = wm.query.get_knowledge_gaps()[:10]
                if not gaps:
                    return "Brak luk w wiedzy."
                lines = ["*Najslabsze tematy:*"]
                for g in gaps:
                    lines.append(
                        f"  {g['topic']}: {g['confidence']:.0%} "
                        f"({g.get('belief_count', '?')} beliefs)"
                    )
                return "\n".join(lines)
            except Exception as e:
                return f"Blad: {e}"

        # /beliefs - stats overview (default)
        try:
            stats = wm.stats()
            by_type = stats.get("by_belief_type", {})
            by_etype = stats.get("by_entity_type", {})
            return (
                f"*Belief Store v2:*\n"
                f"Active: {stats.get('total', 0)} beliefs\n"
                f"All records: {stats.get('total_all', 0)}\n"
                f"Avg confidence: {stats.get('avg_confidence', 0):.0%}\n"
                f"\n*By type:*\n"
                f"  FACT: {by_type.get('fact', 0)}\n"
                f"  OBSERVATION: {by_type.get('observation', 0)}\n"
                f"  HYPOTHESIS: {by_type.get('hypothesis', 0)}\n"
                f"\n*By entity:*\n"
                f"  Topics: {by_etype.get('topic', 0)}\n"
                f"  Files: {by_etype.get('file', 0)}\n"
                f"  Concepts: {by_etype.get('concept', 0)}"
            )
        except Exception as e:
            return f"Blad: {e}"

    # One synthesis at a time per process: the cycle holds the sandbox
    # singleton for minutes (NIM synth + sandbox exam), and a second
    # concurrent run would only bounce off "sandbox_busy" later anyway.
    _synthesis_lock = threading.Lock()

    def _format_synthesis_report(report) -> str:
        """Plain-text result for Telegram. file_id wrapped in backticks:
        synthesis ids carry BALANCED underscores, which bare Markdown
        eats silently (the 2026-06-09 /approve_note lesson)."""
        if not report.get("success"):
            reasons = {
                "insufficient_material": (
                    "Za malo materialu - temat musi wystepowac w >=2 "
                    "ROZNYCH plikach zrodlowych. /synthesize bez "
                    "argumentu pokaze gotowe tematy."
                ),
                "llm_failed": "Synteza LLM nie odpowiedziala (NIM/local).",
                "parse_failed": "LLM nie zwrocil poprawnego JSON syntezy.",
                "summary_too_short": "Synteza za plytka (krotkie podsumowanie).",
                "too_few_key_points": "Synteza za plytka (<3 punkty).",
                "mostly_verbatim_copies": (
                    "Odrzucona: LLM przepisal punkty zrodlowe 1:1 "
                    "zamiast syntetyzowac."
                ),
                "sandbox_busy": "Piaskownica zajeta przez inna sesje.",
                "cycle_error": f"Blad cyklu: {report.get('error', '?')}",
                "unfaithful_to_sources": (
                    "Odrzucona przez bramke wiernosci: twierdzenia nie "
                    "trzymaja sie zrodel (sprzeczne albo konfabulacja)."
                ),
            }
            reason = report.get("reason", "?")
            return f"[Synteza] NIE wyszlo. {reasons.get(reason, reason)}"

        exam = report.get("exam", {})
        lines = [
            "[Synteza] Cykl ukonczony.",
            f"Temat: {report.get('topic')}",
            f"Plik: `{report.get('file_id')}`",
            f"Zrodla: {', '.join(report.get('source_files', []))}",
            (
                f"Egzamin niezalezny: {'ZDANY' if exam.get('passed') else 'OBLANY'}"
                f" ({exam.get('score', 0):.0%})"
                if exam.get("executed") else "Egzamin: NIE WYKONANY"
            ),
        ]
        faith = report.get("faithfulness")
        if isinstance(faith, dict) and faith.get("total"):
            lines.append(
                f"Wiernosc zrodlom: {faith.get('supported')}/{faith.get('total')}"
                f" poparte, {faith.get('unstated', 0)} niewypowiedz., "
                f"{faith.get('contradicted', 0)} sprzeczne "
                f"(sedzia {faith.get('judge_model', '?')})"
            )
        if report.get("promoted"):
            lines.append(
                "PROMOTED -> produkcja. Beliefs powstana przy nastepnym "
                "rebuildzie (watermark widzi zmiane zrodel)."
            )
        elif report.get("would_promote"):
            lines.append(
                "Tryb observe: synteza ZDALA i POSZLABY do produkcji. "
                "Uzbrojenie: SYNTH_ENABLED=1 w .env + restart."
            )
        else:
            lines.append("Sesja odrzucona (egzamin niezdany) - produkcja czysta.")
        return "\n".join(lines)

    def _run_synthesis_cycle(topic: str):
        """Build the full wiring (mirrors the teacher's exam wiring) and
        run one synthesis cycle. Executes in a background thread."""
        from maria_core.sys.config import (
            EXAM_RESULTS, KNOWLEDGE_INDEX, LONGTERM_MEMORY, OLLAMA_MODEL,
            SANDBOX_DIR,
        )
        from maria_core.sys.config import (
            EXAM_ANSWER_HTTP_TIMEOUT_SEC, EXAM_ANSWER_TIMEOUT_SEC,
        )
        from contextlib import nullcontext

        from maria_core.learning.llm_utils import call_ollama
        from agent_core.llm.execution_budget import call_with_timeout
        from agent_core.modules.teacher_module import (
            _make_exam_author_fn,
            _make_exam_grader_fn,
            _make_nim_first_examiner_fn,
        )
        from agent_core.sandbox.manager import SandboxManager
        from agent_core.synthesis import SynthesisAgent

        scheduler = getattr(ctx, "model_scheduler", None)
        student_model = OLLAMA_MODEL
        examiner_model = (
            "qwen3:8b" if student_model != "qwen3:8b" else "llama3.1:8b"
        )

        # Composition needs the big model; NIM-first with the same honest
        # local fallback the exams use (qwen3 -- heavier than the student,
        # serialized on the heavy mutex by the factory).
        synth_fn = _make_nim_first_examiner_fn(
            examiner_model, role="synthesis", temperature=0.3,
            max_tokens=4096, nim_timeout=180, fallback_num_predict=2048,
            scheduler=scheduler,
        )
        grader_fn = _make_exam_grader_fn(examiner_model, scheduler=scheduler)
        author_fn = _make_exam_author_fn(examiner_model, scheduler=scheduler)

        def student_fn(prompt):
            # Same contract as the teacher's exam answer: heavy lease for
            # the full local call + a hard deadline.
            guard = (
                scheduler.heavy_lease("synthesis_exam_answer")
                if scheduler is not None else nullcontext()
            )
            with guard:
                return call_with_timeout(
                    lambda: call_ollama(
                        prompt, model=student_model, num_predict=2048,
                        num_ctx=8192, timeout=EXAM_ANSWER_HTTP_TIMEOUT_SEC,
                    ),
                    timeout_sec=EXAM_ANSWER_TIMEOUT_SEC,
                    label="synthesis_exam_answer",
                )

        def faithfulness_fn(prompt):
            # The source-faithfulness judge is LOCAL-ONLY (qwen3), never
            # NIM-first: it MUST be a different model from the synthesizer (NIM
            # dracarys), because a model rubber-stamps its own output. Heavy
            # lease + hard deadline like the exam answer; runs ~1/day so the
            # CPU cost is bounded, and it short-circuits before the exam.
            guard = (
                scheduler.heavy_lease("synthesis_faithfulness")
                if scheduler is not None else nullcontext()
            )
            with guard:
                # Dedicated, generous budget: the judge reads up to 12 (capped)
                # sources on CPU. Measured ~348s on a clean box for a 12-source
                # synthesis with /no_think + tight caps (live 2026-06-13), so
                # 540s gives ~190s headroom for a richer synthesis or mild load
                # -- the cost of fail-closing a GOOD synthesis (false reject) is
                # worse than a one-a-day ~6-min heavy-mutex hold. Output is a
                # short JSON verdict, so the predict cap stays low.
                return call_with_timeout(
                    lambda: call_ollama(
                        prompt, model=examiner_model, num_predict=400,
                        num_ctx=8192, timeout=530,
                    ),
                    timeout_sec=540,
                    label="synthesis_faithfulness",
                )

        grader_meta = {
            # NOTE: the exam grader is NIM-first, so this flag reflects the
            # fallback names, not the model that actually graded -- the real
            # groundedness signal is now the LOCAL faithfulness judge above, and
            # synthesis beliefs are capped at OBSERVATION regardless (Brick 3).
            "independent": examiner_model != student_model,
            "grader": f"nim-first|{examiner_model}",
            "student": student_model,
        }

        sandbox_mgr = getattr(ctx, "sandbox_manager", None)
        if sandbox_mgr is None:
            sandbox_mgr = SandboxManager(
                sandbox_base_dir=SANDBOX_DIR,
                production_index=KNOWLEDGE_INDEX,
                production_memory=LONGTERM_MEMORY,
                production_exams=EXAM_RESULTS,
            )

        # House three-step rollout: unset/observe -> full cycle, NO
        # promote; truthy -> promote on pass. Operator invocation is the
        # consent for the CYCLE; the flag arms only the production write.
        raw_flag = os.environ.get("SYNTH_ENABLED", "").strip().lower()
        mode = "promote" if raw_flag in ("1", "true", "yes", "on") else "observe"

        agent = SynthesisAgent(LONGTERM_MEMORY)
        report = agent.run_cycle(
            topic, sandbox_mgr, synth_fn, student_fn, grader_fn,
            generator_llm_fn=author_fn, grader_meta=grader_meta,
            faithfulness_llm_fn=faithfulness_fn, mode=mode,
        )
        # Record the model that ACTUALLY judged faithfulness (honest identity,
        # not a pre-declared name) so the review log shows it.
        if isinstance(report, dict) and isinstance(report.get("faithfulness"), dict):
            report["faithfulness"]["judge_model"] = examiner_model
        # Persist the synthesized artifact to the observe-window review log
        # BEFORE returning -- the sandbox session it lived in is already
        # discarded, so this jsonl is the operator's ONLY window into what
        # Maria actually synthesized (the go/no-go evidence for SYNTH_ENABLED).
        try:
            from pathlib import Path as _Path
            from agent_core.synthesis import append_synthesis_review
            _review_path = (
                _Path(ctx.homeostasis_core.event_logger.log_path).parent
                / "synthesis_review.jsonl"
            )
            append_synthesis_review(_review_path, report)
        except Exception:  # observability must never abort a synthesis
            pass
        return report

    def _cmd_synthesize(args):
        """Etap 2b: /synthesize [temat] - cross-source synthesis behind
        the sandbox + independent-exam gate (the first promote() caller)."""
        args = (args or "").strip()

        if not args:
            from maria_core.sys.config import LONGTERM_MEMORY
            from agent_core.synthesis import SynthesisAgent
            topics = SynthesisAgent(LONGTERM_MEMORY).topics(limit=10)
            if not topics:
                return (
                    "Brak tematow z materialem z >=2 zrodel - "
                    "synteza potrzebuje czego skrzyzowac."
                )
            lines = ["Tematy gotowe do syntezy (liczba zrodel):"]
            lines += [f"  {t['topic']} ({t['sources']})" for t in topics]
            lines.append("")
            lines.append("Uzycie: /synthesize <temat>")
            return "\n".join(lines)

        if not _synthesis_lock.acquire(blocking=False):
            return "Synteza juz trwa - poczekaj na jej wynik."

        topic = args

        def _run():
            try:
                report = _run_synthesis_cycle(topic)
                bridge.bot.send_message(_format_synthesis_report(report))
                bs = getattr(ctx, "bulletin_store", None)
                if bs and report.get("success"):
                    try:
                        from agent_core.bulletin.bulletin_model import EntryType
                        exam = report.get("exam", {})
                        bs.create_and_post(
                            entry_type=EntryType.NEED_REVIEW,
                            topic=f"Synteza: {report.get('topic')}",
                            reason_code="synthesis_cycle",
                            summary=(
                                f"file={report.get('file_id')} "
                                f"exam={'pass' if exam.get('passed') else 'fail'} "
                                f"score={exam.get('score', 0):.2f} "
                                f"mode={report.get('mode')} "
                                f"promoted={report.get('promoted')}"
                            ),
                            requested_by="synthesis",
                            metadata={
                                "file_id": report.get("file_id"),
                                "score": exam.get("score"),
                                "promoted": report.get("promoted"),
                                "source_files": report.get("source_files"),
                            },
                        )
                    except Exception:
                        pass
            except Exception as e:
                try:
                    bridge.bot.send_message(f"[Synteza] Blad: {e}")
                except Exception:
                    pass
            finally:
                _synthesis_lock.release()

        # Material check BEFORE spawning (live drill 2026-06-11): the
        # thread's instant insufficient_material message RACED ahead of
        # the "ruszyla w tle" reply, so a typo'd topic produced two
        # messages in reverse order. The check is a fast read-only scan,
        # safe inline; the answer arrives alone and with suggestions.
        spawned = False
        try:
            from maria_core.sys.config import LONGTERM_MEMORY
            from agent_core.synthesis import SynthesisAgent
            _agent = SynthesisAgent(LONGTERM_MEMORY)
            if _agent.gather(topic) is None:
                suggestions = _agent.topics(limit=5)
                hint = "\n".join(
                    f"  {t['topic']} ({t['sources']})" for t in suggestions
                )
                return (
                    f"Za malo materialu dla '{topic}' - temat musi "
                    "wystepowac w >=2 ROZNYCH plikach zrodlowych "
                    "(pisownia tagu musi sie zgadzac co do znaku).\n"
                    f"Najmocniejsze gotowe tematy:\n{hint}\n"
                    "Pelna lista: /synthesize"
                )
            threading.Thread(target=_run, daemon=True).start()
            spawned = True
            return (
                f"Synteza '{topic}' ruszyla w tle: NIM sklada zrodla, potem "
                f"niezalezny egzamin w piaskownicy (~5-10 min). Dam znac."
            )
        finally:
            # The thread owns the release once spawned; every other exit
            # (no material, exception) must free the lock here.
            if not spawned:
                _synthesis_lock.release()

    def _maybe_autonomous_synthesis():
        """Etap 2b cegla E: Maria sama wybiera temat i syntetyzuje raz
        dziennie w oknie nauki. Wolane z fazy 10.8 ticku co ~10 min;
        picker pilnuje 24h cooldownu i wyboru tematu. Tryb observe
        dopoki SYNTH_ENABLED nieuzbrojony -- zero zapisow do produkcji.

        Lock wspoldzielony z /synthesize: jezeli operator wlasnie
        syntetyzuje, picker odpuszcza ten przebieg (non-blocking)."""
        from pathlib import Path
        from maria_core.sys.config import LONGTERM_MEMORY
        from agent_core.synthesis import SynthesisAgent
        from agent_core.synthesis.picker import (
            decide_synthesis, load_state, record_pick, save_state,
        )
        try:
            from agent_core.environment.environment_model import (
                is_learning_window,
            )
            in_window = is_learning_window()
        except Exception:
            in_window = False

        core_ref = ctx.homeostasis_core
        state_path = (
            Path(core_ref.event_logger.log_path).parent
            / "synthesis_picker_state.json"
        )
        state = load_state(state_path)
        eligible = SynthesisAgent(LONGTERM_MEMORY).topics(limit=10)

        decision = decide_synthesis(eligible, state, time.time(), in_window)
        if decision["action"] != "synthesize":
            return  # cooldown / poza oknem / brak tematow -- cicho, normalne

        if not _synthesis_lock.acquire(blocking=False):
            return  # operator (lub poprzedni pick) w trakcie -- nastepnym razem

        topic = decision["topic"]
        # Stempel budzetu dnia PRZED cyklem: nieudany przebieg nie ma
        # retry-stormu (lekcja NREM 2026-06-12 -- cooldown przezywa restart).
        save_state(state_path, record_pick(state, topic, time.time()))
        logger.info(
            "[Synthesis] autonomiczny pick: '%s' (%d zrodel, tryb observe-gate)",
            topic, decision.get("sources", 0),
        )

        def _run():
            try:
                report = _run_synthesis_cycle(topic)
                core_ref.event_logger._write_event({
                    "timestamp": time.time(),
                    "event": "autonomous_synthesis",
                    "topic": topic,
                    "file_id": report.get("file_id"),
                    "exam": report.get("exam"),
                    "mode": report.get("mode"),
                    "would_promote": report.get("would_promote"),
                    "promoted": report.get("promoted"),
                    "success": report.get("success"),
                    "reason": report.get("reason"),
                })
                logger.info(
                    "[Synthesis] autonomiczna synteza '%s': %s",
                    topic, report.get("exam") or report.get("reason"),
                )
                bs = getattr(ctx, "bulletin_store", None)
                if bs and report.get("success"):
                    try:
                        from agent_core.bulletin.bulletin_model import EntryType
                        exam = report.get("exam", {})
                        bs.create_and_post(
                            entry_type=EntryType.NEED_REVIEW,
                            topic=f"Auto-synteza: {report.get('topic')}",
                            reason_code="autonomous_synthesis",
                            summary=(
                                f"file={report.get('file_id')} "
                                f"exam={'pass' if exam.get('passed') else 'fail'} "
                                f"score={exam.get('score', 0):.2f} "
                                f"mode={report.get('mode')} "
                                f"promoted={report.get('promoted')}"
                            ),
                            requested_by="synthesis_picker",
                            metadata={
                                "file_id": report.get("file_id"),
                                "autonomous": True,
                            },
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(
                    "[Synthesis] autonomiczny cykl padl dla '%s': %s", topic, e,
                )
            finally:
                _synthesis_lock.release()

        threading.Thread(
            target=_run, daemon=True, name="AutoSynthesis",
        ).start()

    # Wepnij autonomiczny picker w tick (faza 10.8) -- raz dziennie,
    # okno nauki, observe. Bezpieczne nawet bez sandboxa: cykl sam
    # zbuduje fallback SandboxManager.
    try:
        ctx.homeostasis_core.set_synthesis_trigger(_maybe_autonomous_synthesis)
        logger.info("[Homeostasis] [OK] Autonomous synthesis picker wired (cegla E)")
    except Exception as e:
        logger.warning("Autonomous synthesis picker not wired: %s", e)

    def _cmd_synthreview(args):
        """Etap 2b observe window: /synthreview [n] -- show the last n
        synthesized artifacts (summary + key_points + sources + exam) from
        synthesis_review.jsonl. This is the go/no-go evidence for arming
        SYNTH_ENABLED: read WHAT Maria synthesized, not just a score.

        Plain-text (no Markdown): synthesis file_ids carry underscores that
        bare Markdown eats (the 2026-06-09 /approve_note lesson)."""
        from pathlib import Path as _Path
        from agent_core.synthesis import read_synthesis_reviews
        try:
            n = max(1, min(20, int((args or "").strip() or 5)))
        except (TypeError, ValueError):
            n = 5
        try:
            review_path = (
                _Path(ctx.homeostasis_core.event_logger.log_path).parent
                / "synthesis_review.jsonl"
            )
        except Exception:
            return "[Synteza] Nie moge ustalic sciezki logu recenzji."
        rows = read_synthesis_reviews(review_path, limit=n)
        if not rows:
            return (
                "[Synteza] Brak recenzji jeszcze. Pierwsza autonomiczna "
                "synteza w oknie nauki (lub /synthesize <temat>) zaloguje "
                "tu artefakt do oceny."
            )
        out = [f"[Synteza] Ostatnie {len(rows)} (najnowsze pierwsze):"]
        for r in rows:
            exam = r.get("exam") or {}
            score = exam.get("score")
            score_s = f"{score:.0%}" if isinstance(score, (int, float)) else "?"
            verdict = (
                "ZDANY" if exam.get("passed")
                else ("NIE WYK." if not exam.get("executed") else "OBLANY")
            )
            gate = (
                "PROMOTED" if r.get("promoted")
                else ("by-poszla" if r.get("would_promote") else "odrzut")
            )
            summary = (r.get("summary") or "").strip()
            if len(summary) > 280:
                summary = summary[:280].rstrip() + "..."
            kps = [str(k).strip() for k in (r.get("key_points") or []) if str(k).strip()]
            out.append("")
            out.append(
                f"- {r.get('topic', '?')} | egz {verdict} {score_s} | "
                f"{r.get('mode', '?')}/{gate}"
            )
            out.append(f"  plik: {r.get('file_id', '?')}")
            srcs = r.get("source_files") or []
            if srcs:
                out.append(f"  zrodla: {', '.join(str(s) for s in srcs)}")
            faith = r.get("faithfulness")
            if isinstance(faith, dict) and faith.get("total"):
                out.append(
                    f"  wiernosc: {faith.get('supported')}/{faith.get('total')}"
                    f" poparte, {faith.get('contradicted', 0)} sprzeczne"
                    + ("" if faith.get("ok") else " -> ODRZUT")
                )
            if r.get("reason") == "unfaithful_to_sources" and not faith:
                out.append("  ODRZUT: bramka wiernosci")
            if summary:
                out.append(f"  synteza: {summary}")
            for kp in kps[:6]:
                out.append(f"    * {kp}")
        return "\n".join(out)

    def _cmd_help(args):
        """List available commands grouped by category."""
        return (
            "*ClawBot - Komendy*\n"
            "\n*System:*\n"
            "/status - stan systemu\n"
            "/restart - restart Marii\n"
            "/authority [level] - autoryzacja\n"
            "/trust [incidents|promotion] - trust score i autonomia\n"
            "\n*Cele i zatwierdzanie:*\n"
            "/goals - lista celow\n"
            "/approve <id> - zatwierdz cel\n"
            "/reject <id> - odrzuc cel\n"
            "/priority <id> <0-1> - priorytet\n"
            "\n*Wiedza i nauka:*\n"
            "/learn <temat> - naucz sie\n"
            "/nauka [temat] - postep nauki\n"
            "/memory <temat> - co Maria wie\n"
            "/beliefs [gaps|maintain] - beliefs\n"
            "/synthesize [temat] - synteza wiedzy (sandbox+egzamin)\n"
            "/validate - cross-validation\n"
            "/board - tablica potrzeb\n"
            "\n*Kodowanie (Code Agent):*\n"
            "/code <zadanie> - zlec kodowanie\n"
            "/code approve - zatwierdz krok\n"
            "/code status - aktywna sesja\n"
            "/code history - historia\n"
            "\n*AI asystenci:*\n"
            "/claude <zadanie> - Claude (3/h)\n"
            "/codex <zadanie> - Codex/ChatGPT\n"
            "/analyze <modul> - analiza kodu\n"
            "\n*Przypomnienia i zadania:*\n"
            "/remind <tekst> <czas> - przypomnienie\n"
            "/remind list - lista przypomnien\n"
            "/remind dismiss <id> - usun\n"
            "/todo <tekst> - nowe zadanie\n"
            "/todo list - lista zadan\n"
            "/todo done <id> - oznacz zrobione\n"
            "\n*Proaktywnosc:*\n"
            "/proactive - status proaktywnego kontaktu\n"
            "/proactive on|off - wlacz/wylacz\n"
            "/proactive history - historia kontaktow\n"
            "/profile - profil operatora\n"
            "\n*Workflow (Faza 5):*\n"
            "/wf - lista aktywnych workflow\n"
            "/wf start <szablon> [temat]\n"
            "/wf pause|resume|cancel <id>\n"
            "/wf templates - szablony\n"
            "\n*Srodowisko (Faza 6):*\n"
            "/env - aktualny tryb\n"
            "/env switch <tryb> - przelacz\n"
            "/env list - dostepne tryby\n"
            "/env auto - auto-detekcja\n"
            "\n*Diagnostyka:*\n"
            "/tasks [N] - historia taskow Claude/Codex\n"
            "/pdf <task_id> - wyslij wynik jako PDF\n"
            "/trace [N|stats] - traces\n"
            "/do <zadanie> - zlec zadanie narzedziowe (write/read/fetch/search/exec)\n"
            "/efapprove <id> - zatwierdz efektor\n"
            "/efreject <id> - odrzuc efektor\n"
            "/efstatus - status efektora\n"
            "/list_repairs - otwarte self-repair tasks\n"
            "/approve_repair <id> - zatwierdz self-repair\n"
            "/drill_repair [force] - test self-repair na zywo (drill)\n"
            "/drill_heartbeat [force] - test czujnika pulsu watkow (drill)\n"
            "/drill_outbox - Maria proponuje notatke do outbox (Rung 2 hands)\n"
            "/list_notes - oczekujace notatki outbox\n"
            "/approve_note <id> - zatwierdz zapis notatki (pierwsza akcja na swiat)\n"
            "/reject_note <id> - odrzuc notatke"
        )

    def _cmd_board(args):
        """Show cognitive bulletin board status."""
        bs = getattr(ctx, 'bulletin_store', None)
        if not bs:
            return "BulletinStore niedostepny."

        args = args.strip()

        # /board stats
        if not args or args == "stats":
            s = bs.stats()
            lines = [
                "*Tablica potrzeb poznawczych:*",
                f"Otwarte: {s['open']}",
                f"Actionable: {s['actionable']}",
                f"Total: {s['total']}",
            ]
            if s["by_type"]:
                lines.append("\n*By type:*")
                for t, c in sorted(s["by_type"].items()):
                    lines.append(f"  {t}: {c}")
            return "\n".join(lines)

        # /board open - list open entries
        if args == "open":
            entries = bs.get_open()
            if not entries:
                return "Tablica pusta - brak otwartych potrzeb."
            lines = ["*Otwarte potrzeby:*"]
            for e in entries[:15]:
                status_icon = {
                    "open": "NEW", "in_progress": "WIP",
                    "blocked": "BLK",
                }.get(e.status.value, e.status.value)
                lines.append(
                    f"  [{status_icon}] {e.entry_type.value}: "
                    f"{e.topic} (pri={e.priority:.1f})"
                )
                if e.goal_id:
                    lines.append(f"    goal: {e.goal_id[:16]}")
            return "\n".join(lines)

        # /board prune - cleanup stale entries
        if args == "prune":
            pruned = bs.prune_stale()
            return f"Pruned {pruned} stale entries."

        return "Uzycie: /board [open|prune]"

    def _send_result_pdf(task_id, backend, task_text, result, duration_ms=None, timestamp=None):
        """Generate PDF from result and send via Telegram."""
        try:
            from agent_core.telegram.pdf_export import generate_task_pdf
            pdf_path = generate_task_pdf(
                task_id=task_id, backend=backend,
                task_text=task_text, result=result,
                duration_ms=duration_ms, timestamp=timestamp,
            )
            if pdf_path:
                bridge.bot.send_document(
                    pdf_path,
                    caption=f"[{backend}] {task_text[:80]}",
                )
        except Exception as e:
            logger.debug(f"PDF export failed: {e}")

    def _cmd_codex(args):
        """Execute code task via Codex CLI: /codex <task description>"""
        if not args or not args.strip():
            return (
                "Uzycie: /codex <opis zadania>\n"
                "Przyklad: /codex przeanalizuj modul critic i zaproponuj ulepszenia\n"
                "Przyklad: /codex znajdz TODO i FIXME w agent_core/planner/\n"
                "Przyklad: /codex napisz test dla funkcji compute_belief_score"
            )
        task = args.strip()

        # Run async in background thread
        import threading

        def _run_codex_task():
            from agent_core.llm.task_store import TaskStore
            store = TaskStore()
            task_id = store.create_task(
                task_text=task, backend="codex",
                source="telegram_codex", timeout_s=300,
            )
            try:
                from agent_core.llm.codex_client import CodexClient
                codex = CodexClient(timeout_s=300)
                if not codex.is_available():
                    store.mark_failed(task_id, "Codex CLI niedostepny")
                    bridge.bot.send_message("[Code] Codex CLI niedostepny.")
                    return

                # Build prompt with project context
                prompt = (
                    f"Projekt M.A.R.I.A. (Python, agent_core/). "
                    f"Zadanie od operatora: {task}"
                )

                store.mark_running(task_id)
                bridge.bot.send_message(
                    f"[Code] Pracuje nad: {task[:80]}...\n"
                    f"(task: {task_id}, timeout: 5min)"
                )

                result = codex.ask(prompt, source="telegram_code", context={"task": task})
                if result:
                    store.mark_completed(task_id, result[:500])
                    # Send full result as PDF
                    task_rec = store.get_task(task_id)
                    _send_result_pdf(
                        task_id, "codex", task, result,
                        duration_ms=task_rec.get("duration_ms") if task_rec else None,
                        timestamp=task_rec.get("created_at") if task_rec else None,
                    )
                    # Trim for Telegram (4096 char limit)
                    if len(result) > 3800:
                        result = result[:3800] + "\n...(obciete)"
                    bridge.bot.send_message(f"[Code] Wynik:\n\n{result}")

                    # Save to bulletin board
                    bs = getattr(ctx, 'bulletin_store', None)
                    if bs:
                        try:
                            from agent_core.bulletin.bulletin_model import EntryType
                            # add_entry bylo fantomem (audyt 2026-06-12);
                            # kanon to create_and_post (dedup po topic+type).
                            bs.create_and_post(
                                entry_type=EntryType.CODE_TASK,
                                topic=task[:100],
                                reason_code="code_task_result",
                                summary=result[:500],
                                requested_by="telegram_code",
                                metadata={"full_result_length": len(result), "task_id": task_id},
                            )
                        except Exception:
                            pass
                else:
                    # Check if it was a timeout (codex returns None on timeout)
                    store.mark_timeout(task_id, 300)
                    bridge.bot.send_message(
                        f"[Code] Brak odpowiedzi (timeout 5min).\n"
                        f"Task {task_id} zapisany - mozesz ponowic."
                    )
            except Exception as e:
                store.mark_failed(task_id, str(e)[:300])
                bridge.bot.send_message(f"[Code] Blad: {e}")

        t = threading.Thread(target=_run_codex_task, daemon=True)
        t.start()
        return f"Przyjeto zadanie: '{task[:60]}'. Wynik za chwile..."

    def _cmd_code(args):
        """Code Agent: /code <task|status|approve|reject|cancel|history>"""
        code_agent = getattr(ctx, 'code_agent', None)
        if not code_agent:
            return "Code Agent niedostepny."

        if not args or not args.strip():
            # Show status or help
            active = code_agent.get_active()
            if active:
                return active.describe()
            return (
                "*Code Agent - autonomiczne kodowanie*\n\n"
                "/code <zadanie> - zlec kodowanie\n"
                "/code status - aktywna sesja\n"
                "/code approve - zatwierdz krok\n"
                "/code reject - odrzuc krok\n"
                "/code cancel - anuluj sesje\n"
                "/code history - historia sesji\n\n"
                "Przyklad: /code zrob modul do glosu"
            )

        parts = args.strip().split(None, 1)
        subcmd = parts[0].lower()
        sub_args = parts[1] if len(parts) > 1 else ""

        if subcmd == "status":
            active = code_agent.get_active()
            if not active:
                return "Brak aktywnej sesji kodowania."
            return active.describe()

        elif subcmd == "approve":
            active = code_agent.get_active()
            if not active:
                return "Brak sesji czekajacych na zatwierdzenie."
            sid = sub_args.strip() if sub_args.strip() else active.session_id
            if code_agent.approve_checkpoint(sid):
                # Resume in background
                import threading
                def _resume():
                    try:
                        code_agent.resume(active.session_id)
                    except Exception as e:
                        bridge.bot.send_message(f"[Code] Blad przy wznowieniu: {e}")
                threading.Thread(target=_resume, daemon=True).start()
                return f"Zatwierdzono. Kontynuuje sesje {active.session_id[:8]}..."
            return "Nie ma czekajacego checkpointu."

        elif subcmd == "reject":
            active = code_agent.get_active()
            if not active:
                return "Brak sesji do odrzucenia."
            sid = sub_args.strip() if sub_args.strip() else active.session_id
            if code_agent.reject_checkpoint(sid):
                return f"Odrzucono - sesja anulowana."
            return "Nie ma czekajacego checkpointu."

        elif subcmd == "cancel":
            active = code_agent.get_active()
            if not active:
                return "Brak aktywnej sesji."
            if code_agent.cancel(active.session_id):
                return f"Sesja {active.session_id[:8]} anulowana."
            return "Nie mozna anulowac."

        elif subcmd == "history":
            sessions = code_agent.list_sessions(5)
            if not sessions:
                return "Brak sesji w historii."
            lines = ["*Historia Code Agent:*"]
            for s in sessions:
                files = len(s.files_written)
                lines.append(
                    f"  {s.session_id[:8]} {s.status.value} "
                    f"({files} plikow) {s.task_description[:40]}"
                )
            return "\n".join(lines)

        else:
            # Everything else is a task description
            task = args.strip()
            active = code_agent.get_active()
            if active and not active.status.is_terminal:
                return (
                    f"Aktywna sesja: {active.session_id[:8]} ({active.status.value})\n"
                    f"Uzyj /code cancel aby anulowac."
                )

            import threading
            def _run_code():
                try:
                    session = code_agent.start(task)
                    if session.status.value == "awaiting_approval":
                        pass  # Notification already sent by agent
                    elif session.status.value == "waiting_budget":
                        bridge.bot.send_message(
                            f"[Code] Brak budgetu LLM. Sesja {session.session_id[:8]} "
                            f"wznowi sie automatycznie."
                        )
                    elif session.status.value == "failed":
                        bridge.bot.send_message(
                            f"[Code] Nie udalo sie: {session.result_summary}"
                        )
                except Exception as e:
                    bridge.bot.send_message(f"[Code] Blad: {e}")

            threading.Thread(target=_run_code, daemon=True).start()
            return f"Rozpoczynam kodowanie: '{task[:60]}'. Plan za chwile..."

    def _cmd_analyze(args):
        """Analyze a module via Codex: /analyze <module_path>"""
        if not args or not args.strip():
            return (
                "Uzycie: /analyze <sciezka modulu>\n"
                "Przyklad: /analyze agent_core/critic\n"
                "Przyklad: /analyze agent_core/planner/planner_core.py"
            )
        module_path = args.strip()

        import threading

        def _run_analysis():
            from agent_core.llm.task_store import TaskStore
            store = TaskStore()
            task_id = store.create_task(
                task_text=f"analyze: {module_path}", backend="codex",
                source="telegram_analyze", timeout_s=300,
                metadata={"module": module_path},
            )
            try:
                from agent_core.llm.codex_client import CodexClient
                codex = CodexClient(timeout_s=300)
                if not codex.is_available():
                    store.mark_failed(task_id, "Codex CLI niedostepny")
                    bridge.bot.send_message("[Analyze] Codex CLI niedostepny.")
                    return

                prompt = (
                    f"Przeanalizuj modul '{module_path}' w projekcie M.A.R.I.A. "
                    f"(Python, katalog agent_core/). "
                    f"Opisz: 1) Co robi modul 2) Jakie ma problemy/TODO "
                    f"3) Propozycje ulepszen (max 3). "
                    f"Odpowiedz zwiezle po polsku."
                )

                store.mark_running(task_id)
                bridge.bot.send_message(
                    f"[Analyze] Analizuje: {module_path}...\n"
                    f"(task: {task_id}, timeout: 5min)"
                )

                result = codex.ask(prompt, source="telegram_analyze", context={"module": module_path})
                if result:
                    store.mark_completed(task_id, result[:500])
                    task_rec = store.get_task(task_id)
                    _send_result_pdf(
                        task_id, "codex", f"analyze: {module_path}", result,
                        duration_ms=task_rec.get("duration_ms") if task_rec else None,
                        timestamp=task_rec.get("created_at") if task_rec else None,
                    )
                    if len(result) > 3800:
                        result = result[:3800] + "\n...(obciete)"
                    bridge.bot.send_message(f"[Analyze] {module_path}:\n\n{result}")

                    # Post improvement proposals to bulletin
                    bs = getattr(ctx, 'bulletin_store', None)
                    if bs:
                        try:
                            from agent_core.bulletin.bulletin_model import EntryType
                            # add_entry bylo fantomem (audyt 2026-06-12).
                            bs.create_and_post(
                                entry_type=EntryType.IMPROVEMENT,
                                topic=f"Analiza: {module_path}",
                                reason_code="module_analysis",
                                summary=result[:500],
                                requested_by="telegram_analyze",
                                metadata={"module": module_path, "task_id": task_id},
                            )
                        except Exception:
                            pass
                else:
                    store.mark_timeout(task_id, 300)
                    bridge.bot.send_message(
                        f"[Analyze] Brak odpowiedzi (timeout 5min).\n"
                        f"Task {task_id} zapisany - mozesz ponowic."
                    )
            except Exception as e:
                store.mark_failed(task_id, str(e)[:300])
                bridge.bot.send_message(f"[Analyze] Blad: {e}")

        t = threading.Thread(target=_run_analysis, daemon=True)
        t.start()
        return f"Analizuje modul: '{module_path}'. Wynik za chwile..."

    def _cmd_claude(args):
        """Execute task via Claude Code CLI: /claude <task>"""
        if not args or not args.strip():
            return (
                "Uzycie: /claude <opis zadania>\n"
                "Przyklad: /claude przeanalizuj planner_core.py i znajdz potencjalne bugi\n"
                "Przyklad: /claude zaproponuj refactor modulu critic\n"
                "Limit: 3/h, 15/dzien (subskrypcja operatora)"
            )
        task = args.strip()

        import threading

        def _run_claude_task():
            from agent_core.llm.task_store import TaskStore
            store = TaskStore()
            task_id = store.create_task(
                task_text=task, backend="claude",
                source="telegram_claude", timeout_s=300,
            )
            try:
                from agent_core.llm.claude_client import ClaudeClient
                client = ClaudeClient(timeout_s=300)
                if not client.is_available():
                    store.mark_failed(task_id, "Claude CLI niedostepny")
                    bridge.bot.send_message("[Claude] CLI niedostepny.")
                    return

                stats = client.get_stats()
                if stats["remaining_hour"] <= 0:
                    store.mark_failed(task_id, "rate_limited")
                    bridge.bot.send_message(
                        f"[Claude] Limit godzinowy wyczerpany "
                        f"({stats['calls_this_hour']}/{stats['max_per_hour']}). "
                        f"Sprobuj pozniej."
                    )
                    return

                store.mark_running(task_id)
                bridge.bot.send_message(
                    f"[Claude] Pracuje nad: {task[:80]}...\n"
                    f"(task: {task_id}, timeout: 5min, "
                    f"zostalo {stats['remaining_hour']}/{stats['max_per_hour']})"
                )

                result = client.ask(
                    prompt=f"Projekt M.A.R.I.A. (Python, agent_core/). Zadanie: {task}",
                    source="telegram_claude",
                    context={"task": task},
                )
                if result:
                    store.mark_completed(task_id, result[:500])
                    task_rec = store.get_task(task_id)
                    _send_result_pdf(
                        task_id, "claude", task, result,
                        duration_ms=task_rec.get("duration_ms") if task_rec else None,
                        timestamp=task_rec.get("created_at") if task_rec else None,
                    )
                    if len(result) > 3800:
                        result = result[:3800] + "\n...(obciete)"
                    bridge.bot.send_message(f"[Claude] Wynik:\n\n{result}")

                    bs = getattr(ctx, 'bulletin_store', None)
                    if bs:
                        try:
                            from agent_core.bulletin.bulletin_model import EntryType
                            # add_entry bylo fantomem (audyt 2026-06-12).
                            bs.create_and_post(
                                entry_type=EntryType.CODE_TASK,
                                topic=task[:100],
                                reason_code="code_task_result",
                                summary=result[:500],
                                requested_by="telegram_claude",
                                metadata={"backend": "claude", "task_id": task_id},
                            )
                        except Exception:
                            pass
                else:
                    store.mark_timeout(task_id, 300)
                    bridge.bot.send_message(
                        f"[Claude] Brak odpowiedzi (timeout 5min).\n"
                        f"Task {task_id} zapisany - mozesz ponowic."
                    )
            except Exception as e:
                store.mark_failed(task_id, str(e)[:300])
                bridge.bot.send_message(f"[Claude] Blad: {e}")

        t = threading.Thread(target=_run_claude_task, daemon=True)
        t.start()
        return f"Przyjeto (Claude): '{task[:60]}'. Wynik za chwile..."

    def _cmd_tasks(args):
        """Show recent tasks: /tasks [N]"""
        from agent_core.llm.task_store import TaskStore
        store = TaskStore()
        limit = 5
        if args and args.strip().isdigit():
            limit = min(int(args.strip()), 20)
        tasks = store.get_recent(limit)
        if not tasks:
            return "Brak zapisanych taskow."
        lines = [f"*Ostatnie {len(tasks)} taskow:*"]
        for t in reversed(tasks):
            tid = t.get("task_id", "?")
            status = t.get("status", "?")
            backend = t.get("backend", "?")
            text = t.get("task_text", "?")[:50]
            dur = t.get("duration_ms")
            dur_str = f" {dur/1000:.0f}s" if dur else ""
            err = t.get("error", "")
            err_str = f" | {err[:40]}" if err else ""
            lines.append(f"  `{tid}` [{backend}] {status}{dur_str}{err_str}\n  {text}")
        return "\n".join(lines)

    def _cmd_pdf(args):
        """Re-export a past task as PDF: /pdf <task_id>"""
        if not args or not args.strip():
            return (
                "Uzycie: /pdf <task_id>\n"
                "Uzyj /tasks aby zobaczyc dostepne taski."
            )
        task_id = args.strip()
        from agent_core.llm.task_store import TaskStore
        store = TaskStore()
        # Support prefix matching
        task = store.get_task(task_id)
        if not task:
            # Try prefix match
            for t in reversed(store.get_recent(50)):
                if t.get("task_id", "").startswith(task_id):
                    task = t
                    break
        if not task:
            return f"Task '{task_id}' nie znaleziony. Uzyj /tasks."
        if task.get("status") != "COMPLETED":
            return f"Task {task['task_id']} status: {task.get('status')} (PDF tylko dla COMPLETED)."
        summary = task.get("result_summary", "")
        if not summary:
            return f"Task {task['task_id']} nie ma zapisanego wyniku."
        _send_result_pdf(
            task["task_id"], task.get("backend", "?"),
            task.get("task_text", "?"), summary,
            duration_ms=task.get("duration_ms"),
            timestamp=task.get("created_at"),
        )
        return f"PDF wygenerowany dla task {task['task_id']}."

    def _cmd_profile(args):
        """Operator profile: /profile [set|rhythm|add_interest|remove_interest] <text>"""
        om = getattr(ctx, 'operator_model', None) or getattr(ctx, 'user_profile', None)
        if not om:
            return "OperatorModel niedostepny."

        if not args or not args.strip():
            return om.get_summary()

        parts = args.strip().split(None, 1)
        subcmd = parts[0].lower()
        text = parts[1] if len(parts) > 1 else ""

        if subcmd == "set" and text:
            # /profile set job plytkarz
            kv = text.split(None, 1)
            if len(kv) < 2:
                return "Uzycie: /profile set <klucz> <wartosc>"
            key, value = kv[0], kv[1]
            om.set_fact(key, value, 1.0, "explicit:telegram")
            return f"Ustawiono {key} = {value}"
        elif subcmd == "rhythm":
            r = om.rhythm
            if r.confidence == 0:
                return "Brak danych o rytmie dnia (za malo interakcji)."
            return (
                f"*Rytm dnia:*\n"
                f"Wstaje: ~{r.typical_wake_hour}:00\n"
                f"Praca: {r.work_hours[0]}:00-{r.work_hours[1]}:00\n"
                f"Spi od: ~{r.typical_sleep_hour}:00\n"
                f"Pewnosc: {r.confidence:.0%} (probek: {r.sample_count})"
            )
        elif subcmd == "add_interest" and text:
            ok = om.add_interest(text)
            return f"Dodano zainteresowanie: {text}" if ok else f"Juz znane: {text}"
        elif subcmd == "add_fact" and text:
            ok = om.add_fact(text)
            return f"Dodano fakt: {text}" if ok else f"Juz znane: {text}"
        elif subcmd == "remove_interest" and text:
            ok = om.remove_interest(text)
            return f"Usunieto: {text}" if ok else f"Nie znaleziono: {text}"
        elif subcmd == "remove_fact" and text:
            ok = om.remove_fact(text)
            return f"Usunieto: {text}" if ok else f"Nie znaleziono: {text}"
        else:
            return (
                "*Profil operatora:*\n"
                "/profile - pokaz profil\n"
                "/profile set <klucz> <wartosc>\n"
                "/profile rhythm - rytm dnia\n"
                "/profile add\\_interest <temat>\n"
                "/profile add\\_fact <fakt>\n"
                "/profile remove\\_interest <temat>\n"
                "/profile remove\\_fact <klucz>"
            )

    def _cmd_remind(args):
        """Telegram: /remind <text> <time> | /remind list | /remind dismiss <id>"""
        rs = getattr(ctx, 'reminder_store', None)
        if not rs:
            return "Przypomnienia nie zainicjalizowane"
        if not args:
            return "Uzycie: /remind <tekst> <czas>\nNp: /remind spotkanie za 30min\n/remind list\n/remind dismiss <id>"

        parts = args.split(None, 1) if isinstance(args, str) else [args]
        sub = parts[0].lower() if parts else ""

        if sub == "list":
            pending = rs.get_pending()
            if not pending:
                return "Brak aktywnych przypomnien"
            from agent_core.reminders import format_scheduled_time
            lines = [f"*Przypomnienia ({len(pending)}):*"]
            for r in sorted(pending, key=lambda x: x.scheduled_at):
                when = format_scheduled_time(r.scheduled_at)
                recur = f" [{r.recurrence.value}]" if r.recurrence.value != "ONCE" else ""
                lines.append(f"  {r.id}: {r.text} - {when}{recur}")
            return "\n".join(lines)

        if sub == "dismiss" and len(parts) > 1:
            rest = parts[1].strip()
            rem = _find_by_prefix(rs.get_pending(), rest)
            if not rem:
                return f"Nie znaleziono: {rest}"
            rs.dismiss(rem.id)
            return f"Usunieto: {rem.id}"

        if sub == "snooze" and len(parts) > 1:
            rest = parts[1].strip().split()
            id_pref = rest[0]
            minutes = int(rest[1]) if len(rest) > 1 else 15
            rem = _find_by_prefix(rs.get_pending(), id_pref)
            if not rem:
                return f"Nie znaleziono: {id_pref}"
            rs.snooze(rem.id, minutes)
            return f"Odlozono o {minutes}min: {rem.id}"

        # Create reminder: /remind <text> <time>
        from agent_core.reminders import Reminder, parse_time, format_scheduled_time
        text = args if isinstance(args, str) else " ".join(args)
        tokens = text.split()
        scheduled = None
        reminder_text = text

        # Try last 2 tokens as time, then last 1
        for n in (2, 1):
            if len(tokens) >= n + 1:
                candidate = " ".join(tokens[-n:])
                ts = parse_time(candidate)
                if ts is not None:
                    scheduled = ts
                    reminder_text = " ".join(tokens[:-n])
                    break

        if scheduled is None:
            scheduled = time.time() + 1800  # default 30min

        rem = Reminder(text=reminder_text, scheduled_at=scheduled)
        rs.add(rem)
        when = format_scheduled_time(scheduled)
        return f"Przypomnienie: {rem.id}\n\"{reminder_text}\" - {when}"

    def _cmd_todo(args):
        """Telegram: /todo <text> | /todo list | /todo done <id>"""
        ts = getattr(ctx, 'todo_store', None)
        if not ts:
            return "Zadania nie zainicjalizowane"
        if not args:
            # Show pending by default
            pending = ts.get_pending()
            if not pending:
                return "Brak aktywnych zadan"
            lines = [f"*Zadania ({len(pending)}):*"]
            for t in pending:
                prio = f" [{t.priority.value}]" if t.priority.value != "NORMAL" else ""
                lines.append(f"  {t.id}: {t.text}{prio}")
            return "\n".join(lines)

        parts = args.split(None, 1) if isinstance(args, str) else [args]
        sub = parts[0].lower() if parts else ""

        if sub == "list":
            pending = ts.get_pending()
            if not pending:
                return "Brak aktywnych zadan"
            lines = [f"*Zadania ({len(pending)}):*"]
            for t in pending:
                prio = f" [{t.priority.value}]" if t.priority.value != "NORMAL" else ""
                lines.append(f"  {t.id}: {t.text}{prio}")
            return "\n".join(lines)

        if sub == "done" and len(parts) > 1:
            id_pref = parts[1].strip()
            todo = _find_by_prefix(ts.get_pending(), id_pref)
            if not todo:
                return f"Nie znaleziono: {id_pref}"
            ts.complete(todo.id)
            return f"Zrobione: {todo.id} \"{todo.text}\""

        if sub == "cancel" and len(parts) > 1:
            id_pref = parts[1].strip()
            todo = _find_by_prefix(ts.get_pending(), id_pref)
            if not todo:
                return f"Nie znaleziono: {id_pref}"
            ts.cancel(todo.id)
            return f"Anulowano: {todo.id}"

        # Create: /todo <text>
        from agent_core.reminders import Todo
        text = args if isinstance(args, str) else " ".join(args)
        todo = Todo(text=text)
        ts.add(todo)
        return f"Zadanie: {todo.id}\n\"{text}\""

    def _find_by_prefix(items, prefix):
        """Find item by ID or ID prefix."""
        prefix = prefix.strip()
        for item in items:
            if item.id == prefix or item.id.startswith(prefix):
                return item
        return None

    def _cmd_proactive(args):
        """Handle /proactive [status|on|off|history]."""
        sched = ctx.proactive_scheduler if hasattr(ctx, 'proactive_scheduler') else None
        if not sched:
            return "Proactive contact not initialized"

        parts = args.split() if isinstance(args, str) else list(args)
        sub = parts[0].lower() if parts else "status"

        if sub == "on":
            sched.set_enabled(True)
            return "Proaktywny kontakt: WLACZONY"

        if sub == "off":
            sched.set_enabled(False)
            return "Proaktywny kontakt: WYLACZONY"

        if sub == "history":
            limit = 5
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                except ValueError:
                    pass
            history = sched.get_history(limit)
            if not history:
                return "Brak historii kontaktow"
            lines = [f"*Ostatnie kontakty ({len(history)}):*"]
            for h in history:
                from datetime import datetime
                ts = h.get("timestamp", 0)
                dt = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "?"
                reason = h.get("reason", "?")
                lines.append(f"  [{dt}] {reason}")
            return "\n".join(lines)

        # Default: status
        status = sched.get_status()
        state = "WLACZONY" if status["enabled"] else "WYLACZONY"
        lines = [
            f"*Proaktywny kontakt: {state}*",
            f"Dzisiaj: {status['contacts_today']}/{status['max_per_day']}",
            f"Cisza nocna: {'tak' if status['quiet_hours'] else 'nie'}",
            f"Idle operatora: {status['operator_idle_human']}",
        ]
        # Next possible contacts
        for reason, info in status.get("cooldowns", {}).items():
            remaining = info.get("remaining_sec", 0)
            if remaining > 0:
                from agent_core.homeostasis.time_awareness import TimeAwareness
                lines.append(f"  {reason}: za {TimeAwareness.format_duration(remaining)}")
        return "\n".join(lines)

    def _cmd_privacy(args):
        """Privacy boundaries: /privacy [add|remove|list] <topic>"""
        om = getattr(ctx, 'operator_model', None)
        if not om:
            return "OperatorModel niedostepny."
        if not args or not args.strip():
            boundaries = om.get_boundaries()
            if not boundaries:
                return "Brak granic prywatnosci. Uzyj /privacy add <temat>"
            lines = ["*Granice prywatnosci:*"]
            for b in boundaries:
                lines.append(f"  - {b}")
            lines.append("\n/privacy add <temat> | /privacy remove <temat>")
            return "\n".join(lines)

        parts = args.strip().split(None, 1)
        subcmd = parts[0].lower()
        text = parts[1] if len(parts) > 1 else ""

        if subcmd == "add" and text:
            ok = om.add_boundary(text)
            return f"Dodano granice: {text}" if ok else f"Juz istnieje: {text}"
        elif subcmd == "remove" and text:
            ok = om.remove_boundary(text)
            return f"Usunieto granice: {text}" if ok else f"Nie znaleziono: {text}"
        elif subcmd == "list":
            return _cmd_privacy("")
        else:
            return "Uzycie: /privacy add <temat> | /privacy remove <temat> | /privacy list"

    def _cmd_context(args):
        """Current context: /context <text> [hours] | /context clear"""
        om = getattr(ctx, 'operator_model', None)
        if not om:
            return "OperatorModel niedostepny."
        if not args or not args.strip():
            current = om.get_context()
            if current:
                return f"Aktualny kontekst: {current}"
            return "Brak kontekstu. Uzyj /context <tekst> [godziny]"

        text = args.strip()
        if text.lower() == "clear":
            om.clear_context()
            return "Kontekst wyczyszczony."

        # Parse optional hours at the end: "/context deadline today 8"
        parts = text.rsplit(None, 1)
        hours = 24
        if len(parts) == 2:
            try:
                hours = int(parts[1])
                text = parts[0]
            except ValueError:
                pass  # Last word wasn't a number, use full text

        om.set_context(text, expires_hours=hours)
        return f"Kontekst ustawiony: {text} (wygasa za {hours}h)"

    def _cmd_capabilities(args):
        """What can Maria do: /capabilities"""
        manifest = getattr(ctx, 'capability_manifest', None)
        if not manifest:
            return "CapabilityManifest niedostepny."
        return manifest.get_summary()

    # --- Workflow commands (Faza 5) ---

    def _cmd_wf(args):
        """Telegram /wf - workflow management."""
        engine = ctx.workflow_engine
        if not engine:
            return "Workflow Engine niedostepny."
        sub = args[0].lower() if args else "list"

        if sub == "list":
            wfs = engine.list_workflows()
            active = [w for w in wfs if w["status"] in ("running", "pending", "paused")]
            if not active:
                return "Brak aktywnych workflow."
            lines = []
            for w in active[:10]:
                lines.append(f"{w['workflow_id'][:8]} {w['name']} [{w['status']}] {w['progress_pct']:.0f}%")
            return "\n".join(lines)

        if sub == "start" and len(args) >= 2:
            try:
                from agent_core.workflow.templates import WORKFLOW_TEMPLATES
                tmpl_name = args[1]
                if tmpl_name not in WORKFLOW_TEMPLATES:
                    return f"Nieznany szablon. Dostepne: {', '.join(WORKFLOW_TEMPLATES.keys())}"
                tmpl = WORKFLOW_TEMPLATES[tmpl_name]
                topic = " ".join(args[2:]) if len(args) > 2 else None
                if tmpl["needs_topic"] and not topic:
                    return f"Podaj temat: /wf start {tmpl_name} <topic>"
                steps = tmpl["factory"](topic) if tmpl["needs_topic"] else tmpl["factory"]()
                desc = tmpl["description"] + (f": {topic}" if topic else "")
                wf = engine.create(tmpl_name, desc, steps)
                engine.start(wf.workflow_id)
                return f"Workflow started: {wf.workflow_id[:8]} ({len(steps)} steps)"
            except Exception as e:
                return f"Error: {e}"

        if sub == "pause" and len(args) >= 2:
            wf_obj = _find_wf(engine, args[1])
            if not wf_obj:
                return f"Nie znaleziono: {args[1]}"
            ok = engine.pause(wf_obj["workflow_id"])
            return f"Paused: {wf_obj['workflow_id'][:8]}" if ok else "Nie mozna wstrzymac."

        if sub == "resume" and len(args) >= 2:
            wf_obj = _find_wf(engine, args[1])
            if not wf_obj:
                return f"Nie znaleziono: {args[1]}"
            ok = engine.resume(wf_obj["workflow_id"])
            return f"Resumed: {wf_obj['workflow_id'][:8]}" if ok else "Nie mozna wznowic."

        if sub == "cancel" and len(args) >= 2:
            wf_obj = _find_wf(engine, args[1])
            if not wf_obj:
                return f"Nie znaleziono: {args[1]}"
            ok = engine.cancel(wf_obj["workflow_id"], "operator via Telegram")
            return f"Cancelled: {wf_obj['workflow_id'][:8]}" if ok else "Nie mozna anulowac."

        if sub == "templates":
            try:
                from agent_core.workflow.templates import WORKFLOW_TEMPLATES
                lines = []
                for name, t in WORKFLOW_TEMPLATES.items():
                    lines.append(f"{name} (~{t['estimated_minutes']}min): {t['description']}")
                return "\n".join(lines)
            except Exception:
                return "Error loading templates."

        return "Usage: /wf [list|start|pause|resume|cancel|templates]"

    def _find_wf(engine, prefix):
        for w in engine.list_workflows():
            if w["workflow_id"].startswith(prefix) or w["workflow_id"][:8] == prefix:
                return w
        return None

    def _cmd_env(args):
        """Telegram /env - environment mode management."""
        mgr = ctx.environment_manager
        if not mgr:
            return "Environment Manager niedostepny."
        sub = args[0].lower() if args else "status"

        if sub == "status":
            status = mgr.get_status()
            lines = [
                f"Mode: {status['mode']}",
                f"Auto: {'ON' if status['auto_detect_enabled'] else 'OFF'}",
                f"LLM budget: {status['llm_budget_multiplier']:.1f}x",
                f"Notifications: {status['notification_level']}",
            ]
            if status['blocked_actions']:
                lines.append(f"Blocked: {', '.join(status['blocked_actions'])}")
            return "\n".join(lines)

        if sub in ("switch", "set") and len(args) >= 2:
            try:
                from agent_core.environment.environment_model import EnvironmentMode
                mode = EnvironmentMode(args[1].lower())
                ok = mgr.switch(mode, by="operator")
                return f"Switched to: {mode.value}" if ok else f"Already in: {mode.value}"
            except ValueError:
                from agent_core.environment.environment_model import EnvironmentMode
                valid = [m.value for m in EnvironmentMode]
                return f"Nieznany tryb. Dostepne: {', '.join(valid)}"

        if sub == "list":
            modes = mgr.list_modes()
            lines = []
            for m in modes:
                marker = " <--" if m['active'] else ""
                lines.append(f"{m['mode']}: {m['description']}{marker}")
            return "\n".join(lines)

        if sub == "auto":
            mgr._state.auto_detect_enabled = True
            from agent_core.environment.environment_model import EnvironmentMode
            mgr.switch(EnvironmentMode.DEFAULT, by="operator")
            return "Auto-detection ON, mode: default"

        return "Usage: /env [status|list|switch <mode>|auto]"

    def _cmd_teacher(args):
        """Run ONE exam on demand: /teacher [file_id]

        Picks the next exam-ready file (or the given file_id) and runs the full
        generate -> answer -> grade pipeline: question AUTHOR = NIM (off-CPU),
        GRADER = local qwen3. Bypasses the learning-window gate -- this is an
        explicit operator-triggered verification. Result comes asynchronously
        (an exam takes ~1-2 min) so the poll thread is not blocked.
        """
        core = getattr(ctx, "homeostasis_core", None)
        ta = getattr(core, "_teacher_agent", None) if core else None
        run_exam = getattr(ta, "_run_exam_fn", None) if ta else None
        if run_exam is None:
            return "Teacher agent niedostepny (brak _run_exam_fn)."

        target = args.strip() if args and args.strip() else None

        import threading

        def _run_one_exam():
            try:
                res = run_exam(target)
                if res and res.get("success"):
                    bridge.bot.send_message(
                        f"[/teacher] Egzamin OK: {res.get('file_id')}\n"
                        f"wynik: {res.get('score', 0):.0%} | "
                        f"zaliczony: {'tak' if res.get('passed') else 'nie'}"
                    )
                else:
                    err = (res or {}).get("error") or "brak gotowego pliku lub timeout"
                    bridge.bot.send_message(f"[/teacher] Egzamin nie wykonany: {err}")
            except Exception as exc:
                bridge.bot.send_message(f"[/teacher] Blad egzaminu: {exc}")

        threading.Thread(
            target=_run_one_exam, daemon=True, name="TgExamOnDemand"
        ).start()
        which = f" ({target})" if target else ""
        return (f"Egzamin ruszyl{which} -- autor pytan = NIM, ocena = qwen3. "
                f"Wynik za ~1-2 min...")

    bridge.register_command("wf", _cmd_wf)
    bridge.register_command("teacher", _cmd_teacher)
    bridge.register_command("env", _cmd_env)
    bridge.register_command("capabilities", _cmd_capabilities)
    bridge.register_command("privacy", _cmd_privacy)
    bridge.register_command("context", _cmd_context)
    bridge.register_command("proactive", _cmd_proactive)
    bridge.register_command("remind", _cmd_remind)
    bridge.register_command("todo", _cmd_todo)
    bridge.register_command("profile", _cmd_profile)
    bridge.register_command("pdf", _cmd_pdf)
    bridge.register_command("tasks", _cmd_tasks)
    bridge.register_command("claude", _cmd_claude)
    bridge.register_command("code", _cmd_code)
    bridge.register_command("codex", _cmd_codex)
    bridge.register_command("analyze", _cmd_analyze)
    bridge.register_command("board", _cmd_board)
    bridge.register_command("status", _cmd_status)
    bridge.register_command("selfstatus", _cmd_selfstatus)
    bridge.register_command("strategic", _cmd_strategic)
    bridge.register_command("fs_write", _cmd_fs_write)
    bridge.register_command("heldout", _cmd_heldout)
    bridge.register_command("list_repairs", _cmd_list_repairs)
    bridge.register_command("approve_repair", _cmd_approve_repair)
    bridge.register_command("drill_repair", _cmd_drill_repair)
    bridge.register_command("drill_heartbeat", _cmd_drill_heartbeat)
    bridge.register_command("drill_outbox", _cmd_drill_outbox)
    bridge.register_command("approve_note", _cmd_approve_note)
    bridge.register_command("reject_note", _cmd_reject_note)
    bridge.register_command("list_notes", _cmd_list_notes)
    bridge.register_command("goals", _cmd_goals)
    bridge.register_command("approve", _cmd_approve)
    bridge.register_command("reject", _cmd_reject)
    bridge.register_command("test_propose", _cmd_test_propose)
    bridge.register_command("restart", _cmd_restart)
    bridge.register_command("priority", _cmd_priority)
    bridge.register_command("learn", _cmd_learn)
    bridge.register_command("codexwrite", _cmd_codexwrite)
    bridge.register_command("trace", _cmd_trace)
    bridge.register_command("memory", _cmd_memory)
    bridge.register_command("validate", _cmd_validate)
    bridge.register_command("beliefs", _cmd_beliefs)
    bridge.register_command("synthesize", _cmd_synthesize)
    bridge.register_command("synthreview", _cmd_synthreview)
    bridge.register_command("nauka", _cmd_nauka)
    bridge.register_command("do", _cmd_do)
    bridge.register_command("efapprove", _cmd_efapprove)
    bridge.register_command("efreject", _cmd_efreject)
    bridge.register_command("efstatus", _cmd_efstatus)
    bridge.register_command("authority", _cmd_authority)
    bridge.register_command("trust", _cmd_trust)
    bridge.register_command("help", _cmd_help)
    bridge.register_command("start", lambda a: _cmd_help(a))  # Handle /start from Telegram
