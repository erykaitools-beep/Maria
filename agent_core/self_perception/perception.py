"""Self-perception snapshot orchestration."""

import importlib
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agent_core.self_perception.snapshot_store import SnapshotStore

_MODE_LABELS = {
    "ACTIVE": "aktywna",
    "REDUCED": "ograniczona",
    "SLEEP": "uspiona",
    "SURVIVAL": "tryb awaryjny",
}

_SERVICE_ALIASES = {
    "NVIDIA NIM API": "NIM API",
    "Ollama (local LLM)": "Ollama",
    "OpenClaw Effector": "OpenClaw",
    "Codex (ChatGPT Plus)": "Codex",
    "Telegram (ClawBot)": "Telegram",
}

LimitationReporter: Any = None
ToolCapabilityRegistry: Any = None
UserFacingSelfModel: Any = None


class SelfPerception:
    """Capture and expose Maria's current self-state."""

    def __init__(
        self,
        ctx: Any,
        snapshot_store: Optional[SnapshotStore] = None,
        bulletin_store: Optional[Any] = None,
    ):
        self._ctx = ctx
        self._store = snapshot_store or SnapshotStore()
        self._bulletin_store = bulletin_store

    def take_snapshot(self) -> Dict[str, Any]:
        """Build, persist, and optionally announce a fresh self-state snapshot."""
        previous = self._store.load_latest()
        snapshot = self._build_snapshot()
        diff_fields, summaries = self._diff(previous, snapshot)
        self._store.save(snapshot)
        if diff_fields:
            self._post_bulletin(previous, snapshot, diff_fields, summaries)
        return snapshot

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Latest persisted snapshot, or None if no snapshot exists yet."""
        return self._store.load_latest()

    def is_fresh(self, max_age_seconds: float = 300.0) -> bool:
        """Return True iff the latest snapshot is younger than max_age_seconds."""
        snapshot = self.get_latest()
        if snapshot is None:
            return False
        timestamp = snapshot.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            return False
        return (time.time() - float(timestamp)) <= max_age_seconds

    def format_status_for_telegram(self) -> str:
        """Return the latest self-state snapshot as a Polish Telegram summary."""
        snapshot = self.get_latest()
        if snapshot is None:
            return "Brak snapshotu. Pierwszy zapisze sie w ciagu 30 min."

        identity = snapshot.get("identity", {})
        capabilities = snapshot.get("capabilities", {})
        services = snapshot.get("external_services", [])
        limitations = snapshot.get("limitations", {})
        severity = limitations.get("by_severity", {})

        service_status = {
            _SERVICE_ALIASES.get(str(service.get("name")), str(service.get("name"))):
            str(service.get("status", "unknown"))
            for service in services
            if isinstance(service, dict)
        }
        available_services = sum(
            1 for service in services
            if isinstance(service, dict) and service.get("status") == "available"
        )

        lines = [
            f"[Stan Marii] {snapshot.get('iso_timestamp', '')}",
            (
                f"Tryb: {snapshot.get('mode_label', 'nieznany')}  "
                f"Sesja: #{identity.get('session_count', 0)}  "
                f"Wiek: {identity.get('age_string', '')}"
            ),
            (
                f"Zdolnosci: {capabilities.get('total', 0)} "
                f"({capabilities.get('free', 0)} swobodnych, "
                f"{capabilities.get('guarded', 0)} nadzorowanych)"
            ),
            f"Serwisy: {available_services}/{len(services)} aktywnych",
            (
                f"  NIM API: {service_status.get('NIM API', 'unknown')}    "
                f"Ollama: {service_status.get('Ollama', 'unknown')}    "
                f"OpenClaw: {service_status.get('OpenClaw', 'unknown')}"
            ),
            (
                f"  Codex: {service_status.get('Codex', 'unknown')}      "
                f"Telegram: {service_status.get('Telegram', 'unknown')}"
            ),
            "",
            (
                f"Ograniczenia ({severity.get('critical', 0)} critical, "
                f"{severity.get('warning', 0)} warning, "
                f"{severity.get('info', 0)} info):"
            ),
        ]

        items = limitations.get("items", [])
        shown = [item for item in items if isinstance(item, dict)][:5]
        for item in shown:
            sev = str(item.get("severity", "info")).upper()
            lines.append(f"  [{sev}] {item.get('description', '')}")
        remaining = len(items) - len(shown) if isinstance(items, list) else 0
        if remaining > 0:
            lines.append(f"  + {remaining} more")
        return "\n".join(lines)

    def _build_snapshot(self) -> Dict[str, Any]:
        global LimitationReporter, ToolCapabilityRegistry
        if LimitationReporter is None:
            limitation_module = importlib.import_module(
                "agent_core.orchestrator.limitation_reporter",
            )
            LimitationReporter = limitation_module.LimitationReporter
        if ToolCapabilityRegistry is None:
            registry_module = importlib.import_module(
                "agent_core.orchestrator.tool_registry",
            )
            ToolCapabilityRegistry = registry_module.ToolCapabilityRegistry

        now = time.time()
        self_model = self._get_self_model()
        limitation_reporter = LimitationReporter(self._ctx)
        tool_registry = ToolCapabilityRegistry(self._ctx)

        identity = self._normalize_identity(self_model.get_identity())
        mode = self._get_mode(self_model)
        capability_summary = tool_registry.get_summary()
        services = tool_registry.list_external_services()
        limitations_report = limitation_reporter.get_report()
        awareness = self._get_awareness(self_model)

        return {
            "snapshot_id": f"sps-{uuid.uuid4().hex[:12]}",
            "timestamp": now,
            "iso_timestamp": datetime.fromtimestamp(now).replace(
                microsecond=0,
            ).isoformat(),
            "tick_count": self._get_tick_count(),
            "mode": mode,
            "mode_label": _MODE_LABELS.get(mode, "nieznany"),
            "identity": identity,
            "capabilities": self._normalize_capabilities(capability_summary),
            "external_services": self._normalize_services(services),
            "limitations": self._normalize_limitations(limitations_report),
            "knowledge": self._normalize_knowledge(awareness),
        }

    def _get_self_model(self) -> Any:
        existing = getattr(self._ctx, "user_facing_self_model", None)
        if existing is not None:
            return existing
        global UserFacingSelfModel
        if UserFacingSelfModel is None:
            self_model_module = importlib.import_module(
                "agent_core.orchestrator.self_model_facade",
            )
            UserFacingSelfModel = self_model_module.UserFacingSelfModel

        return UserFacingSelfModel(self._ctx)

    def _get_tick_count(self) -> int:
        core = getattr(self._ctx, "homeostasis_core", None)
        return int(getattr(core, "_tick_count", 0) or 0)

    def _get_mode(self, self_model: Any) -> str:
        mode = self_model.get_current_mode()
        if mode and mode != "UNKNOWN":
            return str(mode)
        core = getattr(self._ctx, "homeostasis_core", None)
        if core and hasattr(core, "get_state"):
            state = core.get_state()
            state_mode = getattr(state, "mode", None)
            if state_mode is not None:
                return str(getattr(state_mode, "name", None) or state_mode)
        return "UNKNOWN"

    def _get_awareness(self, self_model: Any) -> Dict[str, Any]:
        if hasattr(self_model, "get_awareness"):
            awareness = self_model.get_awareness()
            if isinstance(awareness, dict):
                return awareness
        return {}

    def _normalize_identity(self, identity: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": identity.get("name", "Maria"),
            "session_count": int(identity.get("session_count", 0) or 0),
            "total_uptime_hours": float(identity.get("total_uptime_hours", 0) or 0),
            "age_string": identity.get("age_string", ""),
        }

    def _normalize_capabilities(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "total": int(summary.get("total_capabilities", 0) or 0),
            "free": int(summary.get("free", 0) or 0),
            "guarded": int(summary.get("guarded", 0) or 0),
            "restricted": int(summary.get("restricted", 0) or 0),
            "categories": list(summary.get("categories", []) or []),
        }

    def _normalize_services(
        self,
        services: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        result = []
        for service in services or []:
            if not isinstance(service, dict):
                continue
            result.append({
                "name": str(service.get("name", "")),
                "status": str(service.get("status", "unknown")),
            })
        return result

    def _normalize_limitations(self, report: Dict[str, Any]) -> Dict[str, Any]:
        raw_counts = report.get("by_severity", {}) or {}
        counts = {
            "critical": int(raw_counts.get("critical", 0) or 0),
            "warning": int(raw_counts.get("warning", 0) or 0),
            "info": int(raw_counts.get("info", 0) or 0),
        }
        items = []
        for item in report.get("limitations", []) or []:
            if not isinstance(item, dict):
                continue
            items.append({
                "category": str(item.get("category", "")),
                "severity": str(item.get("severity", "info")),
                "description": str(item.get("description", "")),
            })
        return {
            "total": int(report.get("total_limitations", len(items)) or 0),
            "by_severity": counts,
            "blocked_actions_count": int(report.get("blocked_count", 0) or 0),
            "items": items,
        }

    def _normalize_knowledge(self, awareness: Dict[str, Any]) -> Dict[str, Any]:
        raw_by_status = awareness.get("files_by_status", {}) or {}
        by_status = {
            str(status): int(count) if isinstance(count, int) else len(count)
            for status, count in raw_by_status.items()
        }
        return {
            "files_total": int(awareness.get("files_total", 0) or 0),
            "files_by_status": by_status,
            "input_files_count": int(awareness.get("input_files_count", 0) or 0),
        }

    def _diff(
        self,
        previous: Optional[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Tuple[List[str], List[str]]:
        if previous is None:
            return (
                [
                    "mode",
                    "total_capabilities",
                    "external_services",
                    "limitations.critical",
                ],
                [
                    f"mode=None->{current.get('mode')}",
                    f"total_capabilities=None->{current['capabilities']['total']}",
                    "external_services=None->present",
                    (
                        "limitations.critical=None->"
                        f"{current['limitations']['by_severity']['critical']}"
                    ),
                ],
            )

        fields: List[str] = []
        summaries: List[str] = []
        if previous.get("mode") != current.get("mode"):
            fields.append("mode")
            summaries.append(f"mode={previous.get('mode')}->{current.get('mode')}")

        prev_total = previous.get("capabilities", {}).get("total")
        curr_total = current.get("capabilities", {}).get("total")
        if prev_total != curr_total:
            fields.append("total_capabilities")
            summaries.append(f"total_capabilities={prev_total}->{curr_total}")

        prev_services = self._service_status_map(previous)
        curr_services = self._service_status_map(current)
        for name in sorted(set(prev_services) | set(curr_services)):
            if prev_services.get(name) != curr_services.get(name):
                fields.append("external_services")
                summaries.append(
                    f"{name}={prev_services.get(name)}->{curr_services.get(name)}"
                )
                break

        prev_critical = previous.get("limitations", {}).get(
            "by_severity", {},
        ).get("critical")
        curr_critical = current.get("limitations", {}).get(
            "by_severity", {},
        ).get("critical")
        if prev_critical != curr_critical:
            fields.append("limitations.critical")
            summaries.append(f"limitations.critical={prev_critical}->{curr_critical}")

        return fields, summaries

    def _service_status_map(self, snapshot: Dict[str, Any]) -> Dict[str, str]:
        services = snapshot.get("external_services", [])
        result = {}
        for service in services:
            if isinstance(service, dict):
                result[str(service.get("name", ""))] = str(
                    service.get("status", "unknown"),
                )
        return result

    def _post_bulletin(
        self,
        previous: Optional[Dict[str, Any]],
        snapshot: Dict[str, Any],
        diff_fields: List[str],
        summaries: List[str],
    ) -> None:
        if self._bulletin_store is None:
            return
        bulletin_model = importlib.import_module("agent_core.bulletin.bulletin_model")
        entry_type = bulletin_model.EntryType.IMPROVEMENT

        summary = "Self-state change: " + "; ".join(summaries)
        self._bulletin_store.create_and_post(
            entry_type=entry_type,
            topic="self_state_change",
            reason_code="self_perception_diff",
            summary=summary[:200],
            requested_by="self_perception",
            priority=0.4,
            metadata={
                "snapshot_id": snapshot["snapshot_id"],
                "diff_fields": diff_fields,
                "previous_snapshot_id": (
                    previous.get("snapshot_id") if previous else None
                ),
            },
        )
