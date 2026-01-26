"""
Module Executor - Signal dispatch between modules

Provides standardized communication between modules:
- pause/resume signals
- resource reduction requests
- health checks
- shutdown coordination

Spec reference: homeostasis_spec.md lines 1729-1753
"""

import time
import logging
from typing import Dict, Any, Optional, Callable, List

logger = logging.getLogger(__name__)


class ModuleExecutor:
    """
    Dispatches signals between homeostasis and other modules.

    Every module MUST support these signals (spec lines 1731-1753):
    - pause: Stop work, save state
    - resume: Resume from saved state
    - reduce_resources: Operate with fewer resources
    - health_check: Report current status
    - shutdown: Prepare for shutdown
    """

    # Standard signal types from spec
    SIGNAL_TYPES = [
        "pause",
        "resume",
        "reduce_resources",
        "health_check",
        "shutdown_prepare",
        "minimize",
        "readonly",
        "checkpoint",
        "consolidate_episodic",
        "semantic_consistency_check",
        "interrupt_goal_refinement",
        "reduce_batch_size",
    ]

    def __init__(self):
        """Initialize module executor."""
        self._modules: Dict[str, Any] = {}
        self._signal_handlers: Dict[str, Dict[str, Callable]] = {}
        self._signal_history: List[Dict[str, Any]] = []

    def register_module(
        self,
        module_name: str,
        module: Any,
        signal_handlers: Dict[str, Callable] = None,
    ) -> None:
        """
        Register a module for signal dispatch.

        Args:
            module_name: Unique module identifier
            module: Module instance
            signal_handlers: Optional dict mapping signal_type -> handler function
        """
        self._modules[module_name] = module

        if signal_handlers:
            self._signal_handlers[module_name] = signal_handlers

        logger.debug(f"Registered module: {module_name}")

    def unregister_module(self, module_name: str) -> None:
        """Unregister a module."""
        self._modules.pop(module_name, None)
        self._signal_handlers.pop(module_name, None)

    def signal_module(
        self,
        module_name: str,
        signal_type: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Send signal to a module.

        Spec: homeostasis_spec.md lines 1731-1753

        Standard signals:
        - pause: {"paused": true, "saved_state": {...}}
        - resume: {"resumed": true}
        - reduce_resources: {"complied": true, "freed_mb": X}
        - health_check: {"healthy": true, "errors": 0, "latency_ms": X}
        - shutdown: {"ready_shutdown": true}

        Args:
            module_name: Target module (or "all" for broadcast)
            signal_type: Type of signal
            **kwargs: Additional signal parameters

        Returns:
            Response dictionary from module
        """
        # Record signal
        self._signal_history.append({
            "timestamp": time.time(),
            "module": module_name,
            "signal": signal_type,
            "kwargs": kwargs,
        })

        # Broadcast to all modules
        if module_name == "all":
            return self._broadcast_signal(signal_type, **kwargs)

        # Get module
        module = self._modules.get(module_name)
        if not module:
            logger.warning(f"Unknown module: {module_name}")
            return {"error": f"Unknown module: {module_name}"}

        # Try custom handler first
        handlers = self._signal_handlers.get(module_name, {})
        if signal_type in handlers:
            try:
                return handlers[signal_type](**kwargs)
            except Exception as e:
                logger.error(f"Signal handler error: {e}")
                return {"error": str(e)}

        # Try module method
        method = getattr(module, signal_type, None)
        if method and callable(method):
            try:
                return method(**kwargs) or {"success": True}
            except Exception as e:
                logger.error(f"Module method error: {e}")
                return {"error": str(e)}

        # Fallback for common signals
        return self._default_signal_response(module_name, signal_type)

    def _broadcast_signal(
        self,
        signal_type: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Broadcast signal to all registered modules."""
        results = {}

        for name in self._modules:
            results[name] = self.signal_module(name, signal_type, **kwargs)

        return {
            "broadcast": True,
            "results": results,
        }

    def _default_signal_response(
        self,
        module_name: str,
        signal_type: str,
    ) -> Dict[str, Any]:
        """Default response for unimplemented signals."""
        if signal_type == "pause":
            return {"paused": True, "saved_state": {}}
        elif signal_type == "resume":
            return {"resumed": True}
        elif signal_type == "health_check":
            return {"healthy": True, "errors": 0}
        elif signal_type == "shutdown_prepare":
            return {"ready_shutdown": True}
        else:
            logger.debug(f"No handler for {module_name}.{signal_type}")
            return {"acknowledged": True}

    def get_signal_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent signal history."""
        return self._signal_history[-limit:]

    def get_registered_modules(self) -> List[str]:
        """Get list of registered module names."""
        return list(self._modules.keys())

    def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """
        Run health check on all modules.

        Returns:
            Dictionary mapping module name to health status
        """
        return self._broadcast_signal("health_check")["results"]

    def pause_all(self) -> None:
        """Pause all modules."""
        self._broadcast_signal("pause")

    def resume_all(self) -> None:
        """Resume all modules."""
        self._broadcast_signal("resume")

    def shutdown_all(self, grace_period_seconds: int = 30) -> Dict[str, Any]:
        """
        Initiate shutdown for all modules.

        Args:
            grace_period_seconds: Time available for cleanup

        Returns:
            Shutdown status for each module
        """
        return self._broadcast_signal(
            "shutdown_prepare",
            grace_period_seconds=grace_period_seconds,
        )
