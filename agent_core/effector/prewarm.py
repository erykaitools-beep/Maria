"""
Pre-warm Ollama models before OpenClaw agent calls.

OpenClaw agent tools spin up qwen2.5:3b via Ollama. When the model is
cold, loading 3GB from disk eats 15-30s of the agent's own timeout,
often causing the tool call to abort before generating a result.

We trigger Ollama's load-and-keep-alive pathway via a minimal
/api/generate request with keep_alive set to a longer window, so the
subsequent OpenClaw subprocess hits a warm model.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional


logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_KEEP_ALIVE = "30m"
DEFAULT_TIMEOUT_S = 30.0


def warm_ollama_model(
    model: str,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    keep_alive: str = DEFAULT_KEEP_ALIVE,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> bool:
    """
    Ensure `model` is loaded in Ollama and pinned for `keep_alive`.

    Uses an empty /api/generate request — Ollama treats that as
    load-only (returns immediately once weights are ready).

    Returns True if the request succeeded, False on any error.
    """
    payload = json.dumps({
        "model": model,
        "prompt": "",
        "keep_alive": keep_alive,
    }).encode("utf-8")

    req = urllib.request.Request(
        url=f"{ollama_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            resp.read()
        logger.info(
            "[Prewarm] Ollama model '%s' warmed (keep_alive=%s)",
            model, keep_alive,
        )
        return True
    except urllib.error.URLError as e:
        logger.warning("[Prewarm] Failed to warm '%s': %s", model, e)
        return False
    except Exception as e:
        logger.warning("[Prewarm] Unexpected error warming '%s': %s", model, e)
        return False
