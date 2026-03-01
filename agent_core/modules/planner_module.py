"""Planner REPL commands: /plan, /plan status, /plan history, /plan goals."""

import logging
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class PlannerModule(MariaModule):
    """Warstwa 2 Planner - connects K1-K4 into decision loop."""

    name = "planner"
    description = "Rule-based ReAct loop (Warstwa 2)"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/plan", self._cmd_plan,
                "  /plan               - pokaz ostatnia decyzje plannera\n"
                "  /plan status        - status plannera (cykle, plany)\n"
                "  /plan history [N]   - historia decyzji (domyslnie 10)\n"
                "  /plan goals         - ranking celow wg priorytetu",
                "[PLANNER] WARSTWA 2",
            ),
        ]

    def _get_planner(self):
        """Get PlannerCore from SharedContext."""
        return getattr(self.ctx, 'planner_core', None)

    def _cmd_plan(self, args):
        """Handle /plan commands."""
        planner = self._get_planner()
        if planner is None:
            print("[Planner] Nie zainicjalizowany")
            return

        if not args:
            return self._show_last_plan(planner)

        sub = args[0].lower()
        if sub == "status":
            return self._show_status(planner)
        elif sub == "history":
            limit = 10
            if len(args) > 1:
                try:
                    limit = int(args[1])
                except ValueError:
                    pass
            return self._show_history(planner, limit)
        elif sub == "goals":
            return self._show_goals(planner)
        else:
            print(f"[Planner] Nieznana komenda: {sub}")
            print("  /plan [status|history|goals]")

    def _show_last_plan(self, planner):
        """Show the most recent plan."""
        history = planner.get_history(limit=1)
        if not history:
            print("\n[Planner] Brak decyzji")
            return

        plan = history[-1]
        ts = plan.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "?"
        success = plan.get("result", {}).get("success", False)
        status_mark = "[OK]" if success else "[!!]"

        print(f"\n[Planner] Ostatnia decyzja ({dt})")
        print("-" * 50)
        print(f"  {status_mark} Plan:    {plan.get('plan_id', '?')}")
        print(f"      Cel:     {plan.get('goal_description', '?')}")
        print(f"      Akcja:   {plan.get('action_type', '?')}")
        print(f"      Status:  {plan.get('status', '?')}")
        print(f"      Czas:    {plan.get('duration_ms', 0):.0f}ms")
        result = plan.get("result", {})
        if result:
            for k, v in result.items():
                if k != "duration_ms":
                    print(f"      {k}: {v}")
        print()

    def _show_status(self, planner):
        """Show planner status."""
        status = planner.get_status()
        print("\n[Planner] Status")
        print("-" * 40)
        print(f"  Cykli:         {status['total_cycles']}")
        print(f"  Planow:        {status['total_plans_executed']}")
        print(f"  Ostatni tick:  {status['last_cycle_tick']}")

        eval_ts = status['last_evaluation_ts']
        if eval_ts > 0:
            dt = datetime.fromtimestamp(eval_ts).strftime("%H:%M:%S")
            print(f"  Ostatni eval:  {dt}")
        else:
            print("  Ostatni eval:  brak")
        print()

    def _show_history(self, planner, limit: int = 10):
        """Show recent planner decisions."""
        history = planner.get_history(limit=limit)
        if not history:
            print("\n[Planner] Brak historii decyzji")
            return

        print(f"\n[Planner] Ostatnie {len(history)} decyzji")
        print("-" * 70)

        for entry in history:
            ts = entry.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
            action = entry.get("action_type", "?")
            goal_desc = entry.get("goal_description", "?")
            success = entry.get("result", {}).get("success", False)
            mark = "[OK]" if success else "[!!]"
            dur = entry.get("duration_ms", 0)

            if len(goal_desc) > 40:
                goal_desc = goal_desc[:37] + "..."

            print(f"  {dt} {mark} {action:12s} {goal_desc} ({dur:.0f}ms)")
        print()

    def _show_goals(self, planner):
        """Show goals ranked by effective priority."""
        goal_store = getattr(self.ctx, 'goal_store', None)
        if goal_store is None:
            print("[Planner] GoalStore nie zainicjalizowany")
            return

        active = goal_store.get_active()
        if not active:
            print("\n[Planner] Brak aktywnych celow")
            return

        # Use planner's evaluation metrics if available
        metrics = {}
        observer = getattr(self.ctx, 'evaluation_observer', None)
        if observer:
            try:
                reports = observer.get_recent_reports(1)
                if reports:
                    metrics = reports[0].metrics
            except Exception:
                pass

        ranked = planner.selector.rank_goals(active, metrics)

        print(f"\n[Planner] Cele wg priorytetu ({len(ranked)})")
        print("-" * 70)

        for score, goal in ranked:
            status = goal.status.value.upper()
            gtype = goal.type.value
            desc = goal.description
            if len(desc) > 45:
                desc = desc[:42] + "..."
            print(
                f"  {score:5.2f}  [{status:7s}] [{gtype:11s}] {desc}"
            )
        print()
