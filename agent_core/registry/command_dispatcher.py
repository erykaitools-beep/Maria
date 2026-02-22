"""
CommandDispatcher - Routes REPL commands to module handlers.

Replaces the if/elif chain in main.py.
"""

import logging
from typing import Dict, List, Optional, Callable, Tuple

from .module_registry import ModuleRegistry
from .base_module import CommandInfo

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """
    Dispatches REPL commands to registered module handlers.

    Built from ModuleRegistry after all modules are initialized.

    Usage:
        dispatcher = CommandDispatcher(registry)
        dispatcher.add_builtin("/help", lambda args: print_help())
        handled = dispatcher.dispatch("/homeostasis", ["start"])
    """

    def __init__(self, registry: ModuleRegistry):
        """
        Build command table from registry.

        Args:
            registry: Initialized ModuleRegistry
        """
        self._registry = registry
        self._commands: Dict[str, CommandInfo] = {}
        self._builtin_help: List[Tuple[str, List[str]]] = []

        self._build_command_table()

    def _build_command_table(self) -> None:
        """Collect commands from all registered modules."""
        for module in self._registry.get_all_modules():
            for cmd_info in module.get_commands():
                name = cmd_info.name.lower()
                if name in self._commands:
                    logger.warning(
                        f"Command conflict: {name} already registered, "
                        f"overwriting with {module.name}"
                    )
                self._commands[name] = cmd_info

    def add_builtin(
        self,
        name: str,
        handler: Callable,
        help_text: str = "",
    ) -> None:
        """
        Register a built-in command (not from a module).

        Used for /help, /exit.
        """
        cmd_info = CommandInfo(
            name=name,
            handler=handler,
            help_text=help_text,
            category="",
        )
        self._commands[name.lower()] = cmd_info

    def set_builtin_help(self, lines: List[Tuple[str, List[str]]]) -> None:
        """Set help lines for built-in commands (shown before module help)."""
        self._builtin_help = lines

    def dispatch(self, command: str, args: List[str]) -> bool:
        """
        Dispatch a command to its handler.

        Returns:
            True if command was handled, False if unknown
        """
        cmd_info = self._commands.get(command.lower())
        if cmd_info:
            try:
                cmd_info.handler(args)
            except Exception as e:
                print(f"[System] [ERROR] Command error: {e}")
            return True

        return False

    def get_all_help(self) -> List[Tuple[str, List[str]]]:
        """
        Get organized help text for all commands.

        Returns:
            List of (category, [help_lines]) tuples.
        """
        all_help = list(self._builtin_help)
        seen_categories = {cat for cat, _ in all_help}

        for module in self._registry.get_all_modules():
            for category, lines in module.get_help_lines():
                if category not in seen_categories:
                    all_help.append((category, lines))
                    seen_categories.add(category)

        return all_help

    def get_command_names(self) -> List[str]:
        """Get all registered command names."""
        return sorted(self._commands.keys())
