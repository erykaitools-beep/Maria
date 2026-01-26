"""
Operator Controls - Safe commands for operator dashboard

Provides safe operator interface with reasoning-required commands.
All actions logged, validated by homeostasis before execution.

Spec reference: homeostasis_spec.md section 6.2 (lines 820-875)
"""

import time
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass

if TYPE_CHECKING:
    from ..homeostasis.core import HomeostasisCore
    from ..homeostasis.state_model import Mode


class OperatorCommandType(Enum):
    """Types of operator commands."""
    FORCE_MODE = "force_mode"
    TRIGGER_SNAPSHOT = "trigger_snapshot"
    VIEW_AUDIT = "view_audit"
    URGENT_SIGNAL = "urgent_signal"
    GRACEFUL_SHUTDOWN = "graceful_shutdown"


@dataclass
class OperatorCommand:
    """
    Operator command with required reasoning.

    Spec: lines 849-865 - all operator actions require reasoning
    """
    command_type: OperatorCommandType
    reasoning: str
    parameters: Dict[str, Any]
    timestamp: float
    operator_id: str = "default"


@dataclass
class CommandResult:
    """Result of operator command execution."""
    success: bool
    message: str
    command_type: OperatorCommandType
    timestamp: float
    details: Optional[Dict[str, Any]] = None


