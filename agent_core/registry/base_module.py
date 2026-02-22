"""
MariaModule - Base class for REPL-integrated modules.

Each module provides:
- A name and description
- Commands it handles
- Help text
- init/cleanup lifecycle
"""

from typing import List, Tuple, Callable


class CommandInfo:
    """Describes a single REPL command."""

    __slots__ = ('name', 'handler', 'help_text', 'category')

    def __init__(
        self,
        name: str,
        handler: Callable,
        help_text: str,
        category: str = "",
    ):
        """
        Args:
            name: Command name including slash, e.g. "/homeostasis"
            handler: Function(args: List[str]) -> None
            help_text: One or more lines of help text
            category: Help category heading, e.g. "[HEART] HOMEOSTASIS"
        """
        self.name = name
        self.handler = handler
        self.help_text = help_text
        self.category = category


class MariaModule:
    """
    Base class for M.A.R.I.A. REPL modules.

    Subclass and override methods as needed.
    Not all methods need to be overridden.
    """

    name: str = "unnamed"
    description: str = ""

    def init(self, ctx) -> bool:
        """
        Initialize the module with shared context.

        Args:
            ctx: SharedContext instance

        Returns:
            True if initialization succeeded, False to disable module
        """
        self.ctx = ctx
        return True

    def get_commands(self) -> List[CommandInfo]:
        """Return list of commands this module provides."""
        return []

    def get_help_lines(self) -> List[Tuple[str, List[str]]]:
        """
        Return help text organized by category.

        Returns:
            List of (category_header, [help_lines]) tuples.
        """
        commands = self.get_commands()
        if not commands:
            return []

        categories = {}
        for cmd in commands:
            cat = cmd.category or f"[{self.name.upper()}]"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(cmd.help_text)

        return list(categories.items())

    def cleanup(self) -> None:
        """Cleanup when module is being unloaded or system exits."""
        pass
