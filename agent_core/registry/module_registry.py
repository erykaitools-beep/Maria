"""
ModuleRegistry - Manages module lifecycle and discovery.

Handles:
- Module registration with try/except import safety
- Module initialization with SharedContext
- Module listing and status
- Cleanup on shutdown
"""

import logging
from typing import Dict, List, Optional, Callable

from .base_module import MariaModule
from .shared_context import SharedContext

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """
    Registry of all M.A.R.I.A. modules.

    Usage:
        registry = ModuleRegistry()
        registry.register(HomeostasisModule())
        registry.init_all(ctx)
        registry.cleanup_all()
    """

    def __init__(self):
        """Initialize empty registry."""
        self._modules: Dict[str, MariaModule] = {}
        self._load_order: List[str] = []
        self._failed: Dict[str, str] = {}

    def register(self, module: MariaModule) -> bool:
        """
        Register a module instance.

        Returns:
            True if registered successfully
        """
        name = module.name
        if name in self._modules:
            logger.warning(f"Module already registered: {name}")
            return False

        self._modules[name] = module
        self._load_order.append(name)
        return True

    def try_register(self, module_factory: Callable, module_name: str = "") -> bool:
        """
        Try to instantiate and register a module.

        Catches ImportError and other exceptions gracefully.

        Args:
            module_factory: Callable that returns a MariaModule instance
            module_name: Name for error reporting

        Returns:
            True if module was registered successfully
        """
        try:
            module = module_factory()
            self.register(module)
            return True
        except ImportError as e:
            display_name = module_name or "unknown"
            self._failed[display_name] = str(e)
            print(f"[{display_name}] [WARN] Not available: {e}")
            return False
        except Exception as e:
            display_name = module_name or "unknown"
            self._failed[display_name] = str(e)
            print(f"[{display_name}] [WARN] Registration failed: {e}")
            return False

    def init_all(self, ctx: SharedContext) -> None:
        """
        Initialize all registered modules with shared context.

        Modules that fail init() are removed from registry.
        """
        failed_names = []

        for name in list(self._load_order):
            module = self._modules.get(name)
            if not module:
                continue

            try:
                success = module.init(ctx)
                if success:
                    print(f"[{name}] [OK] Initialized")
                else:
                    print(f"[{name}] [WARN] Init returned False, disabling")
                    failed_names.append(name)
            except Exception as e:
                print(f"[{name}] [WARN] Init failed: {e}")
                failed_names.append(name)

        for name in failed_names:
            self._modules.pop(name, None)
            if name in self._load_order:
                self._load_order.remove(name)
            self._failed[name] = "init failed"

    def cleanup_all(self) -> None:
        """Cleanup all modules in reverse registration order."""
        for name in reversed(self._load_order):
            module = self._modules.get(name)
            if module:
                try:
                    module.cleanup()
                except Exception as e:
                    logger.warning(f"[{name}] Cleanup error: {e}")

    def get_module(self, name: str) -> Optional[MariaModule]:
        """Get a module by name."""
        return self._modules.get(name)

    def get_all_modules(self) -> List[MariaModule]:
        """Get all active modules in registration order."""
        return [self._modules[n] for n in self._load_order if n in self._modules]

    def is_available(self, name: str) -> bool:
        """Check if a module is registered and active."""
        return name in self._modules

    def get_status(self) -> Dict[str, str]:
        """Get status of all known modules."""
        status = {}
        for name in self._load_order:
            if name in self._modules:
                status[name] = "active"
        for name, error in self._failed.items():
            status[name] = f"failed: {error}"
        return status
