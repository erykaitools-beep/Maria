"""
FileManager - Safe file operations (second "digital hand").

Creates notes, organizes files, reads content.
All operations are bounded to safe directories (input/, docs/, meta_data/).
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Allowed directories for write operations (safety boundary)
_SAFE_WRITE_DIRS = {"input", "docs", "meta_data"}
_SAFE_READ_DIRS = {"input", "docs", "meta_data", "memory", "logs"}


class FileManager:
    """Safe file operations for Maria."""

    def __init__(self, base_dir: Optional[Path] = None):
        self._base = base_dir or Path(".")

    # -- Tool handlers (for TaskExecutor) --

    def write_note(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a text note in input/ or docs/.

        Args: {"title": str, "content": str, "directory": str (default "input")}
        Returns: {"success": bool, "path": str, "size": int}
        """
        title = args.get("title", "")
        content = args.get("content", "")
        directory = args.get("directory", "input")

        if not title:
            return {"success": False, "error": "brak tytulu"}
        if not content:
            return {"success": False, "error": "brak tresci"}
        if directory not in _SAFE_WRITE_DIRS:
            return {"success": False, "error": f"niedozwolony katalog: {directory}"}

        try:
            # Sanitize filename
            safe_name = self._sanitize_filename(title)
            dir_path = self._base / directory
            dir_path.mkdir(parents=True, exist_ok=True)
            file_path = dir_path / f"{safe_name}.txt"

            # Don't overwrite existing files
            if file_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                file_path = dir_path / f"{safe_name}_{timestamp}.txt"

            # Write with header
            header = (
                f"# {title}\n"
                f"# Utworzono przez Marie: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"# Zrodlo: auto-generated\n\n"
            )
            file_path.write_text(header + content, encoding="utf-8")

            return {
                "success": True,
                "ok": True,
                "path": str(file_path),
                "size": file_path.stat().st_size,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def read_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read a file content (bounded to safe dirs).

        Args: {"path": str, "max_chars": int (default 5000)}
        Returns: {"success": bool, "content": str, "size": int}
        """
        path_str = args.get("path", "")
        max_chars = args.get("max_chars", 5000)

        if not path_str:
            return {"success": False, "error": "brak sciezki"}

        file_path = Path(path_str)
        if not self._is_safe_read(file_path):
            return {"success": False, "error": f"niedozwolona sciezka: {path_str}"}

        try:
            if not file_path.exists():
                return {"success": False, "error": f"plik nie istnieje: {path_str}"}

            content = file_path.read_text(encoding="utf-8")[:max_chars]
            return {
                "success": True,
                "ok": True,
                "content": content,
                "size": file_path.stat().st_size,
                "path": str(file_path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List files in a directory.

        Args: {"directory": str, "pattern": str (default "*.txt")}
        Returns: {"success": bool, "files": list, "count": int}
        """
        directory = args.get("directory", "input")
        pattern = args.get("pattern", "*.txt")

        dir_path = self._base / directory
        if not dir_path.exists():
            return {"success": False, "error": f"katalog nie istnieje: {directory}"}

        try:
            files = []
            for f in sorted(dir_path.glob(pattern)):
                if f.is_file():
                    files.append({
                        "name": f.name,
                        "size": f.stat().st_size,
                        "modified": f.stat().st_mtime,
                    })

            return {
                "success": True,
                "ok": True,
                "files": files,
                "count": len(files),
                "directory": directory,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -- Internal --

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Convert title to safe filename."""
        # Replace unsafe chars
        safe = name.lower().strip()
        for ch in " /\\:*?\"<>|()[]{}!@#$%^&+=":
            safe = safe.replace(ch, "_")
        # Remove multiple underscores
        while "__" in safe:
            safe = safe.replace("__", "_")
        safe = safe.strip("_")
        # Limit length
        return safe[:80] if safe else "notatka"

    def _is_safe_read(self, path: Path) -> bool:
        """Check if path is within allowed read directories."""
        try:
            resolved = path.resolve()
            base_resolved = self._base.resolve()
            # Must be under base dir
            if not str(resolved).startswith(str(base_resolved)):
                return False
            # First directory component must be in safe list
            rel = resolved.relative_to(base_resolved)
            first_part = rel.parts[0] if rel.parts else ""
            return first_part in _SAFE_READ_DIRS
        except Exception:
            return False
