"""
Lightweight health checks for the effector stack.

Pre-flight checks before spending 30-180s on an OpenClaw subprocess:
- OpenClaw gateway process alive (pgrep)
- Ollama reachable (api/tags)
- Optional: specific model already loaded (api/ps)
"""

from __future__ import annotations

import json
import logging
import subprocess
import urllib.error
import urllib.request
from typing import Optional, Set


logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_CHECK_TIMEOUT_S = 3.0


def openclaw_gateway_alive() -> bool:
    """Return True iff openclaw-gateway process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "openclaw-gateway"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_CHECK_TIMEOUT_S,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("[HealthCheck] openclaw pgrep failed: %s", e)
        return False


def ollama_alive(ollama_url: str = DEFAULT_OLLAMA_URL) -> bool:
    """Return True iff Ollama API responds on /api/tags."""
    try:
        req = urllib.request.Request(f"{ollama_url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=DEFAULT_CHECK_TIMEOUT_S) as resp:
            return resp.status == 200
    except (urllib.error.URLError, Exception) as e:
        logger.warning("[HealthCheck] Ollama unreachable: %s", e)
        return False


def ollama_loaded_models(ollama_url: str = DEFAULT_OLLAMA_URL) -> Set[str]:
    """Return set of currently-loaded model names (from /api/ps)."""
    try:
        req = urllib.request.Request(f"{ollama_url.rstrip('/')}/api/ps")
        with urllib.request.urlopen(req, timeout=DEFAULT_CHECK_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
        return {m.get("name", "") for m in data.get("models", [])}
    except Exception as e:
        logger.debug("[HealthCheck] /api/ps failed: %s", e)
        return set()


def model_loaded(
    model: str, ollama_url: str = DEFAULT_OLLAMA_URL,
) -> bool:
    """Return True iff `model` is in Ollama's loaded-models list."""
    return model in ollama_loaded_models(ollama_url)