class OperatorControls:
    """
    Safe operator interface for homeostasis.

    Spec: lines 868-875 - Safety rules:
    1. Cannot directly modify homeostasis code/config
    2. Cannot force mode change if system CRITICAL
    3. Cannot delete memories or reset agent
    4. Can only SUGGEST, then homeostasis decides
    5. Every action logged and timestamped
    6. Operator actions visible in audit trail
    """

    def __init__(self, homeostasis_core: Optional["HomeostasisCore"] = None):
        """
        Initialize operator controls.

        Args:
            homeostasis_core: Reference to homeostasis core
        """
        self._core = homeostasis_core
        self._command_history: List[Dict[str, Any]] = []
        self._max_history = 1000

    def set_core(self, core: "HomeostasisCore") -> None:
        """Set homeostasis core reference."""
        self._core = core

    def force_mode(
        self,
        target_mode: str,
        duration_hours: float,
        reasoning: str,
        operator_id: str = "default"
    ) -> CommandResult:
        """
        Request forced mode change.

        Spec: lines 849-851 - Force mode with reasoning
        - Homeostasis will accept if system not critical
        - Cannot force if system in CRITICAL state

        Args:
            target_mode: Target mode name ('active', 'reduced', 'sleep', 'survival')
            duration_hours: How long to maintain forced mode
            reasoning: Why operator wants this mode
            operator_id: Operator identifier

        Returns:
            CommandResult with success/failure
        """
        command = OperatorCommand(
            command_type=OperatorCommandType.FORCE_MODE,
            reasoning=reasoning,
            parameters={
                "target_mode": target_mode,
                "duration_hours": duration_hours,
            },
            timestamp=time.time(),
            operator_id=operator_id,
        )

        # Validate reasoning provided
        if not reasoning or len(reasoning.strip()) < 10:
            return self._reject_command(
                command,
                "Reasoning required (minimum 10 characters)"
            )

        if not self._core:
            return self._reject_command(command, "Homeostasis core not available")

        # Check if system is critical - cannot force mode if critical
        if self._core.state.has_critical_alert():
            return self._reject_command(
                command,
                "Cannot force mode change: system in CRITICAL state"
            )

        # Validate target mode
        valid_modes = ["active", "reduced", "sleep", "survival"]
        if target_mode.lower() not in valid_modes:
            return self._reject_command(
                command,
                f"Invalid mode '{target_mode}'. Valid: {valid_modes}"
            )

        # Request mode from homeostasis (homeostasis decides)
        try:
            # Import here to avoid circular imports
            from ..homeostasis.state_model import Mode
            target = Mode(target_mode.lower())

            # Set operator override with expiration
            expiration = time.time() + (duration_hours * 3600)
            self._core.set_operator_mode_override(target, expiration, reasoning)

            result = CommandResult(
                success=True,
                message=f"Mode override accepted: {target_mode} for {duration_hours}h",
                command_type=OperatorCommandType.FORCE_MODE,
                timestamp=time.time(),
                details={
                    "target_mode": target_mode,
                    "duration_hours": duration_hours,
                    "expiration": expiration,
                },
            )

            self._log_command(command, result)
            return result

        except Exception as e:
            return self._reject_command(command, f"Mode override failed: {e}")

    def trigger_snapshot(
        self,
        reasoning: str,
        operator_id: str = "default"
    ) -> CommandResult:
        """
        Request system snapshot.

        Spec: lines 853-854 - Trigger snapshot with reasoning
        - Homeostasis will prioritize if not in REDUCED/SLEEP

        Args:
            reasoning: Why operator wants snapshot
            operator_id: Operator identifier

        Returns:
            CommandResult with success/failure
        """
        command = OperatorCommand(
            command_type=OperatorCommandType.TRIGGER_SNAPSHOT,
            reasoning=reasoning,
            parameters={},
            timestamp=time.time(),
            operator_id=operator_id,
        )

        if not reasoning or len(reasoning.strip()) < 10:
            return self._reject_command(
                command,
                "Reasoning required (minimum 10 characters)"
            )

        if not self._core:
            return self._reject_command(command, "Homeostasis core not available")

        # Check if in REDUCED/SLEEP - may delay snapshot
        from ..homeostasis.state_model import Mode
        current_mode = self._core.state.mode

        if current_mode in (Mode.REDUCED, Mode.SLEEP):
            # Still allow, but warn
            priority = "low"
            message = f"Snapshot queued (system in {current_mode.value} mode)"
        else:
            priority = "high"
            message = "Snapshot triggered"

        try:
            # Request snapshot from core
            snapshot_id = self._core.request_snapshot(
                reason=f"Operator request: {reasoning}",
                priority=priority,
            )

            result = CommandResult(
                success=True,
                message=message,
                command_type=OperatorCommandType.TRIGGER_SNAPSHOT,
                timestamp=time.time(),
                details={
                    "snapshot_id": snapshot_id,
                    "priority": priority,
                    "current_mode": current_mode.value,
                },
            )

            self._log_command(command, result)
            return result

        except Exception as e:
            return self._reject_command(command, f"Snapshot failed: {e}")

    def view_audit_log(
        self,
        limit: int = 100,
        operator_id: str = "default"
    ) -> CommandResult:
        """
        View audit log entries.

        Spec: lines 856-857 - Read-only, for operator understanding

        Args:
            limit: Maximum entries to return
            operator_id: Operator identifier

        Returns:
            CommandResult with audit entries in details
        """
        command = OperatorCommand(
            command_type=OperatorCommandType.VIEW_AUDIT,
            reasoning="Audit log view request",
            parameters={"limit": limit},
            timestamp=time.time(),
            operator_id=operator_id,
        )

        if not self._core:
            return self._reject_command(command, "Homeostasis core not available")

        try:
            entries = self._core.get_audit_log(limit)

            result = CommandResult(
                success=True,
                message=f"Retrieved {len(entries)} audit entries",
                command_type=OperatorCommandType.VIEW_AUDIT,
                timestamp=time.time(),
                details={"entries": entries},
            )

            # Note: Audit views are logged but don't need reasoning
            self._log_command(command, result)
            return result

        except Exception as e:
            return self._reject_command(command, f"Audit retrieval failed: {e}")

    def send_urgent_signal(
        self,
        signal_type: str,
        reasoning: str,
        operator_id: str = "default"
    ) -> CommandResult:
        """
        Send urgent signal to meta-controller.

        Spec: lines 859-861 - Only if homeostasis REFUSES critical fix
        - Last resort, logged

        Args:
            signal_type: Type of urgent signal
            reasoning: Why operator is sending urgent signal
            operator_id: Operator identifier

        Returns:
            CommandResult with success/failure
        """
        command = OperatorCommand(
            command_type=OperatorCommandType.URGENT_SIGNAL,
            reasoning=reasoning,
            parameters={"signal_type": signal_type},
            timestamp=time.time(),
            operator_id=operator_id,
        )

        # Urgent signals require substantial reasoning
        if not reasoning or len(reasoning.strip()) < 20:
            return self._reject_command(
                command,
                "Urgent signals require detailed reasoning (minimum 20 characters)"
            )

        if not self._core:
            return self._reject_command(command, "Homeostasis core not available")

        try:
            # Send to meta-controller via event bus
            self._core.event_bus.emit(
                "operator.urgent_signal",
                {
                    "signal_type": signal_type,
                    "reasoning": reasoning,
                    "operator_id": operator_id,
                    "timestamp": time.time(),
                }
            )

            result = CommandResult(
                success=True,
                message=f"Urgent signal '{signal_type}' sent to meta-controller",
                command_type=OperatorCommandType.URGENT_SIGNAL,
                timestamp=time.time(),
                details={"signal_type": signal_type},
            )

            self._log_command(command, result)
            return result

        except Exception as e:
            return self._reject_command(command, f"Urgent signal failed: {e}")

    def graceful_shutdown(
        self,
        reasoning: str,
        operator_id: str = "default"
    ) -> CommandResult:
        """
        Request graceful system shutdown.

        Spec: lines 863-864 - POWER OFF
        - Homeostasis initiates SURVIVAL mode, then shutdown

        Args:
            reasoning: Why operator wants shutdown
            operator_id: Operator identifier

        Returns:
            CommandResult with success/failure
        """
        command = OperatorCommand(
            command_type=OperatorCommandType.GRACEFUL_SHUTDOWN,
            reasoning=reasoning,
            parameters={},
            timestamp=time.time(),
            operator_id=operator_id,
        )

        # Shutdown requires substantial reasoning
        if not reasoning or len(reasoning.strip()) < 20:
            return self._reject_command(
                command,
                "Shutdown requires detailed reasoning (minimum 20 characters)"
            )

        if not self._core:
            return self._reject_command(command, "Homeostasis core not available")

        try:
            # Initiate graceful shutdown via homeostasis
            self._core.initiate_shutdown(
                reason=f"Operator request: {reasoning}",
                operator_id=operator_id,
            )

            result = CommandResult(
                success=True,
                message="Graceful shutdown initiated (SURVIVAL mode -> shutdown)",
                command_type=OperatorCommandType.GRACEFUL_SHUTDOWN,
                timestamp=time.time(),
                details={
                    "shutdown_sequence": [
                        "1. Enter SURVIVAL mode",
                        "2. Flush memories to disk",
                        "3. Create final snapshot",
                        "4. Stop all modules",
                        "5. Shutdown",
                    ]
                },
            )

            self._log_command(command, result)
            return result

        except Exception as e:
            return self._reject_command(command, f"Shutdown initiation failed: {e}")

    def get_command_history(
        self,
        limit: int = 50,
        command_type: Optional[OperatorCommandType] = None
    ) -> List[Dict[str, Any]]:
        """
        Get operator command history.

        Args:
            limit: Maximum entries to return
            command_type: Filter by command type (optional)

        Returns:
            List of command records
        """
        history = self._command_history

        if command_type:
            history = [h for h in history if h["command_type"] == command_type.value]

        return history[-limit:]

    def _reject_command(
        self,
        command: OperatorCommand,
        reason: str
    ) -> CommandResult:
        """
        Reject a command and log it.

        Args:
            command: The rejected command
            reason: Why it was rejected

        Returns:
            CommandResult with success=False
        """
        result = CommandResult(
            success=False,
            message=f"Command rejected: {reason}",
            command_type=command.command_type,
            timestamp=time.time(),
        )

        self._log_command(command, result)
        return result

    def _log_command(
        self,
        command: OperatorCommand,
        result: CommandResult
    ) -> None:
        """
        Log command to history and audit.

        Spec: line 873 - Every action logged and timestamped
        """
        record = {
            "command_type": command.command_type.value,
            "reasoning": command.reasoning,
            "parameters": command.parameters,
            "operator_id": command.operator_id,
            "command_timestamp": command.timestamp,
            "result_success": result.success,
            "result_message": result.message,
            "result_timestamp": result.timestamp,
        }

        self._command_history.append(record)

        # Trim history if too long
        if len(self._command_history) > self._max_history:
            self._command_history = self._command_history[-self._max_history:]

        # Also log to homeostasis audit if available
        if self._core:
            self._core.log_audit(
                event="operator_command",
                details=record,
            )

