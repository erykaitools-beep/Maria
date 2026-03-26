"""Shared LLM utilities for Creative Module Phase 2 engines.

JSON parsing, prompt building, and response extraction.
"""

import json
import logging
import re
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract JSON from LLM response (handles markdown wrapping).

    Handles:
    - Clean JSON
    - Markdown code fences (```json ... ```)
    - JSON embedded in text
    """
    if not text:
        return None

    text = text.strip()

    # Try markdown code fences
    md_match = re.search(r'```(?:json)?\s*(.+?)\s*```', text, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try direct JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try finding first { ... } block
    brace_match = re.search(r'\{.+\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    return None


def safe_llm_call(
    llm_fn: Optional[Callable[[str], str]],
    prompt: str,
    context_label: str = "creative",
) -> Optional[str]:
    """Call LLM function with error handling.

    Returns None on any failure (caller should fall back to rule-based).
    """
    if llm_fn is None:
        return None
    try:
        response = llm_fn(prompt)
        if response and response.strip():
            return response.strip()
        logger.warning(f"[{context_label}] LLM returned empty response")
        return None
    except Exception as e:
        logger.warning(f"[{context_label}] LLM call failed: {e}")
        return None
