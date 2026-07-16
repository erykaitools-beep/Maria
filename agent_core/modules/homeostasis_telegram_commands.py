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

# Sub-goals an operator can attach to one /project (bounds the active-goal load).
MAX_PROJECT_SUBGOALS = 12


def _parse_project_deadline(text):
    """Parse an operator deadline string to epoch seconds (Etap B /project).

    Returns None when ``text`` is blank (a project may have no deadline). Raises
    ValueError when ``text`` is non-blank but unparseable, so the command can
    reject bad input upfront rather than silently dropping the deadline.

    Accepts the reminder natural forms ("za 30 dni", "jutro 9:00", "za 2h") plus
    ISO dates: "YYYY-MM-DD" (-> 23:59 local that day) and "YYYY-MM-DD HH:MM".
    """
    text = (text or "").strip()
    if not text:
        return None
    from agent_core.reminders import parse_time

    ts = parse_time(text)
    if ts is not None:
        return ts
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            dt = dt.replace(hour=23, minute=59, second=0, microsecond=0)
        return dt.timestamp()
    raise ValueError(f"nie rozumiem terminu: {text!r}")


def _parse_project_args(args):
    """Split a raw /project arg string into (name, deadline_text, [subgoals]).

    Format: ``<nazwa> | <termin> | <podcel1> ; <podcel2> ; ...`` where the two
    ``|`` segments are optional. Sub-goals split on ``;`` or newlines; blanks are
    dropped. Returns (name, deadline_text, subgoals) with name possibly empty
    (caller validates).
    """
    raw = (args or "").strip()
    parts = [p.strip() for p in raw.split("|")]
    name = parts[0] if parts else ""
    deadline_text = parts[1] if len(parts) > 1 else ""
    subgoals = []
    if len(parts) > 2:
        blob = parts[2].replace("\n", ";")
        subgoals = [s.strip() for s in blob.split(";") if s.strip()]
    return name, deadline_text, subgoals


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

    def _cmd_myslenie(args):
        """Show recent reasoning-journal entries (Maria "thinks out loud").

        Usage: /myslenie [n] [zrodlo]  e.g. /myslenie 5 creative
        """
        from agent_core.tracing.reasoning_journal import get_reasoning_journal
        parts = (args or "").split()
        n = 3
        source = None
        for p in parts:
            if p.isdigit():
                n = max(1, min(int(p), 10))
            else:
                source = p
        entries = get_reasoning_journal().recent(n=n, source=source)
        if not entries:
            scope = f" (zrodlo: {source})" if source else ""
            return (
                f"Notatnik rozumowania pusty{scope}.\n"
                "Wpisy powstaja gdy LLM rozumuje w creative/K12/teacher."
            )
        lines = [f"*Notatnik rozumowania* (ostatnie {len(entries)}):"]
        for e in entries:
            ts = time.strftime("%d.%m %H:%M", time.localtime(e.get("ts", 0)))
            head = f"\n[{ts}] {e.get('source', '?')}"
            if e.get("model"):
                head += f" ({e['model'].split('/')[-1]})"
            lines.append(head)
            if e.get("conclusion"):
                lines.append(f"Wniosek: {e['conclusion'][:200]}")
            reasoning = (e.get("reasoning") or "").replace("\n", " ")
            lines.append(f"Myslenie: {reasoning[:300]}")
            if e.get("episode_id"):
                lines.append(f"epizod: {e['episode_id']}")
        return "\n".join(lines)

    def _cmd_selfcontext(args):
        """Show the merged situational picture (Super-META E0 SelfContext)."""
        sc = getattr(ctx, "self_context", None)
        if sc is None:
            return "Brak SelfContext (modul nie wired)."
        return sc.format_for_telegram()

    def _cmd_lastseen(args):
        """Show what Maria recently saw (Super-META E1 VisionMemory)."""
        vm = getattr(ctx, "vision_memory", None)
        if vm is None:
            return "Brak VisionMemory (modul nie wired)."
        return vm.format_for_telegram()

    def _cmd_growth(args):
        """Show Maria's growth targets (K15.3 GrowthAwareness), top 5 by benefit/cost."""
        g = getattr(ctx, "growth_awareness", None)
        if g is None:
            return "Brak GrowthAwareness (modul nie wired)."
        return g.get_summary_text()

    def _cmd_samorozwoj(args):
        """Curated self-development board: which ideas Maria keeps asking for,
        how many times, since when, and whether anything ever came of it."""
        sdj = getattr(ctx, "self_dev_journal", None)
        if sdj is None:
            return "Brak dziennika samorozwoju (modul nie wired)."
        return sdj.render_board()

    def _cmd_approve_dev(args):
        """Take over a self-dev idea Maria nudged about (/approve_dev <token>).

        Closure, not execution (mirrors /approve_repair): resolves the linked
        creative advisories as operator_acknowledged so the idea stops recurring
        and the board flips it from UTKNAL to zrealizowane."""
        bridge = getattr(ctx, "self_dev_bridge", None)
        if bridge is None:
            return "Brak mostu samorozwoju (modul nie wired)."
        token = (args or "").strip().split()[0] if (args or "").strip() else ""
        if not token:
            return "Uzycie: /approve_dev <token> (token z powiadomienia Marii)."
        return bridge.acknowledge(token)

    def _cmd_play(args):
        """Self-time ("spacer po wlasnej glowie"): toggle + peek at her musings.

        This is the OBSERVE window -- without it the play journal would rot
        unseen like the creative one did.

        /play        -> status (flag + last musings + how many continued a thread)
        /play on     -> arm self-time (runtime; resets to PLAY_ENABLED on restart)
        /play off    -> stop
        """
        planner = ctx.planner_core
        pm = getattr(ctx, "play_module", None)
        arg = (args or "").strip().lower()
        if arg in {"on", "true", "1", "start"}:
            if planner is None:
                return "Brak planner_core (modul nie wired)."
            planner.set_play_enabled(True)
            return (
                "Self-time (PLAY) = ON (runtime; reset po restarcie).\n"
                "Gdy obudzona i bez zadan -> swobodna mysl do wlasnego dziennika, "
                "bez oceny. /play -> podglad, /play off -> cofnij."
            )
        if arg in {"off", "false", "0", "stop"}:
            if planner is None:
                return "Brak planner_core (modul nie wired)."
            planner.set_play_enabled(False)
            return "Self-time (PLAY) = OFF."
        flag = "ON" if (planner and getattr(planner, "_play_enabled", False)) else "OFF"
        if pm is None:
            return f"Self-time (PLAY) = {flag}. Brak play_module (nie wired)."
        st = pm.get_status()
        recent = pm.journal.recent(2)
        cont = sum(1 for e in recent if e.get("continues"))
        lines = [
            f"Self-time (PLAY) = {flag}",
            f"musingow lacznie: {st['total_plays']} | dzis: {st['today']} "
            f"| LLM: {'tak' if st['has_llm'] else 'nie'}",
        ]
        if recent:
            lines.append(f"ostatnie ({cont} kontynuuje watek):")
            for e in recent:
                m = str(e.get("musing", "")).replace("\n", " ")[:200]
                link = " (watek)" if e.get("continues") else ""
                lines.append(f"- {m}{link}")
        else:
            lines.append("(jeszcze zadnych musingow)")
        return "\n".join(lines)

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
        lines.append("/fs_write on|off|seed | /drill_fs_write | /learning_notes (notatki z nauki)")
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
            # C8: the flag arms ONLY the planner's B4 emission. Mechanical
            # grading is opted into PER EXAM by the plan's grader='heldout'
            # param (carried from the goal's criterion) -- regular exams and
            # spaced reviews keep the LLM examiner regardless of this toggle.
            _os.environ["HELDOUT_GRADER_ENABLED"] = "1"
            planner.set_heldout_enabled(True)
            return (
                "HELDOUT = ON (runtime; reset po restarcie).\n"
                "Planner emituje egzaminy dla celow z kryterium exam_independent;\n"
                "ocena mechaniczna (heldout:static@v1) TYLKO dla planow z\n"
                "grader=heldout (kryterium celu). Zwykle egzaminy/powtorki: LLM.\n"
                "/heldout seed -> cel-demo, /heldout off -> cofnij."
            )
        if arg in {"off", "false", "0", "stop"}:
            _os.environ["HELDOUT_GRADER_ENABLED"] = "0"
            planner.set_heldout_enabled(False)
            return "HELDOUT = OFF (planner nie emituje egzaminow B4)."
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
        try:
            from agent_core.teacher.heldout_author import author_enabled
            lines.append(
                f"Bank author (fetch): {'ON' if author_enabled() else 'OFF'}"
            )
        except Exception:
            pass
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
        # Bank coverage (C9 arming aid): v3 rows per covered file + a red flag
        # if any file of a NON-heldout market goal leaked into the v3 bank
        # (must be ZERO pre-flip -- Kronika stays with the LLM examiner).
        try:
            from maria_core.learning.exam_agent import (
                load_heldout_bank, HELDOUT_MIN_BANK_ROWS,
            )
            rows = load_heldout_bank()
            v3 = [r for r in rows if r.get("bank_version") == "v3"]
            by_file = {}
            for r in v3:
                fid = r.get("file") or r.get("file_id")
                by_file[fid] = by_file.get(fid, 0) + 1
            covered = sum(
                1 for n in by_file.values() if n >= HELDOUT_MIN_BANK_ROWS)
            lines.append(
                f"Bank: {len(rows)} wierszy ({len(v3)} v3, "
                f"{covered} plikow z pokryciem >= {HELDOUT_MIN_BANK_ROWS})"
            )
            if store is not None and by_file:
                banked = set(by_file)
                leaked = set()
                for g in store.get_all():
                    meta = getattr(g, "metadata", None) or {}
                    if meta.get("source_kind") == "market" and str(
                        meta.get("verification_mode") or ""
                    ).lower() != "heldout":
                        leaked |= banked & set(meta.get("market_file_ids") or [])
                if leaked:
                    lines.append(
                        f"UWAGA: {len(leaked)} plikow spoza trybu heldout w "
                        f"banku v3 (np. {sorted(leaked)[0]})"
                    )
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

    def _cmd_drill_fs_write(args):
        """On-demand proof of the AUTONOMOUS FS_WRITE loop (B2, the first
        autonomous hand -- mirror /drill_outbox + /drill_repair).

        Seeds a file_exists goal with a FRESH filename (only if none is open),
        then runs the REAL planner -> execute -> close chain ONCE and reports
        whether Maria wrote the file into the jailed sandbox and the goal closed
        on EXTERNAL evidence (the file on disk). The write is jailed
        (meta_data/fs_sandbox/), <=1 KiB, sanitized -- never a production
        artifact. FS_WRITE_ENABLED is flipped on only for this run, then restored
        (the drill leaves no standing autonomy). Unlike Rung 2 (/drill_outbox)
        there is NO operator approval in the write loop -- this proves the
        autonomous hand, not the operator-gated one.
        """
        planner = ctx.planner_core
        store = ctx.goal_store
        if planner is None or store is None:
            return "Brak planner_core/goal_store (modul nie wired)."

        import time
        import uuid
        from agent_core.goals.goal_model import GoalStatus
        from agent_core.hands.sandbox_writer import default_sandbox_root
        from agent_core.routing.handlers import (
            seed_first_action_goal, close_goal_on_criteria,
        )

        # Resolve the sandbox root exactly as _maybe_fs_write does, so the seeded
        # criterion path, the planner's write target, and the closer all agree.
        root = getattr(planner, "_fs_sandbox_root", None)
        if not root:
            try:
                from maria_core.sys.config import BASE_DIR
                root = default_sandbox_root(BASE_DIR)
            except Exception:
                root = default_sandbox_root(".")

        def _has_open_file_crit(g):
            return any(
                isinstance(c, dict) and c.get("type") == "file_exists"
                for c in (getattr(g, "success_criteria", None) or [])
            )
        try:
            existing = [g for g in store.get_active() if _has_open_file_crit(g)]
        except Exception:
            existing = []

        seeded_gid = None
        if not existing:
            fname = f"maria_drill_{int(time.time())}_{uuid.uuid4().hex[:6]}.txt"
            seeded_gid = seed_first_action_goal(store, sandbox_root=root, filename=fname)
            if not seeded_gid:
                return "drill_fs_write: nie udalo sie stworzyc celu-demo."

        prev = getattr(planner, "_fs_write_enabled", False)
        try:
            # Inside the try so finally always restores, even if this raises.
            planner.set_fs_write_enabled(True)
            plan = planner._maybe_fs_write({})
            if plan is None:
                if seeded_gid:
                    try:
                        store.update_status(
                            seeded_gid, GoalStatus.ABANDONED,
                            "drill: planner nie wygenerowal planu", "drill",
                        )
                    except Exception:
                        pass
                return (
                    "drill_fs_write: planner nie wygenerowal planu "
                    "(rate-limit lub brak celu file_exists). Sprobuj za chwile."
                )
            result = planner.executor.execute(plan) or {}
            # Production executor (CapabilityRouter) already closes the goal; the
            # routerless fallback does not -- close defensively (idempotent: the
            # closer re-stats the file on disk, never trusts a flag).
            try:
                close_goal_on_criteria(
                    plan, result, store,
                    sandbox_root=plan.action_params.get("sandbox_root") or root,
                )
            except Exception:
                pass
        finally:
            planner.set_fs_write_enabled(prev)

        gid = plan.goal_id
        g = store.get(gid) if gid else None
        achieved = bool(g and getattr(g.status, "value", None) == "achieved")
        wrote = bool(result.get("success"))
        path = result.get("path", "?")
        if wrote and achieved:
            return (
                f"drill_fs_write OK -> Maria SAMA zapisala plik:\n{path}\n"
                f"Cel {gid} domkniety NA DOWODZIE (plik istnieje na dysku).\n"
                f"Pierwsza autonomiczna reka dziala. Plik jest kasowalny."
            )
        return (
            f"drill_fs_write czesciowy: zapis={wrote} cel_domkniety={achieved} "
            f"path={path} goal={gid}. Sprawdz logi."
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

    def _cmd_learning_notes(args):
        """Etap 2 (RED zone) -- READ-ONLY view of Maria's autonomous learning notes.

        Lists meta_data/fs_sandbox/maria_note_*.txt (the notes the FS_WRITE hand
        writes on a passed exam), counts the backing b2_learning_note goals by
        status, and prints the most recent note's content. Pure read: no store
        mutation, no write, no flag flip -- so the operator can SEE that the
        armed Etap 2 actually fired after a restart.
        """
        import os as _os
        import glob as _glob

        from agent_core.hands.sandbox_writer import default_sandbox_root

        # Resolve the sandbox root EXACTLY like the seed/write path does, so the
        # files we list are the ones the hand actually wrote.
        root = None
        planner = getattr(ctx, "planner_core", None)
        if planner is not None:
            root = getattr(planner, "_fs_sandbox_root", None)
        if not root:
            try:
                from maria_core.sys.config import BASE_DIR
                root = default_sandbox_root(BASE_DIR)
            except Exception:
                root = default_sandbox_root(".")

        # Backing goals (b2_learning_note), grouped by status.
        active = achieved = other = 0
        store = getattr(ctx, "goal_store", None)
        if store is not None:
            try:
                for g in store.get_all():
                    meta = getattr(g, "metadata", None) or {}
                    if not meta.get("b2_learning_note"):
                        continue
                    if getattr(g, "is_active", False):
                        active += 1
                    elif getattr(getattr(g, "status", None), "value", "") == "achieved":
                        achieved += 1
                    else:
                        other += 1
            except Exception:
                pass

        # Notes actually on disk (newest first).
        files = []
        try:
            files = sorted(
                _glob.glob(_os.path.join(root, "maria_note_*.txt")),
                key=lambda p: _os.path.getmtime(p),
                reverse=True,
            )
        except Exception:
            pass

        lines = [
            "Notatki z nauki (autonomiczna reka FS_WRITE):",
            f"  cele b2_learning_note: {achieved} domkniete / {active} otwarte"
            + (f" / {other} inne" if other else ""),
            f"  pliki na dysku: {len(files)}",
        ]
        if not files:
            lines.append("(jeszcze brak -- Maria zapisze gdy zda egzamin po restarcie)")
            return "\n".join(lines)

        for p in files[:5]:
            try:
                sz = _os.path.getsize(p)
            except OSError:
                sz = 0
            lines.append(f"- {_os.path.basename(p)} ({sz} B)")

        # Most recent note's content (jailed <=1 KiB, safe to print).
        try:
            newest = files[0]
            with open(newest, "r", encoding="utf-8", errors="replace") as fh:
                body = fh.read(1024).strip()
            lines.append("")
            lines.append(f"Ostatnia ({_os.path.basename(newest)}):")
            lines.append(body)
        except Exception:
            pass
        return "\n".join(lines)

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

    def _cmd_project(args):
        """Create a long-horizon project goal with sub-goals + an optional deadline.

        Etap B operator producer ("kran"): turns the dormant sub-goal tree +
        deadline machinery live. The project (parent USER goal) owns its sub-goals
        (child USER goals); the planner's rollup phase completes the parent when
        all children finish, and the children inherit the deadline so urgency
        prioritises the actionable leaves.

        Usage:
          /project <nazwa> | <termin> | <podcel1> ; <podcel2> ; ...
          /project heldout <N> <nazwa> | <termin> | <podcele...>
        Examples:
          /project Hiszpanski | za 30 dni | slownictwo ; gramatyka ; rozmowki
          /project Remont | 2026-07-15 | demontaz ; malowanie
          /project Szybki cel | jutro 18:00          (sam termin, bez pod-celow)
          /project heldout 12 Kronika srebra | za 14 dni | zebrac ; timeline

        Tryb heldout (Option C, 2026-07-12): dzieci dostaja source_kind=market
        + provenance_target_n=N + verification_mode='heldout' -- ich postep
        licza WYLACZNIE egzaminy komisyjne (zamrozony klucz + mechaniczna
        ocena), zwykly egzamin LLM ich nie domyka.
        """
        if not ctx.goal_store:
            return "GoalStore not available"
        from agent_core.goals.goal_model import (
            GoalType, GoalStatus, MAX_ACTIVE_GOALS, create_goal,
        )

        name, deadline_text, subgoals = _parse_project_args(args)
        # Optional heldout prefix in the first segment:
        #   "heldout 12 Kronika srebra" -> N=12, name="Kronika srebra"
        heldout_n = None
        if name:
            _toks = name.split()
            if _toks and _toks[0].lower() == "heldout":
                heldout_n = 12  # default pantry target (Kronika precedent)
                rest = _toks[1:]
                if rest and rest[0].isdigit():
                    heldout_n = int(rest[0])
                    rest = rest[1:]
                name = " ".join(rest).strip()
                if not name:
                    return (
                        "Tryb heldout wymaga nazwy: /project heldout <N> "
                        "<nazwa> | <termin> | <podcele>"
                    )
                if not (1 <= heldout_n <= 50):
                    return "Tryb heldout: N poza zakresem (1-50)."
        if not name:
            return (
                "Uzycie: /project <nazwa> | <termin> | <podcel1> ; <podcel2> ...\n"
                "Przyklad: /project Hiszpanski | za 30 dni | slownictwo ; gramatyka"
            )
        if len(subgoals) > MAX_PROJECT_SUBGOALS:
            return (
                f"Za duzo pod-celow ({len(subgoals)}), max {MAX_PROJECT_SUBGOALS}. "
                "Rozbij projekt na mniejsze."
            )
        try:
            deadline = _parse_project_deadline(deadline_text)
        except ValueError as e:
            return (
                f"Termin: {e}\n"
                "Akceptuje: 'za 30 dni', 'jutro 9:00', '2026-07-15', "
                "'2026-07-15 18:00'."
            )
        if deadline is not None and deadline <= time.time():
            return (
                "Termin jest w przeszlosci. Podaj date w przod (lub pomin termin)."
            )

        # Capacity guard: /project creates 1 parent + N children, ALL ACTIVE, in a
        # burst. GoalStore.create() only reclaims PENDING slots on overflow, so an
        # active set already full of ACTIVE goals would silently exceed
        # MAX_ACTIVE_GOALS. Validate upfront (producer-validates-strictly) against
        # the irreducible floor = goals that cannot be abandoned (status ACTIVE).
        needed = 1 + len(subgoals)
        running = sum(
            1 for g in ctx.goal_store.get_active()
            if g.status == GoalStatus.ACTIVE
        )
        free = MAX_ACTIVE_GOALS - running
        if needed > free:
            return (
                f"Za malo miejsca w aktywnych celach (potrzeba {needed}, wolne "
                f"{max(free, 0)} z {MAX_ACTIVE_GOALS}). Domknij cele (/goals) lub "
                "rozbij projekt na mniejsze."
            )

        parent = create_goal(
            goal_type=GoalType.USER,
            description=name,
            priority=0.55,  # below children so leaves get worked first
            status=GoalStatus.ACTIVE,
            created_by="operator",
            deadline=deadline,
            metadata=(
                {"project": True, "subgoal_count": len(subgoals),
                 "verification_mode": "heldout"}
                if heldout_n else
                {"project": True, "subgoal_count": len(subgoals)}
            ),
        )
        parent_id = ctx.goal_store.create(parent)

        created_children = []
        for text in subgoals:
            child = create_goal(
                goal_type=GoalType.USER,
                description=text,
                priority=0.6,
                status=GoalStatus.ACTIVE,
                created_by="operator",
                parent_goal_id=parent_id,
                deadline=deadline,  # inherit so urgency boosts the leaves
                # topics: the sub-goal name feeds the learn filter and the
                # B2 FETCH pump (no material on the topic -> Maria fetches it)
                metadata=(
                    {"project_parent": parent_id, "topics": [text],
                     "source_kind": "market",
                     "provenance_target_n": heldout_n,
                     "verification_mode": "heldout"}
                    if heldout_n else
                    {"project_parent": parent_id, "topics": [text]}
                ),
            )
            cid = ctx.goal_store.create(child)
            created_children.append((cid, text))
        ctx.goal_store.save()

        from agent_core.reminders import format_scheduled_time
        when = format_scheduled_time(deadline) if deadline else "brak"
        lines = [
            f"*Projekt utworzony:* {name}",
            f"  [{parent_id[:8]}] termin: {when}",
        ]
        if heldout_n:
            lines.append(
                f"  tryb: HELDOUT (spizarnia N={heldout_n}/podcel; "
                "postep licza tylko egzaminy komisyjne)"
            )
        if created_children:
            lines.append(f"*Pod-cele ({len(created_children)}):*")
            for cid, text in created_children:
                lines.append(f"  [{cid[:8]}] {text[:60]}")
        else:
            lines.append("(bez pod-celow - sam cel projektu)")
        lines.append("\n/projects pokaze postep drzewa.")
        return "\n".join(lines)

    def _cmd_projects(args):
        """List project trees: each parent goal with its children + progress.

        Read-only view so the operator can watch rollup close a parent as its
        sub-goals finish, and see deadline urgency at a glance.
        """
        if not ctx.goal_store:
            return "GoalStore not available"
        from agent_core.goals.goal_model import TERMINAL_STATUSES
        from agent_core.reminders import format_scheduled_time

        all_goals = ctx.goal_store.get_all()
        parents = [g for g in all_goals if g.metadata.get("project")]
        if not parents:
            return "Brak projektow. Utworz: /project <nazwa> | <termin> | <pod-cele>"

        parents.sort(key=lambda g: g.created_at, reverse=True)
        lines = []
        for p in parents[:15]:
            children = ctx.goal_store.get_children(p.id)
            done = sum(1 for c in children if c.status in TERMINAL_STATUSES)
            when = format_scheduled_time(p.deadline) if p.deadline else "brak"
            lines.append(
                f"*{p.description[:50]}* [{p.id[:8]}] {p.status.value} "
                f"{p.progress:.0%} ({done}/{len(children)}) termin: {when}"
            )
            for c in sorted(children, key=lambda x: x.created_at):
                mark = "x" if c.status in TERMINAL_STATUSES else " "
                lines.append(f"   [{mark}] {c.description[:55]} ({c.status.value})")
        return "\n".join(lines)

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
            # A judge STALL (timeout/parse-fail/nothing-to-judge) comes back as
            # reason="unfaithful_to_sources" with the real reason preserved in
            # the faithfulness dict. Surface it distinctly: otherwise it reads
            # byte-identical to "claims don't hold to sources" -- the exact
            # misdiagnosis that would corrupt a SYNTH_ENABLED go/no-go call.
            from agent_core.synthesis import is_judge_stall
            _faith = report.get("faithfulness")
            if is_judge_stall(_faith):
                return (
                    "[Synteza] NIE rozstrzygnieto. SEDZIA WIERNOSCI NIE "
                    f"ZADZIALAL ({_faith.get('reason')}) -- to NIE ocena "
                    "tresci, tylko timeout/blad lokalnego qwen3 na CPU. "
                    "Synteza moze byc dobra; brak realnego sygnalu wiernosci."
                )
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
        # One-slot cells: record which backend ACTUALLY authored/graded (NIM vs
        # local fallback) -- copied into the sandbox exam record by
        # run_exam_if_ready, same contract as the teacher exam path.
        synth_author_cell = {"backend": None}
        synth_grader_cell = {"backend": None}
        grader_fn = _make_exam_grader_fn(
            examiner_model, scheduler=scheduler, used_cell=synth_grader_cell)
        author_fn = _make_exam_author_fn(
            examiner_model, scheduler=scheduler, used_cell=synth_author_cell)

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
                # Belt (2026-06-14): pre-warm the judge model INSIDE the lease,
                # BEFORE the deadline-bounded call. A cold qwen3 load (~10-30s
                # reading 5GB from disk on this CPU box, or a ModelScheduler
                # idle-unload between cycles) would otherwise be paid OUT OF the
                # judge's 540s budget -- and a cold load on top of a 12-source
                # prefill is exactly how a GOOD synthesis fail-closes on a
                # timeout that was never the judge's verdict. Warm-up is
                # best-effort (errors swallowed); keep_alive holds the model in
                # RAM through to the real call below, which still fail-closes on
                # its own deadline.
                try:
                    from agent_core.llm.warmup import warm_up_models
                    warm_up_models(
                        [examiner_model], keep_alive="10m", timeout_s=120,
                    )
                except Exception as exc:  # warm-up must never abort the judge
                    logger.debug(
                        "[Synthesis] judge pre-warm skipped: %s", exc)
                # Dedicated, generous budget: the judge reads up to 12 (capped)
                # sources on CPU. Measured ~348s on a clean box for a 12-source
                # synthesis with /no_think + tight caps (live 2026-06-13), so
                # 540s gives ~190s headroom for a richer synthesis or mild load
                # -- the cost of fail-closing a GOOD synthesis (false reject) is
                # worse than a one-a-day ~6-min heavy-mutex hold. With the model
                # pre-warmed above, the budget now covers prefill+inference, not
                # a cold load. Output is a short JSON verdict, so predict stays low.
                return call_with_timeout(
                    lambda: call_ollama(
                        prompt, model=examiner_model, num_predict=400,
                        num_ctx=8192, timeout=530,
                    ),
                    timeout_sec=540,
                    label="synthesis_faithfulness",
                )

        grader_meta = {
            # NOTE: the planned label is NIM-first, but the record now carries
            # the ACTUAL grader via the cells below -- the real groundedness
            # signal is still the LOCAL faithfulness judge above, and synthesis
            # beliefs are capped at OBSERVATION regardless (Brick 3).
            "independent": examiner_model != student_model,
            "grader": f"nim-first|{examiner_model}",
            "student": student_model,
            "grader_cell": synth_grader_cell,
            "author_cell": synth_author_cell,
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
        # Feed the picker the FULL eligible set (limit=None), not the top-10.
        # The picker's rule is least-recently-synthesized; capping candidates
        # at the 10 richest-by-source-count tags meant the autonomous loop
        # forever re-synthesized the SAME ~10 strongest topics while 990+
        # eligible topics were never pickable -- the exact opposite of the
        # "spread across the corpus" promise. The top-10 cap belongs only to
        # the human-facing /synthesize suggestion menu (audit 2026-06-15 #3).
        eligible = SynthesisAgent(LONGTERM_MEMORY).topics(limit=None)

        decision = decide_synthesis(eligible, state, time.time(), in_window)
        if decision["action"] != "synthesize":
            return  # cooldown / poza oknem / brak tematow -- cicho, normalne

        if not _synthesis_lock.acquire(blocking=False):
            return  # operator (lub poprzedni pick) w trakcie -- nastepnym razem

        topic = decision["topic"]

        def _run():
            report = None
            try:
                report = _run_synthesis_cycle(topic)
            except Exception as e:
                logger.warning(
                    "[Synthesis] autonomiczny cykl padl dla '%s': %s", topic, e,
                )
                report = {"success": False, "reason": "cycle_error",
                          "error": str(e), "topic": topic}
            finally:
                # ALWAYS surface the run before releasing the lock. Even a
                # crashed run consumed the day's only synthesis budget, so an
                # invisible failure is a real legibility hole (audit 2026-06-15
                # #5). The release sits in its OWN finally so a slow/throwing
                # report never strands the SHARED lock.
                try:
                    # (a) Event UNCONDITIONALLY -- the cron watcher + log scans
                    # must see a failed run, not silence.
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
                    # (b) Same-day failure alert. A judge-stall returns
                    # success=False too, so this covers it; success stays on
                    # the bulletin + cron path (no chat spam on the daily win).
                    if not report.get("success"):
                        try:
                            bridge.bot.send_message(
                                f"[Auto] {_format_synthesis_report(report)}"
                            )
                        except Exception:
                            pass
                finally:
                    _synthesis_lock.release()

        # Stempel budzetu dnia PRZED cyklem: nieudany przebieg nie ma
        # retry-stormu (lekcja NREM 2026-06-12 -- cooldown przezywa restart).
        # The thread owns the lock release once spawned; ANY exception
        # before it starts (a save_state TypeError on a corrupt state file,
        # or Thread.start RuntimeError under thread/FD exhaustion) must free
        # the SHARED _synthesis_lock here -- otherwise it leaks for the whole
        # process lifetime and ALL synthesis (autonomous + manual /synthesize)
        # dies silently until a restart. Mirrors the manual /synthesize guard.
        spawned = False
        try:
            save_state(state_path, record_pick(state, topic, time.time()))
            logger.info(
                "[Synthesis] autonomiczny pick: '%s' (%d zrodel, tryb observe-gate)",
                topic, decision.get("sources", 0),
            )
            threading.Thread(
                target=_run, daemon=True, name="AutoSynthesis",
            ).start()
            spawned = True
        finally:
            if not spawned:
                _synthesis_lock.release()

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
        from agent_core.synthesis import is_judge_stall, read_synthesis_reviews
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
            if is_judge_stall(faith):
                out.append(
                    f"  wiernosc: SEDZIA NIE ZADZIALAL ({faith.get('reason')})"
                    " -- timeout/blad qwen3, NIE ocena tresci (brak sygnalu)"
                )
            elif isinstance(faith, dict) and faith.get("total"):
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

    # -- Conscious unlearn (rollback/quarantine) -- operator surface --
    # Master-gated by the bridge (like every command here). Plain-text, ids in
    # backticks: synthesis/concept ids carry underscores that bare Markdown eats
    # (the 2026-06-09 /approve_note lesson). Irreversible ops (/retract,
    # /forget_source) require a two-step confirm.

    def _cmd_quarantine(args):
        """/quarantine <belief_id|entity> -- reversible soft-hide (undo:
        /unquarantine). Hides the belief from every consumer + evicts its
        vector, but keeps it on disk + in the audit ledger."""
        wm = getattr(ctx, "world_model", None)
        if wm is None:
            return "[Unlearn] WorldModel niedostepny."
        target = (args or "").strip()
        if not target:
            return "Uzycie: /quarantine <belief_id|entity>"
        res = wm.quarantine_belief(
            target, reason="operator quarantine", actor="operator",
            actor_detail="telegram")
        if not res.get("ok"):
            return f"[Unlearn] Nie wykonano: {res.get('message')}"
        ents = ", ".join(res.get("entities", []))
        return (f"[Unlearn] Kwarantanna: {res['count']} belief(ow) [{ents}] "
                f"schowane. Cofnij: /unquarantine {target}")

    def _cmd_unquarantine(args):
        """/unquarantine <belief_id|entity> -- restore a quarantined belief."""
        wm = getattr(ctx, "world_model", None)
        if wm is None:
            return "[Unlearn] WorldModel niedostepny."
        target = (args or "").strip()
        if not target:
            return "Uzycie: /unquarantine <belief_id|entity>"
        res = wm.unquarantine_belief(
            target, actor="operator", actor_detail="telegram")
        if not res.get("ok"):
            return f"[Unlearn] Nie wykonano: {res.get('message')}"
        ents = ", ".join(res.get("entities", []))
        return f"[Unlearn] Przywrocono {res['count']} belief(ow) [{ents}]."

    def _cmd_retract(args):
        """/retract <belief_id|entity> <powod> [confirm] -- audited removal
        (IRREVERSIBLE: confidence 0, denylisted so it never re-mints). Without
        'confirm' shows a preview. Use a belief_id for multi-word entities."""
        wm = getattr(ctx, "world_model", None)
        if wm is None:
            return "[Unlearn] WorldModel niedostepny."
        parts = (args or "").strip().split()
        if len(parts) < 2:
            return "Uzycie: /retract <belief_id|entity> <powod> [confirm]"
        confirm = parts[-1].lower() == "confirm"
        if confirm:
            parts = parts[:-1]
        target = parts[0]
        reason = " ".join(parts[1:]).strip() or "operator retract"
        targets = wm._resolve_targets(target)
        if not targets:
            return f"[Unlearn] Brak aktywnego beliefa dla: {target}"
        if not confirm:
            lines = [f"[Unlearn] /retract usunie {len(targets)} belief(ow) "
                     "(NIEODWRACALNE):"]
            for b in targets[:10]:
                lines.append(f"  `{b.belief_id}` [{b.entity}] "
                             f"{(b.content or '')[:60]}")
            lines.append(f"Potwierdz: /retract {target} {reason} confirm")
            return "\n".join(lines)
        res = wm.retract_belief(
            target, reason=reason, actor="operator", actor_detail="telegram")
        if not res.get("ok"):
            return f"[Unlearn] Nie wykonano: {res.get('message')}"
        return (f"[Unlearn] Wycofano {res['count']} belief(ow). Audyt: "
                f"`{res.get('retraction_id')}`. /retractions by zobaczyc.")

    def _cmd_forget_source(args):
        """/forget_source <file_id|synthesis_id> <powod> [confirm] -- root-and-
        branch retract of every belief derived from a source (the pull for a
        flagged-bad synthesis) + denylist so build_all never re-creates them."""
        wm = getattr(ctx, "world_model", None)
        if wm is None:
            return "[Unlearn] WorldModel niedostepny."
        parts = (args or "").strip().split()
        if len(parts) < 2:
            return "Uzycie: /forget_source <file_id|synthesis_id> <powod> [confirm]"
        confirm = parts[-1].lower() == "confirm"
        if confirm:
            parts = parts[:-1]
        source = parts[0]
        reason = " ".join(parts[1:]).strip() or "operator forget_source"
        targets = wm.store.get_current_by_source(source)
        if not confirm:
            if targets:
                lines = [f"[Unlearn] /forget_source wytnie {len(targets)} "
                         f"belief(ow) ze zrodla `{source}` (NIEODWRACALNE, + denylist):"]
                for b in targets[:10]:
                    lines.append(f"  `{b.belief_id}` [{b.entity}]")
            else:
                lines = [f"[Unlearn] Zero aktywnych beliefow ze zrodla `{source}`; "
                         "forget_source i tak doda denylist (nie odrosna przy budowie)."]
            lines.append(f"Potwierdz: /forget_source {source} {reason} confirm")
            return "\n".join(lines)
        res = wm.forget_source(
            source, reason=reason, actor="operator", actor_detail="telegram")
        if res.get("count", 0) == 0:
            return (f"[Unlearn] Zero aktywnych beliefow, ale zrodlo `{source}` na "
                    f"denylescie (nie odrosnie). Audyt: `{res.get('retraction_id')}`.")
        return (f"[Unlearn] Wyciecie zrodla `{source}`: {res['count']} belief(ow) "
                f"wycofane + denylist. Audyt: `{res.get('retraction_id')}`.")

    def _cmd_retractions(args):
        """/retractions [n] -- the conscious-unlearn audit ledger (newest
        first): who retracted what, when, why. The go/no-go evidence + the
        operator's record of every soft-hide / removal."""
        wm = getattr(ctx, "world_model", None)
        if wm is None:
            return "[Unlearn] WorldModel niedostepny."
        try:
            n = max(1, min(30, int((args or "").strip() or 10)))
        except (TypeError, ValueError):
            n = 10
        rows = wm.list_retractions(limit=n)
        if not rows:
            return ("[Unlearn] Ksiega pusta -- jeszcze nic nie wycofano. "
                    "/quarantine /retract /forget_source zapisuja tutaj.")
        out = [f"[Unlearn] Ostatnie {len(rows)} (najnowsze pierwsze):"]
        for r in rows:
            ents = ", ".join(r.get("target_entities") or []) or "?"
            scope = r.get("source_scope") or {}
            scope_s = (f" zrodlo={scope.get('value')}"
                       if scope.get("kind") == "by_source" else "")
            out.append("")
            out.append(f"- {r.get('op', '?')} x{r.get('count', '?')} "
                       f"[{r.get('actor', '?')}/{r.get('actor_detail', '')}]"
                       f"{scope_s}")
            out.append(f"  encje: {ents}")
            if r.get("reason"):
                out.append(f"  powod: {r.get('reason')}")
            out.append(f"  id: `{r.get('retraction_id', '?')}` | {r.get('iso', '')}")
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
            "/synthreview [n] - ostatnie syntezy (observe)\n"
            "/validate - cross-validation\n"
            "/board - tablica potrzeb\n"
            "\n*Cofanie wiedzy (rollback):*\n"
            "/quarantine <id|encja> - schowaj belief (odwracalne)\n"
            "/unquarantine <id|encja> - przywroc\n"
            "/retract <id|encja> <powod> [confirm] - usun (audyt)\n"
            "/forget_source <zrodlo> <powod> [confirm] - wytnij cale zrodlo\n"
            "/retractions [n] - ksiega cofniec (audyt)\n"
            "\n*Kodowanie (Code Agent):*\n"
            "/code <zadanie> - zlec kodowanie\n"
            "/code approve - zatwierdz krok\n"
            "/code status - aktywna sesja\n"
            "/code history - historia\n"
            "\n*Pliki:*\n"
            "/wyslij <sciezka> - przeslij dokument z repo (docs/)\n"
            "\n*Zdalna naprawa (izolowana):*\n"
            "/fix <opis> - Codex naprawia w worktree, przysle diff\n"
            "/fix_list - oczekujace galezie fix/\n"
            "/fix_apply <galaz> - scal (gdy drzewo czyste)\n"
            "/fix_drop <galaz> - odrzuc\n"
            "/undo_list - dziennik cofania akcji efektora\n"
            "/undo_preview <id> - jak cofnac dana akcje\n"
            "\n*AI asystenci:*\n"
            "/claude <zadanie> - analiza/odczyt kodu (read-only, 3/h)\n"
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
            "\n*Samoswiadomosc:*\n"
            "/selfstatus - aktualny stan (zdolnosci, limity)\n"
            "/selfcontext - pelny obraz sytuacji (kto, ja, misja, wiedza, wzrok)\n"
            "/lastseen - co Maria ostatnio widziala (cowidzialas)\n"
            "/growth - kierunki rozwoju (rozwoj; top 5)\n"
            "/samorozwoj - co Maria chce w sobie poprawic + czy utknelo (petla)\n"
            "/approve_dev <token> - przejmij pomysl ktory Maria podsunela\n"
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

    def _send_repo_doc_async(abs_path, label="WyslijCmd"):
        """Send a pre-validated repo document on a daemon thread (a 30s upload
        must never block the poll loop). The document itself is the result;
        only failures get an extra text line."""
        import threading
        from pathlib import Path as _Path
        name = _Path(abs_path).name

        def _send():
            try:
                ok = bridge.bot.send_document(abs_path, caption=f"Dokument: {name}")
                if not ok:
                    bridge.bot.send_message(f"Nie udalo sie wyslac: {name}")
            except Exception as e:
                bridge.bot.send_message(f"Blad wysylki: {e}")

        threading.Thread(target=_send, daemon=True, name=label).start()
        return name

    def _cmd_wyslij(args):
        """Send a repo document via Telegram: /wyslij <path>.

        Deterministic, safe counterpart to asking in chat. Whitelisted to docs/
        and claude_notes/ (plus a few top-level docs); path-jailed; secrets
        denylisted; 20 MiB cap. The morning of 2026-06-22 both the chat brain and
        /claude FAKED sending a file -- this command actually does it (or says
        plainly why not). Single source of truth for the jail: doc_sender."""
        from agent_core.telegram.doc_sender import resolve_sendable
        res = resolve_sendable(args or "")
        if not res.ok:
            return (
                f"{res.reason}\n"
                "Uzycie: /wyslij <sciezka>\n"
                "Przyklad: /wyslij docs/DIGITAL_HUMAN_ROADMAP.md"
            )
        name = _send_repo_doc_async(res.path, label="WyslijCmd")
        return f"Wysylam: {name}..."

    def _cmd_fix(args):
        """Remote fix in an isolated worktree: /fix <opis>.

        Dispatches Codex (workspace-write) into a throwaway git worktree branched
        off HEAD, OUTSIDE the live repo, so the running daemon is untouched. Sends
        the diff to Telegram for review; applying (/fix_apply) stays operator-gated
        and clean-tree only. Eryk's 2026-06-22 ask: react from work, not just read."""
        if not args or not args.strip():
            return (
                "Uzycie: /fix <opis naprawy>\n"
                "Przyklad: /fix popraw literowke w docstringu doc_sender\n"
                "Codex pracuje w IZOLOWANYM worktree (zywy demon nietkniety), "
                "przysle diff. Scalanie: /fix_apply <galaz> (gdy drzewo czyste) "
                "lub w sesji. /fix_list, /fix_drop <galaz>."
            )
        task = args.strip()
        from agent_core.telegram import remote_fix
        if remote_fix.is_busy():
            return "Inny /fix wlasnie trwa - poczekaj az skonczy."

        import threading

        def _run():
            try:
                from agent_core.llm.codex_client import CodexClient
                codex = CodexClient()
                bridge.bot.send_message(
                    f"[/fix] Pracuje w izolowanym worktree nad: {task[:80]}...\n"
                    "(Codex, do ~15 min). Diff przysle po skonczeniu."
                )
                res = remote_fix.create_fix(task, codex)
                if not res.get("ok"):
                    msg = f"[/fix] Nie wyszlo: {res.get('reason')}"
                    if res.get("summary"):
                        msg += f"\n\nCodex: {res['summary'][:600]}"
                    bridge.bot.send_message(msg)
                    return
                branch = res["branch"]
                bridge.bot.send_message(
                    f"[/fix] Gotowe na galezi `{branch}`.\n\n"
                    f"Codex: {(res.get('summary') or '(brak)')[:900]}\n\n"
                    f"Zmiany:\n{res.get('stat','')[:900]}\n\n"
                    f"Scal: /fix_apply {branch} (gdy drzewo czyste) lub w sesji. "
                    f"Odrzuc: /fix_drop {branch}"
                )
                diff = res.get("diff") or ""
                from agent_core.telegram.remote_fix import _MAX_DIFF_INLINE
                if 0 < len(diff) <= _MAX_DIFF_INLINE:
                    # parse_mode=None: a diff may itself contain ``` and break a
                    # Markdown code fence -> send as plain text, no fence.
                    bridge.bot.send_message(f"diff {branch}:\n{diff}", parse_mode=None)
                elif diff:
                    import tempfile
                    import os as _os
                    fd, path = tempfile.mkstemp(prefix="maria_fix_", suffix=".patch")
                    try:
                        with _os.fdopen(fd, "w", encoding="utf-8") as f:
                            f.write(diff)
                        bridge.bot.send_document(path, caption=f"diff: {branch}")
                    finally:
                        try:
                            _os.remove(path)
                        except OSError:
                            pass
            except Exception as e:
                bridge.bot.send_message(f"[/fix] Blad: {e}")

        threading.Thread(target=_run, daemon=True, name="RemoteFix").start()
        return f"[/fix] Przyjeto: '{task[:60]}'. Worktree + Codex startuje..."

    def _cmd_fix_list(args):
        """List pending fix/ branches: /fix_list"""
        from agent_core.telegram import remote_fix
        branches = remote_fix.list_fix_branches()
        if not branches:
            return "Brak oczekujacych galezi fix/."
        return ("Oczekujace naprawy:\n" + "\n".join(f"- {b}" for b in branches)
                + "\n\nScal: /fix_apply <galaz> | Odrzuc: /fix_drop <galaz>")

    def _cmd_fix_apply(args):
        """Merge a fix/ branch into the live branch (clean-tree only): /fix_apply <galaz>"""
        if not args or not args.strip():
            return "Uzycie: /fix_apply <galaz>  (zobacz /fix_list)"
        from agent_core.telegram import remote_fix
        res = remote_fix.apply_fix(args.strip())
        if not res.get("ok"):
            return f"[/fix_apply] {res.get('reason')}"
        return f"[/fix_apply] {res['branch']} -> {res['into']}. {res.get('note','')}"

    def _cmd_fix_drop(args):
        """Delete a fix/ branch: /fix_drop <galaz>"""
        if not args or not args.strip():
            return "Uzycie: /fix_drop <galaz>  (zobacz /fix_list)"
        from agent_core.telegram import remote_fix
        res = remote_fix.drop_fix(args.strip())
        return (f"[/fix_drop] Usunieto {res['branch']}." if res.get("ok")
                else f"[/fix_drop] {res.get('reason')}")

    def _cmd_undo_list(args):
        """List recent effector undo-journal entries: /undo_list [N]"""
        from agent_core.effector.undo_journal import (
            EffectorUndoJournal, format_undo_list,
        )
        n = int(args.strip()) if args.strip().isdigit() else 10
        return format_undo_list(EffectorUndoJournal().list_recent(n))

    def _cmd_undo_preview(args):
        """Preview how a journaled effector action would be undone: /undo_preview <id>"""
        rid = args.strip()
        if not rid:
            return "Uzycie: /undo_preview <record_id>  (zobacz /undo_list)"
        from agent_core.effector.undo_journal import (
            EffectorUndoJournal, format_undo_preview,
        )
        return format_undo_preview(EffectorUndoJournal().get(rid))

    def _cmd_drill_undo(args):
        """Proof of the undo EXECUTION path against the FS sandbox (no live OpenClaw).

        Two sub-cases run end to end through the REAL EffectorCoordinator._execute_undo:
          - RESTORE: a sandbox file is overwritten, then undo restores its prior content.
          - REMOVE:  a NEW sandbox file (name with a space) is created, then undo removes
                     it -- exercising the argv-safe rm inverse (FIX-2).
        The invoke is a jailed fake doing real file I/O confined to meta_data/fs_sandbox/;
        EFFECTOR_UNDO_EXECUTE_ENABLED is flipped on only for this run (restored after).
        Never touches the live, unsandboxed OpenClaw -- proves capture -> build_inverse
        -> execute -> verify -> mark_undone with zero live risk."""
        import os
        from pathlib import Path
        from agent_core.effector.coordinator import EffectorCoordinator
        from agent_core.effector.undo_journal import EffectorUndoJournal, STATUS_UNDONE
        from agent_core.hands.sandbox_writer import default_sandbox_root

        try:
            from maria_core.sys.config import BASE_DIR
            root = Path(default_sandbox_root(BASE_DIR))
        except Exception:
            root = Path(default_sandbox_root("."))
        root.mkdir(parents=True, exist_ok=True)

        def _jailed(path):
            p = Path(path).resolve()
            rp = root.resolve()
            if not (p == rp or rp in p.parents):
                raise ValueError(f"path escapes sandbox: {path}")
            return p

        def invoke(tool, a):
            if tool == "write":
                _jailed(a["path"]).write_text(a["content"], encoding="utf-8")
                return {"ok": True, "result": "ok"}
            if tool == "read":
                p = _jailed(a["path"])
                if p.is_file():
                    return {"ok": True, "result": p.read_text(encoding="utf-8")}
                return {"ok": False, "error": "cat: No such file or directory"}
            if tool == "exec":
                argv = a.get("argv") or []
                if len(argv) >= 3 and argv[0] == "rm":
                    p = _jailed(argv[-1])
                    if p.exists():
                        p.unlink()
                return {"ok": True, "result": ""}
            return {"ok": False, "error": "unknown tool"}

        def _read_or_none(p):
            r = invoke("read", {"path": p})
            return r.get("result") if r.get("ok") else None

        journal = EffectorUndoJournal(path=root / "drill_undo_journal.jsonl")
        coord = EffectorCoordinator(openclaw_client=None, undo_journal=journal)
        restore_path = root / "drill_restore.txt"
        remove_path = root / "drill_new file.txt"  # space -> proves argv-safe rm

        prev = os.environ.get("EFFECTOR_UNDO_EXECUTE_ENABLED")
        os.environ["EFFECTOR_UNDO_EXECUTE_ENABLED"] = "1"
        try:
            # RESTORE: prior content exists, action overwrites, undo restores it.
            invoke("write", {"path": str(restore_path), "content": "OLD"})
            rec1 = journal.record_action(
                tool="write", args={"path": str(restore_path), "content": "NEW"},
                read_fn=_read_or_none)
            invoke("write", {"path": str(restore_path), "content": "NEW"})  # the action
            out1 = coord._execute_undo(rec1.record_id, invoke=invoke)
            restored = restore_path.read_text(encoding="utf-8") if restore_path.exists() else None
            restore_ok = bool(out1.get("ok")) and restored == "OLD"

            # REMOVE: no prior file, action creates it, undo removes it.
            rec2 = journal.record_action(
                tool="write", args={"path": str(remove_path), "content": "NEW"},
                read_fn=_read_or_none)
            invoke("write", {"path": str(remove_path), "content": "NEW"})  # the action (create)
            out2 = coord._execute_undo(rec2.record_id, invoke=invoke)
            remove_ok = bool(out2.get("ok")) and not remove_path.exists()
            r1, r2 = journal.get(rec1.record_id), journal.get(rec2.record_id)
            undone1 = r1 is not None and r1.status == STATUS_UNDONE
            undone2 = r2 is not None and r2.status == STATUS_UNDONE
        finally:
            if prev is None:
                os.environ.pop("EFFECTOR_UNDO_EXECUTE_ENABLED", None)
            else:
                os.environ["EFFECTOR_UNDO_EXECUTE_ENABLED"] = prev
            for f in (restore_path, remove_path, root / "drill_undo_journal.jsonl"):
                try:
                    f.unlink()
                except OSError:
                    pass

        return (
            "drill_undo (sandbox, BEZ live OpenClaw):\n"
            f"  RESTORE: {'OK' if restore_ok else 'FAIL'} -- plik wrocil do 'OLD'"
            f" (journal UNDONE={undone1})\n"
            f"  REMOVE:  {'OK' if remove_ok else 'FAIL'} -- nowy plik (nazwa ze spacja)"
            f" usuniety (journal UNDONE={undone2})\n"
            "_execute_undo cofnal realne zmiany w jailu. Live = ten sam tor na "
            "OpenClaw, RAZEM po /undo_action."
        )

    def _cmd_undo_action(args):
        """Execute the inverse of a journaled effector action: /undo_action <id> [tak].

        Operator-initiated (inherently authorized, like /efapprove) but fail-closed
        and gated: EFFECTOR_UNDO_EXECUTE_ENABLED must be armed; the record must be
        auto-reversible and not already undone / not a failed action; and a TWO-STEP
        confirm is required (the bare call previews, '<id> tak' executes). This runs
        a REAL action on the live, unsandboxed OpenClaw filesystem -- armed only with
        the operator, for the live rung (use /drill_undo for a safe sandbox proof)."""
        from agent_core.effector.coordinator import _undo_execute_enabled
        from agent_core.effector.undo_journal import (
            EffectorUndoJournal, format_undo_preview,
            STATUS_UNDONE, STATUS_ACTION_FAILED,
        )
        if not _undo_execute_enabled():
            return ("Cofanie wykonawcze WYLACZONE (EFFECTOR_UNDO_EXECUTE_ENABLED OFF).\n"
                    "To uzbrajamy RAZEM na zywo -- /undo_action wykonuje realna akcje "
                    "OpenClaw. Bezpieczny dowod toru: /drill_undo.")
        parts = (args or "").split()
        if not parts:
            return "Uzycie: /undo_action <id> [tak]  (najpierw podglad, potem 'tak')"
        rid = parts[0]
        confirm = len(parts) > 1 and parts[1].strip().lower() in (
            "tak", "yes", "confirm", "ok")

        journal = getattr(ctx, "undo_journal", None) or EffectorUndoJournal()
        rec = journal.get(rid)
        if rec is None:
            return f"Nie znam wpisu {rid} (zobacz /undo_list)."
        if rec.status == STATUS_UNDONE:
            return f"Wpis {rid} juz cofniety."
        if rec.status == STATUS_ACTION_FAILED:
            return f"Wpis {rid}: akcja sie nie powiodla -- nie ma czego cofac."
        kind = (rec.inverse or {}).get("kind")
        if kind not in ("invoke", "noop"):
            return (f"Wpisu {rid} NIE da sie automatycznie cofnac "
                    f"({rec.reversibility}).\n" + format_undo_preview(rec))
        if not confirm:
            return (format_undo_preview(rec)
                    + f"\n\nWYKONAC cofniecie na zywym OpenClaw? -> /undo_action {rid} tak")

        coord = getattr(ctx, "effector_coordinator", None)
        if coord is None:
            return "Brak effector_coordinator (modul nie wired)."
        out = coord._execute_undo(rid)
        if out.get("ok"):
            return f"Cofnieto {rid} (status={out.get('reason')})."
        detail = f" -- {out.get('detail')}" if out.get("detail") else ""
        return f"Cofniecie {rid} NIE powiodlo sie: {out.get('reason')}{detail}"

    def _cmd_approve_undo(args):
        """Approve a Maria undo SUGGESTION: run the bounded inverse, then close.

        Unlike /approve_repair (close-only -- ADR-031, no clean autonomous fix),
        approving an undo EXECUTES it: the journaled, post-verified inverse is a
        single reversible OpenClaw call (the same _execute_undo proven live via
        /undo_action). Safe where dispatching Codex to prod was not. Fail-closed:
        EFFECTOR_UNDO_EXECUTE_ENABLED must be armed. Success -> mark_done + resolve
        bulletin; failure -> mark_blocked (expiry cleans it) + report. The undo
        journal already records the undo_failed status, so the operator can retry
        manually via /undo_action.
        """
        from agent_core.effector.coordinator import _undo_execute_enabled
        conductor = getattr(ctx, "maria_conductor", None)
        task_ref = args.strip() if isinstance(args, str) else str(args).strip()
        if conductor is None or not task_ref:
            return "Uzycie: /approve_undo <task_id>"

        matches = [
            task for task in conductor.get_pending_undo_suggestions()
            if _repair_task_matches(task.task_id, task_ref)
        ]
        if len(matches) != 1:
            return f"Nie znaleziono PENDING undo-suggestion: {task_ref}"

        task = matches[0]
        record_id = (task.artifacts or {}).get("undo_record_id")
        if not record_id:
            return f"Task {task.task_id} bez undo_record_id (uszkodzony wpis)."

        if not _undo_execute_enabled():
            return ("Cofanie wykonawcze WYLACZONE (EFFECTOR_UNDO_EXECUTE_ENABLED OFF).\n"
                    f"Sugestia {task.task_id} czeka -- uzbroj flage i sprobuj ponownie, "
                    "albo zostaw ja do expiry (24h).")

        coord = getattr(ctx, "effector_coordinator", None)
        if coord is None:
            return "Brak effector_coordinator (modul nie wired)."

        out = coord._execute_undo(record_id)
        from agent_core.self_repair.expiry import _close_linked_bulletin
        if out.get("ok"):
            conductor.mark_done(
                task.task_id,
                notes=f"undo executed by operator (/approve_undo): {out.get('reason')}",
            )
            _close_linked_bulletin(
                getattr(ctx, "bulletin_store", None), task.task_id,
                reason="undo_executed",
            )
            # The dispatch loop sends the returned string (telegram/__init__.py:212);
            # an explicit send here would double-deliver the confirmation (review F3).
            return (f"[Undo] {task.task_id}: cofnieto {record_id} "
                    f"(status={out.get('reason')}).")

        detail = f" -- {out.get('detail')}" if out.get("detail") else ""
        conductor.mark_blocked(
            task.task_id, reason=f"undo_failed: {out.get('reason')}{detail}")
        # Close the bulletin now, not via expiry: expiry is flag-gated for the
        # scan path, and /approve_undo is reachable with SUGGEST off (EXECUTE on,
        # or a /drill task), so an open bulletin would leak (review F4).
        _close_linked_bulletin(
            getattr(ctx, "bulletin_store", None), task.task_id,
            reason="undo_failed",
        )
        return (f"Cofniecie {record_id} NIE powiodlo sie: {out.get('reason')}{detail}\n"
                f"Task {task.task_id} -> BLOCKED (expiry sprzatnie). "
                f"Dziennik: /undo_preview {record_id}")

    def _cmd_drill_suggest_undo(args):
        """Live drill for the undo-SUGGEST channel: create a synthetic undo
        suggestion through the REAL UndoSuggestionCreator so the propose chain
        runs end to end -- gate -> PENDING task -> bulletin -> Telegram notify.
        Proves the 'Maria raises her hand' wiring; the inverse is NOT executed
        (synthetic record, no live OpenClaw). Execution is proven separately by
        /drill_undo + the live rung. The task is drill=True + approval_required,
        harmless; let expiry sweep it after 24h.

        /drill_suggest_undo        respect the gate (refused outside ACTIVE/REDUCED).
        /drill_suggest_undo force  bypass the gate -- exercise the chain on demand.
        """
        creator = getattr(ctx, "undo_suggestion_creator", None)
        if creator is None:
            return "Brak undo_suggestion_creator (modul undo_suggest nie wired)."

        arg = args.strip().lower() if isinstance(args, str) else ""
        force = arg == "force"

        from agent_core.undo_suggest.suggestion_creator import UndoSuggestionCandidate
        candidate = UndoSuggestionCandidate(
            undo_record_id=f"eundo-drill{int(time.time()) % 100000:05d}",
            tool="write",
            goal_id="drill-goal",
            summary="DRILL - synthetic undo suggestion (no real action, no live OpenClaw)",
            evidence_summary={
                "drill": True,
                "path": "/tmp/drill",
                "goal_status": "failed",
                "inverse_note": "synthetic",
                "note": "manual /drill_suggest_undo -- exercises the real propose chain",
            },
            detected_at=time.time(),
        )
        try:
            task_id = creator.create(candidate, snapshot_id="drill", bypass_gate=force)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("drill_suggest_undo create failed", exc_info=True)
            return f"Drill blad: {exc}"

        if task_id is None:
            return (
                "Drill ODMOWIONY przez gate (mode != ACTIVE/REDUCED, stale snapshot "
                "lub cooldown). To JEST realne zachowanie. Uzyj "
                "'/drill_suggest_undo force' by przetestowac sam lancuch teraz."
            )

        return (
            f"Drill OK -> {task_id} (drill, approval_required). Ping TG powinien przyjsc.\n"
            "To dowod KANALU propozycji (nie wykonania -- rekord syntetyczny). "
            "Zostaw do expiry (24h)."
        )

    def _cmd_claude(args):
        """Execute task via Claude Code CLI: /claude <task>"""
        if not args or not args.strip():
            return (
                "Uzycie: /claude <opis zadania>\n"
                "/claude to ANALIZA tekstem (bez narzedzi): nie czyta plikow, "
                "nie wykonuje akcji, nie wysle pliku.\n"
                "Przyklad: /claude przeanalizuj planner_core.py i znajdz potencjalne bugi\n"
                "Plik wyslesz przez /wyslij <sciezka>; zadanie kodowe przez /codex.\n"
                "Limit: 3/h, 15/dzien (subskrypcja operatora)"
            )
        task = args.strip()

        # The morning of 2026-06-22: /claude is a TOOL-LESS text analyst
        # (--tools "") so "wyslij mi plik X" produced hallucinated <tool_call>
        # text falsely marked COMPLETED. Catch a file-delivery request here and
        # actually send it (or redirect to /wyslij) instead of burning a Claude
        # call on something this backend categorically cannot do.
        try:
            from agent_core.telegram.doc_sender import detect_file_request
            fr = detect_file_request(task)
        except Exception:
            fr = None
        if fr is not None:
            if fr.kind == "send" and fr.path:
                name = _send_repo_doc_async(fr.path, label="ClaudeFileSend")
                return f"To nie wymaga Claude - wysylam plik: {name}..."
            return fr.message  # honest redirect to /wyslij

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
                        "[Claude] Brak uzytecznej odpowiedzi (timeout 5min albo "
                        "zadanie wymagalo akcji/narzedzi - /claude tylko analizuje "
                        "tekst). Plik wyslesz przez /wyslij <sciezka>; zadanie "
                        f"kodowe przez /codex.\nTask {task_id} zapisany."
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

    def _cmd_kronika(args):
        """Render a /project tree as a chronicle PDF: /kronika [goal_id].

        Tasma-lite (operator pull only): the project's stamped pantry
        (market_file_ids) + independent-exam verification become a
        chronological DOCUMENT sent via the existing PDF pipe. READ-ONLY --
        no goal mutation, no autocreate, no scheduling.
        """
        store = ctx.goal_store
        if not store:
            return "Brak goal_store (modul nie wired)."

        parent_id = (args or "").strip()
        if not parent_id:
            # Auto-detect: the most recent parent whose children carry a
            # market provenance stamp (there is exactly one live: Kronika).
            candidates = []
            for g in store.get_all():
                children = store.get_children(g.id)
                if children and any(
                    (c.metadata or {}).get("source_kind") == "market"
                    for c in children
                ):
                    candidates.append(g)
            if not candidates:
                return ("Nie znalazlem projektu z rynkowa spizarnia. "
                        "Uzycie: /kronika [goal_id]")
            candidates.sort(key=lambda g: getattr(g, "created_at", 0))
            parent_id = candidates[-1].id
        else:
            # Support prefix matching like /pdf does
            if store.get(parent_id) is None:
                for g in store.get_all():
                    if g.id.startswith(parent_id):
                        parent_id = g.id
                        break

        try:
            from agent_core.synthesis.kronika_report import (
                build_kronika_report,
            )
            report = build_kronika_report(store, parent_id)
        except Exception as e:
            logger.warning(f"[KRONIKA] report build failed: {e}")
            return f"Blad budowy kroniki: {e}"
        if report is None:
            return f"Cel '{parent_id}' nie istnieje. Uzycie: /kronika [goal_id]"

        parent = store.get(parent_id)
        stamp = time.strftime("%Y%m%d_%H%M")
        _send_result_pdf(
            f"kronika_{stamp}", "Kronika rynku",
            (parent.description or parent_id)[:120], report,
            timestamp=time.time(),
        )
        n_children = len(store.get_children(parent_id))
        return (
            f"Kronika wygenerowana: {parent.description[:60]} "
            f"({n_children} podceli). PDF w drodze."
        )

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
        """Telegram /wf - workflow management.

        Telegram delivers args as a STRING (handler(args: str)); split into
        tokens so subcommands work. The old code indexed the string directly
        (args[0] == first CHARACTER), so every subcommand was unreachable and
        only the bare no-arg view worked (2026-06-14 audit, Rank 9)."""
        engine = ctx.workflow_engine
        if not engine:
            return "Workflow Engine niedostepny."
        tokens = (args or "").split()
        sub = tokens[0].lower() if tokens else "list"

        if sub == "list":
            wfs = engine.list_workflows()
            active = [w for w in wfs if w["status"] in ("running", "pending", "paused")]
            if not active:
                return "Brak aktywnych workflow."
            lines = []
            for w in active[:10]:
                lines.append(f"{w['workflow_id'][:8]} {w['name']} [{w['status']}] {w['progress_pct']:.0f}%")
            return "\n".join(lines)

        if sub == "start" and len(tokens) >= 2:
            try:
                from agent_core.workflow.templates import WORKFLOW_TEMPLATES
                tmpl_name = tokens[1]
                if tmpl_name not in WORKFLOW_TEMPLATES:
                    return f"Nieznany szablon. Dostepne: {', '.join(WORKFLOW_TEMPLATES.keys())}"
                tmpl = WORKFLOW_TEMPLATES[tmpl_name]
                topic = " ".join(tokens[2:]) if len(tokens) > 2 else None
                if tmpl["needs_topic"] and not topic:
                    return f"Podaj temat: /wf start {tmpl_name} <topic>"
                steps = tmpl["factory"](topic) if tmpl["needs_topic"] else tmpl["factory"]()
                desc = tmpl["description"] + (f": {topic}" if topic else "")
                wf = engine.create(tmpl_name, desc, steps)
                engine.start(wf.workflow_id)
                return f"Workflow started: {wf.workflow_id[:8]} ({len(steps)} steps)"
            except Exception as e:
                return f"Error: {e}"

        if sub == "pause" and len(tokens) >= 2:
            wf_obj = _find_wf(engine, tokens[1])
            if not wf_obj:
                return f"Nie znaleziono: {tokens[1]}"
            ok = engine.pause(wf_obj["workflow_id"])
            return f"Paused: {wf_obj['workflow_id'][:8]}" if ok else "Nie mozna wstrzymac."

        if sub == "resume" and len(tokens) >= 2:
            wf_obj = _find_wf(engine, tokens[1])
            if not wf_obj:
                return f"Nie znaleziono: {tokens[1]}"
            ok = engine.resume(wf_obj["workflow_id"])
            return f"Resumed: {wf_obj['workflow_id'][:8]}" if ok else "Nie mozna wznowic."

        if sub == "cancel" and len(tokens) >= 2:
            wf_obj = _find_wf(engine, tokens[1])
            if not wf_obj:
                return f"Nie znaleziono: {tokens[1]}"
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
        """Telegram /env - environment mode management.

        Telegram delivers args as a STRING; tokenize (see _cmd_wf -- same
        2026-06-14 audit Rank 9 string-vs-list bug)."""
        mgr = ctx.environment_manager
        if not mgr:
            return "Environment Manager niedostepny."
        tokens = (args or "").split()
        sub = tokens[0].lower() if tokens else "status"

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

        if sub in ("switch", "set") and len(tokens) >= 2:
            try:
                from agent_core.environment.environment_model import EnvironmentMode
                mode = EnvironmentMode(tokens[1].lower())
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
    bridge.register_command("kronika", _cmd_kronika)
    bridge.register_command("wyslij", _cmd_wyslij)
    bridge.register_command("fix", _cmd_fix)
    bridge.register_command("fix_list", _cmd_fix_list)
    bridge.register_command("fix_apply", _cmd_fix_apply)
    bridge.register_command("fix_drop", _cmd_fix_drop)
    bridge.register_command("undo_list", _cmd_undo_list)
    bridge.register_command("undo_preview", _cmd_undo_preview)
    bridge.register_command("drill_undo", _cmd_drill_undo)
    bridge.register_command("undo_action", _cmd_undo_action)
    bridge.register_command("approve_undo", _cmd_approve_undo)
    bridge.register_command("drill_suggest_undo", _cmd_drill_suggest_undo)
    bridge.register_command("tasks", _cmd_tasks)
    bridge.register_command("claude", _cmd_claude)
    bridge.register_command("code", _cmd_code)
    bridge.register_command("codex", _cmd_codex)
    bridge.register_command("analyze", _cmd_analyze)
    bridge.register_command("board", _cmd_board)
    bridge.register_command("status", _cmd_status)
    bridge.register_command("selfstatus", _cmd_selfstatus)
    bridge.register_command("selfcontext", _cmd_selfcontext)
    bridge.register_command("myslenie", _cmd_myslenie)
    bridge.register_command("lastseen", _cmd_lastseen)
    bridge.register_command("cowidzialas", _cmd_lastseen)
    bridge.register_command("growth", _cmd_growth)
    bridge.register_command("rozwoj", _cmd_growth)
    bridge.register_command("samorozwoj", _cmd_samorozwoj)
    bridge.register_command("petla", _cmd_samorozwoj)
    bridge.register_command("approve_dev", _cmd_approve_dev)
    bridge.register_command("play", _cmd_play)
    bridge.register_command("strategic", _cmd_strategic)
    bridge.register_command("fs_write", _cmd_fs_write)
    bridge.register_command("heldout", _cmd_heldout)
    bridge.register_command("list_repairs", _cmd_list_repairs)
    bridge.register_command("approve_repair", _cmd_approve_repair)
    bridge.register_command("drill_repair", _cmd_drill_repair)
    bridge.register_command("drill_heartbeat", _cmd_drill_heartbeat)
    bridge.register_command("drill_outbox", _cmd_drill_outbox)
    bridge.register_command("drill_fs_write", _cmd_drill_fs_write)
    bridge.register_command("approve_note", _cmd_approve_note)
    bridge.register_command("reject_note", _cmd_reject_note)
    bridge.register_command("list_notes", _cmd_list_notes)
    bridge.register_command("learning_notes", _cmd_learning_notes)
    bridge.register_command("goals", _cmd_goals)
    bridge.register_command("approve", _cmd_approve)
    bridge.register_command("reject", _cmd_reject)
    bridge.register_command("project", _cmd_project)
    bridge.register_command("projects", _cmd_projects)
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
    bridge.register_command("quarantine", _cmd_quarantine)
    bridge.register_command("unquarantine", _cmd_unquarantine)
    bridge.register_command("retract", _cmd_retract)
    bridge.register_command("forget_source", _cmd_forget_source)
    bridge.register_command("retractions", _cmd_retractions)
    bridge.register_command("nauka", _cmd_nauka)
    bridge.register_command("do", _cmd_do)
    bridge.register_command("efapprove", _cmd_efapprove)
    bridge.register_command("efreject", _cmd_efreject)
    bridge.register_command("efstatus", _cmd_efstatus)
    bridge.register_command("authority", _cmd_authority)
    bridge.register_command("trust", _cmd_trust)
    bridge.register_command("help", _cmd_help)
    bridge.register_command("start", lambda a: _cmd_help(a))  # Handle /start from Telegram

    # --- Telegram as CHAT (not just a command console) -----------------------
    # Plain (non-slash) operator text -> Maria's daemon chat brain, with the SAME
    # identity + situational awareness as the Web UI chat. Flag-gated OFF
    # (TELEGRAM_CHAT_ENABLED) per BHP: when off, free-text keeps the historical
    # silent-consume behaviour (still fed to OperatorModel learning).
    def _chat_reply(text):
        brain = getattr(ctx, "brain", None)
        if brain is None or not hasattr(brain, "think"):
            return None
        try:
            from models.ollama_brain import BrainTimeout
        except Exception:
            BrainTimeout = ()  # pragma: no cover - import always works in prod
        try:
            # raise_on_timeout: a cold-CPU stall surfaces a clear "busy" line
            # instead of a silent dead chat (mirrors the Web UI chat, 2026-06-08).
            return brain.think(text, raise_on_timeout=True) or None
        except BrainTimeout:
            return ("Jestem teraz zajeta ciezkim mysleniem (planer/nauka na CPU), "
                    "sprobuj za chwile.")
        except Exception as e:
            logger.warning("Telegram chat reply failed: %s", e)
            return None

    import os as _os_chat
    if _os_chat.environ.get("TELEGRAM_CHAT_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        bridge.set_chat_handler(_chat_reply)
        logger.info("[Telegram] chat mode ON (plain text -> Maria's brain)")
