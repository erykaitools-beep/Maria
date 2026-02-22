"""
M.A.R.I.A. Module Registry and Command Dispatcher.

Provides a plug-in system for REPL modules.
"""

from .base_module import MariaModule, CommandInfo
from .shared_context import SharedContext
from .module_registry import ModuleRegistry
from .command_dispatcher import CommandDispatcher

__all__ = [
    "MariaModule",
    "CommandInfo",
    "SharedContext",
    "ModuleRegistry",
    "CommandDispatcher",
]
