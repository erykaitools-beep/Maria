"""
ContextBuilder - Aggregates Maria's self-awareness for the system prompt.

Reads from:
- memory/knowledge_index.jsonl    (files to learn, statuses)
- memory/maria_longterm_memory.jsonl  (learned topics/tags)
- meta_data/code_self_model.json  (code stats from introspection)
- psutil                          (RAM, CPU)

Result is a compact string (~500 chars) cached for 60 seconds.
Used by OllamaBrain to answer questions like "what files do you have?"
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

# Safe psutil import
try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False


def _resolve_paths():
    """Get project paths from config, with fallback to relative paths."""
    try:
        from maria_core.sys.config import (
            KNOWLEDGE_INDEX,
            LONGTERM_MEMORY,
            BASE_DIR,
        )
        meta_data_dir = BASE_DIR / "meta_data"
        input_dir = BASE_DIR / "input"
        return {
            "knowledge_index": Path(KNOWLEDGE_INDEX),
            "longterm_memory": Path(LONGTERM_MEMORY),
            "code_self_model": meta_data_dir / "code_self_model.json",
            "input_dir": Path(input_dir),
        }
    except ImportError:
        # Fallback: resolve relative to this file (agent_core/awareness/)
        project_root = Path(__file__).resolve().parents[2]
        return {
            "knowledge_index": project_root / "memory" / "knowledge_index.jsonl",
            "longterm_memory": project_root / "memory" / "maria_longterm_memory.jsonl",
            "code_self_model": project_root / "meta_data" / "code_self_model.json",
            "input_dir": project_root / "input",
        }


class ContextBuilder:
    """
    Builds a compact self-awareness context string for Maria's system prompt.

    The context is cached for CACHE_TTL seconds to avoid reading files
    on every brain.think() call.

    Usage:
        builder = ContextBuilder()
        context = builder.build()
        # Returns: "[Swiadomosc: ...]" or "" on failure
    """

    CACHE_TTL = 60  # seconds

    def __init__(
        self,
        knowledge_index_path: Optional[Path] = None,
        longterm_memory_path: Optional[Path] = None,
        code_self_model_path: Optional[Path] = None,
        input_dir: Optional[Path] = None,
    ):
        """
        Initialize with optional path overrides (useful for testing).

        Args:
            knowledge_index_path: Override for knowledge_index.jsonl
            longterm_memory_path: Override for maria_longterm_memory.jsonl
            code_self_model_path: Override for code_self_model.json
            input_dir: Override for input/ directory
        """
        paths = _resolve_paths()

        self._knowledge_index = knowledge_index_path or paths["knowledge_index"]
        self._longterm_memory = longterm_memory_path or paths["longterm_memory"]
        self._code_self_model = code_self_model_path or paths["code_self_model"]
        self._input_dir = input_dir or paths["input_dir"]

        self._cache: str = ""
        self._cache_time: float = 0.0

    def build(self) -> str:
        """
        Build and return the awareness context string.

        Returns cached result if less than CACHE_TTL seconds old.

        Returns:
            String like "[Swiadomosc: ...]" or "" if all sources fail.
        """
        if time.time() - self._cache_time < self.CACHE_TTL:
            return self._cache

        parts = []

        learning = self._learning_status()
        if learning:
            parts.append(learning)

        knowledge = self._knowledge_summary()
        if knowledge:
            parts.append(knowledge)

        code = self._code_summary()
        if code:
            parts.append(code)

        system = self._system_status()
        if system:
            parts.append(system)

        if parts:
            self._cache = "[Swiadomosc: " + ". ".join(parts) + ".]"
        else:
            self._cache = ""

        self._cache_time = time.time()
        return self._cache

    def invalidate_cache(self) -> None:
        """Force refresh on next build() call."""
        self._cache_time = 0.0

    # ------------------------------------------------------------------
    # Private: data sources
    # ------------------------------------------------------------------

    def _learning_status(self) -> str:
        """
        Summarize files in the learning queue from knowledge_index.jsonl.

        Returns:
            e.g. "Pliki do nauki: 7 (1 ukonczone, 1 w trakcie, 5 nowych)"
            or "" on failure.
        """
        if not self._knowledge_index.exists():
            return ""

        try:
            counts = {
                "completed": 0,
                "learning": 0,
                "new": 0,
                "hard_topic": 0,
                "exam_failed": 0,
                "learned": 0,
                "other": 0,
            }
            total = 0

            with open(self._knowledge_index, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        status = record.get("status", "other")
                        if status in counts:
                            counts[status] += 1
                        else:
                            counts["other"] += 1
                        total += 1
                    except json.JSONDecodeError:
                        continue

            if total == 0:
                return ""

            # Build summary
            details = []
            if counts["completed"] > 0:
                details.append(f"{counts['completed']} ukonczone")
            if counts["learning"] > 0:
                details.append(f"{counts['learning']} w trakcie")
            if counts["learned"] > 0:
                details.append(f"{counts['learned']} nauczone")
            if counts["new"] > 0:
                details.append(f"{counts['new']} nowe")
            if counts["hard_topic"] > 0:
                details.append(f"{counts['hard_topic']} trudne")
            if counts["exam_failed"] > 0:
                details.append(f"{counts['exam_failed']} niezdane")

            detail_str = ", ".join(details) if details else "brak danych"
            return f"Mam {total} plikow do nauki ({detail_str})"

        except Exception as e:
            logger.debug(f"ContextBuilder: learning_status error: {e}")
            return ""

    def _knowledge_summary(self) -> str:
        """
        Summarize recently learned topics from longterm_memory.jsonl.

        Returns:
            e.g. "Tagi nauki: decyzje, ekspert, pytania"
            or "" on failure.
        """
        if not self._longterm_memory.exists():
            return ""

        try:
            all_tags: List[str] = []

            with open(self._longterm_memory, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        tags = record.get("tags", [])
                        if isinstance(tags, list):
                            all_tags.extend(tags)
                    except json.JSONDecodeError:
                        continue

            if not all_tags:
                return ""

            # Deduplicate, keep top 8 most common
            from collections import Counter
            tag_counts = Counter(all_tags)
            top_tags = [tag for tag, _ in tag_counts.most_common(8)]

            return "Tagi nauki: " + ", ".join(top_tags)

        except Exception as e:
            logger.debug(f"ContextBuilder: knowledge_summary error: {e}")
            return ""

    def _code_summary(self) -> str:
        """
        Summarize Maria's own code stats from code_self_model.json.

        Returns:
            e.g. "Moj kod: 92 pliki, 16942 linii, 133 funkcje"
            or "" if file not found.
        """
        if not self._code_self_model.exists():
            return ""

        try:
            with open(self._code_self_model, "r", encoding="utf-8") as f:
                model = json.load(f)

            stats = model.get("statistics", model.get("stats", {}))
            if not stats:
                return ""

            files = stats.get("files", stats.get("total_files", 0))
            lines = stats.get("lines", stats.get("total_lines", 0))
            functions = stats.get("functions", stats.get("total_functions", 0))
            classes = stats.get("classes", stats.get("total_classes", 0))

            parts = []
            if files:
                parts.append(f"{files} plikow")
            if lines:
                parts.append(f"{lines} linii")
            if functions:
                parts.append(f"{functions} funkcji")
            if classes:
                parts.append(f"{classes} klas")

            if not parts:
                return ""

            return "Moj kod: " + ", ".join(parts)

        except Exception as e:
            logger.debug(f"ContextBuilder: code_summary error: {e}")
            return ""

    def _system_status(self) -> str:
        """
        Current system metrics (RAM, CPU) from psutil.

        Returns:
            e.g. "RAM 45%, CPU 12%"
            or "" if psutil unavailable.
        """
        if not _PSUTIL_OK:
            return ""

        try:
            ram = psutil.virtual_memory().percent
            cpu = psutil.cpu_percent(interval=0.1)
            return f"RAM {ram:.0f}%, CPU {cpu:.0f}%"
        except Exception as e:
            logger.debug(f"ContextBuilder: system_status error: {e}")
            return ""

    def get_input_files(self) -> List[str]:
        """
        List of filenames in input/ directory.

        Returns:
            List of .txt filenames, or empty list.
        """
        if not self._input_dir.exists():
            return []
        try:
            return sorted([
                f.name for f in self._input_dir.rglob("*.txt")
            ])
        except Exception:
            return []

    def get_detailed_file_list(self) -> List[dict]:
        """
        Detailed file list with statuses from knowledge_index.jsonl.

        Returns:
            List of dicts with keys: file, status, priority, exam_score.
        """
        if not self._knowledge_index.exists():
            return []

        results = []
        try:
            with open(self._knowledge_index, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        last_scores = record.get("last_scores", [])
                        score = last_scores[-1] if last_scores else None
                        results.append({
                            "file": record.get("file", "?"),
                            "status": record.get("status", "?"),
                            "priority": record.get("priority", 0),
                            "exam_score": score,
                            "chunks_learned": record.get("chunks_learned", 0),
                            "total_chunks": record.get("total_chunks", 0),
                        })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.debug(f"ContextBuilder: detailed_file_list error: {e}")

        return results
