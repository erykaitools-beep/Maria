"""Explicit runtime choices, preserving existing installs by default."""
import os


def lean_runtime() -> bool:
    profile = os.environ.get("MARIA_RUNTIME_PROFILE", "standard").strip().lower()
    if profile not in {"standard", "lean"}:
        raise ValueError("MARIA_RUNTIME_PROFILE must be standard or lean")
    return profile == "lean"


def conductor_integration_enabled() -> bool:
    override = os.environ.get("MARIA_CONDUCTOR_INTEGRATION")
    if override is None:
        return not lean_runtime()
    value = override.strip().lower()
    if value not in {"0", "1", "false", "true", "off", "on"}:
        raise ValueError("MARIA_CONDUCTOR_INTEGRATION must be 0 or 1")
    return value in {"1", "true", "on"}


def model_keep_alive(kind: str, default: str) -> str:
    override = os.environ.get(f"MARIA_{kind.upper()}_KEEP_ALIVE")
    if override is not None:
        return override
    if lean_runtime():
        return {"embedding": "60s", "vision": "60s", "role": "5m"}.get(kind, default)
    return default


def background_reasoning_enabled() -> bool:
    """Whether autonomous reasoning/model warm-up is admitted (legacy: on)."""
    value = os.environ.get("MARIA_BACKGROUND_REASONING", "1").strip().lower()
    if value not in {"0", "1", "false", "true", "off", "on"}:
        raise ValueError("MARIA_BACKGROUND_REASONING must be 0 or 1")
    return value in {"1", "true", "on"}


def telegram_integration_enabled() -> bool:
    """Whether Telegram initialization, polling and notifications are admitted."""
    value = os.environ.get("MARIA_TELEGRAM_INTEGRATION", "1").strip().lower()
    if value not in {"0", "1", "false", "true", "off", "on"}:
        raise ValueError("MARIA_TELEGRAM_INTEGRATION must be 0 or 1")
    return value in {"1", "true", "on"}
