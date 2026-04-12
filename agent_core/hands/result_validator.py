"""
ResultValidator - Post-action verification.

Checks whether an action actually succeeded by examining the result
and optionally verifying side effects (file exists, content correct, etc.).
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ResultValidator:
    """Validates action results after execution."""

    def validate(self, tool_name: str, tool_args: Dict, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate action result. Returns validation dict.

        Returns:
            {"valid": bool, "reason": str, "checks": list}
        """
        checks = []

        # Basic: did the tool report success?
        tool_success = result.get("success", result.get("ok", False))
        checks.append({
            "check": "tool_reported_success",
            "passed": bool(tool_success),
        })

        # Tool-specific validation
        if tool_name == "file_write":
            file_check = self._validate_file_write(tool_args, result)
            checks.append(file_check)
        elif tool_name == "web_search":
            search_check = self._validate_web_search(result)
            checks.append(search_check)
        elif tool_name == "web_fetch":
            fetch_check = self._validate_web_fetch(result)
            checks.append(fetch_check)

        # Overall verdict
        all_passed = all(c["passed"] for c in checks)
        reason = "all checks passed" if all_passed else "; ".join(
            c.get("reason", c["check"]) for c in checks if not c["passed"]
        )

        return {
            "valid": all_passed,
            "reason": reason,
            "checks": checks,
        }

    def _validate_file_write(self, tool_args: Dict, result: Dict) -> Dict:
        """Verify file was actually created/written."""
        path = tool_args.get("path", "") or result.get("path", "")
        if not path:
            return {"check": "file_exists", "passed": False, "reason": "no path specified"}

        exists = Path(path).exists()
        if exists:
            size = Path(path).stat().st_size
            return {
                "check": "file_exists",
                "passed": True,
                "detail": f"exists, {size} bytes",
            }
        return {"check": "file_exists", "passed": False, "reason": f"file not found: {path}"}

    def _validate_web_search(self, result: Dict) -> Dict:
        """Verify web search returned results."""
        results_count = len(result.get("results", []))
        if results_count > 0:
            return {
                "check": "search_has_results",
                "passed": True,
                "detail": f"{results_count} results",
            }
        return {
            "check": "search_has_results",
            "passed": False,
            "reason": "no search results returned",
        }

    def _validate_web_fetch(self, result: Dict) -> Dict:
        """Verify web fetch returned content."""
        content = result.get("content", "")
        if content and len(content) > 50:
            return {
                "check": "fetch_has_content",
                "passed": True,
                "detail": f"{len(content)} chars",
            }
        return {
            "check": "fetch_has_content",
            "passed": False,
            "reason": "no content or too short",
        }
