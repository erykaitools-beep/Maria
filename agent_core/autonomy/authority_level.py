"""
Authority Level Model for Effector Safety Envelope (Phase 5).

5-level staged authority controlling how Maria can use OpenClaw effector:
- OBSERVE: can see tools, never invoke
- SUGGEST: proposes tool use, operator sees notification, no execution
- CONFIRM: proposes, operator approves via Telegram, then executes
- BOUNDED: autonomous for non-dangerous tools, confirm for dangerous
- UNRESTRICTED: full autonomous (stub, not activated in Phase 5)

Default: OBSERVE (backward compatible - no change in behavior).
Operator sets level via Telegram /authority command.

Persistence: meta_data/authority_config.json (singleton).

ADR-026: Effector Safety Envelope.
"""

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Default config path
DEFAULT_CONFIG_PATH = Path("meta_data/authority_config.json")


class AuthorityLevel(Enum):
    """Staged effector authority levels."""
    OBSERVE = "observe"           # Can see tools, never invoke
    SUGGEST = "suggest"           # Proposes, operator sees notification, no exec
    CONFIRM = "confirm"           # Proposes, operator approves, then exec
    BOUNDED = "bounded"           # Auto-exec safe tools, confirm dangerous
    UNRESTRICTED = "unrestricted" # Full autonomous (not activated in Phase 5)


# Ordered levels for comparison (lower index = less authority)
_LEVEL_ORDER = [
    AuthorityLevel.OBSERVE,
    AuthorityLevel.SUGGEST,
    AuthorityLevel.CONFIRM,
    AuthorityLevel.BOUNDED,
    AuthorityLevel.UNRESTRICTED,
]


def level_index(level: AuthorityLevel) -> int:
    """Get numeric index for level comparison."""
    return _LEVEL_ORDER.index(level)


# Default per-tool rate limits (invocations per hour)
DEFAULT_TOOL_RATE_LIMITS: Dict[str, int] = {
    # Non-dangerous (safe)
    "web_fetch": 20,
    "web_search": 20,
    "read": 30,
    "cron": 2,
    # Dangerous
    "exec": 5,
    "write": 5,
    "message": 5,
}

# Default failure management
DEFAULT_FAILURE_COOLDOWN_SEC = 300.0    # 5 minutes
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class AuthorityConfig:
    """
    Configuration for effector authority.

    Persisted to meta_data/authority_config.json.
    Thread-safe access via AuthorityManager.
    """
    level: str = AuthorityLevel.OBSERVE.value
    tool_rate_limits: Dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_TOOL_RATE_LIMITS)
    )
    failure_cooldown_sec: float = DEFAULT_FAILURE_COOLDOWN_SEC
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES
    updated_at: float = 0.0

    def get_level(self) -> AuthorityLevel:
        """Parse level string to enum."""
        try:
            return AuthorityLevel(self.level)
        except ValueError:
            logger.warning("Unknown authority level '%s', defaulting to OBSERVE", self.level)
            return AuthorityLevel.OBSERVE

    def to_dict(self) -> Dict:
        """Serialize to dict for JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "AuthorityConfig":
        """Deserialize from dict."""
        return cls(
            level=data.get("level", AuthorityLevel.OBSERVE.value),
            tool_rate_limits=data.get("tool_rate_limits", dict(DEFAULT_TOOL_RATE_LIMITS)),
            failure_cooldown_sec=data.get("failure_cooldown_sec", DEFAULT_FAILURE_COOLDOWN_SEC),
            max_consecutive_failures=data.get("max_consecutive_failures", DEFAULT_MAX_CONSECUTIVE_FAILURES),
            updated_at=data.get("updated_at", 0.0),
        )


class AuthorityManager:
    """
    Thread-safe manager for authority configuration.

    Handles loading, saving, and level changes.
    """

    # UNRESTRICTED is not allowed in Phase 5
    MAX_ALLOWED_LEVEL = AuthorityLevel.BOUNDED

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._lock = threading.Lock()
        self._config = self._load()
        self._on_downgrade_fn = None  # Callback for downgrade (e.g. reject pending approvals)

    def set_on_downgrade(self, fn) -> None:
        """Set callback invoked on authority downgrade. fn(old_level, new_level)."""
        self._on_downgrade_fn = fn

    def _load(self) -> AuthorityConfig:
        """Load config from JSON file, or return defaults."""
        try:
            if self._config_path.exists():
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                config = AuthorityConfig.from_dict(data)
                # Validate loaded level against MAX_ALLOWED_LEVEL
                loaded_level = config.get_level()
                if level_index(loaded_level) > level_index(self.MAX_ALLOWED_LEVEL):
                    logger.warning(
                        "Loaded authority %s exceeds max %s, clamping",
                        loaded_level.value, self.MAX_ALLOWED_LEVEL.value,
                    )
                    config.level = self.MAX_ALLOWED_LEVEL.value
                logger.info("Authority config loaded: level=%s", config.level)
                return config
        except Exception as e:
            logger.warning("Failed to load authority config: %s", e)
        return AuthorityConfig()

    def _save(self) -> None:
        """Persist current config to JSON file."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                json.dumps(self._config.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save authority config: %s", e)

    def get_level(self) -> AuthorityLevel:
        """Get current authority level (thread-safe)."""
        with self._lock:
            return self._config.get_level()

    def get_config(self) -> AuthorityConfig:
        """Get current config snapshot (thread-safe)."""
        with self._lock:
            return AuthorityConfig.from_dict(self._config.to_dict())

    def set_level(self, level: AuthorityLevel) -> bool:
        """
        Change authority level.

        Args:
            level: New authority level

        Returns:
            True if changed, False if blocked (e.g. UNRESTRICTED)
        """
        if level == AuthorityLevel.UNRESTRICTED:
            logger.warning(
                "UNRESTRICTED authority not available in Phase 5. "
                "Max allowed: %s", self.MAX_ALLOWED_LEVEL.value
            )
            return False

        with self._lock:
            import time
            old = self._config.level
            old_level_enum = self._config.get_level()
            self._config.level = level.value
            self._config.updated_at = time.time()
            self._save()
            logger.info("Authority level changed: %s -> %s", old, level.value)

        # On downgrade: notify callback (e.g. reject pending approvals)
        if level_index(level) < level_index(old_level_enum) and self._on_downgrade_fn:
            try:
                self._on_downgrade_fn(old_level_enum, level)
            except Exception as e:
                logger.warning("Downgrade callback error: %s", e)

        return True

    def get_tool_rate_limit(self, tool_name: str) -> int:
        """Get rate limit for a specific tool."""
        with self._lock:
            return self._config.tool_rate_limits.get(tool_name, 5)

    def get_status(self) -> Dict:
        """Get status dict for REPL/Telegram/Web UI."""
        with self._lock:
            return {
                "authority_level": self._config.level,
                "tool_rate_limits": dict(self._config.tool_rate_limits),
                "failure_cooldown_sec": self._config.failure_cooldown_sec,
                "max_consecutive_failures": self._config.max_consecutive_failures,
                "updated_at": self._config.updated_at,
            }
