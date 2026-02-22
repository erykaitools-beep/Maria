"""
SharedContext - Dependency container for REPL modules.

Bundles shared objects that modules need access to.
Created once during init_brain() and passed to all modules.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SharedContext:
    """
    Shared dependencies for all REPL modules.

    Created by main.py during initialization.
    Passed to each module's init() method.
    """
    # Core objects (set during init_brain)
    brain: Any = None
    brain_loop: Any = None
    semantic_memory: Any = None
    episodic_memory: Any = None

    # Subsystems (set by modules during init)
    homeostasis_core: Any = None

    # REPL state
    last_result: Any = None

    # Configuration
    brain_model: str = "llama3.1:8b"

    def update(self, **kwargs) -> None:
        """Update context fields. Used after reload."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
