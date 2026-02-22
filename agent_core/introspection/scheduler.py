"""
Introspection Scheduler - Periodic code analysis for homeostasis.

Runs code analysis in the background at configurable intervals.
READ-ONLY: This module only reads code and writes analysis results.
"""

import os
import time
import threading
import logging
from typing import Optional, Callable
from datetime import datetime
from pathlib import Path

from .analyzer import CodeAnalyzer
from .code_model import CodeModel
from .reporters import DualReporter

logger = logging.getLogger(__name__)


class IntrospectionScheduler:
    """
    Schedules periodic code introspection.

    Integrates with homeostasis loop by running analysis
    at configurable intervals (default: every hour).

    READ-ONLY: Only reads source code and writes JSON analysis.
    """

    # Default analysis interval (1 hour)
    DEFAULT_INTERVAL_SEC = 3600

    # Minimum interval (5 minutes)
    MIN_INTERVAL_SEC = 300

    def __init__(
        self,
        project_root: str,
        output_path: Optional[str] = None,
        interval_sec: int = DEFAULT_INTERVAL_SEC,
        on_analysis_complete: Optional[Callable[[CodeModel], None]] = None,
    ):
        """
        Initialize introspection scheduler.

        Args:
            project_root: Path to M.A.R.I.A. project root
            output_path: Path for saving analysis (default: meta_data/code_self_model.json)
            interval_sec: Analysis interval in seconds
            on_analysis_complete: Optional callback when analysis completes
        """
        self.project_root = Path(project_root)
        self.interval_sec = max(interval_sec, self.MIN_INTERVAL_SEC)

        # Default output path
        if output_path is None:
            meta_dir = self.project_root / "meta_data"
            meta_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(meta_dir / "code_self_model.json")
        else:
            # Ensure parent directory exists for custom output path
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
        self.output_path = output_path

        self.on_analysis_complete = on_analysis_complete

        # State
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_analysis: Optional[datetime] = None
        self._model: Optional[CodeModel] = None
        self._analyzer = CodeAnalyzer(str(self.project_root))

    def start(self) -> None:
        """Start the periodic analysis loop."""
        if self._running:
            logger.warning("Introspection scheduler already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="IntrospectionScheduler"
        )
        self._thread.start()
        logger.info(
            f"Introspection scheduler started "
            f"(interval: {self.interval_sec}s)"
        )

    def stop(self) -> None:
        """Stop the periodic analysis loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Introspection scheduler stopped")

    def _run_loop(self) -> None:
        """Main scheduler loop."""
        # Run initial analysis immediately
        self._run_analysis()

        while self._running:
            # Wait for interval
            time.sleep(self.interval_sec)

            if not self._running:
                break

            # Run analysis
            self._run_analysis()

    def _run_analysis(self) -> None:
        """Execute a single analysis cycle."""
        try:
            logger.info("Starting code introspection...")
            start_time = time.time()

            # Run analysis (READ-ONLY)
            self._model = self._analyzer.analyze()

            # Save to file
            self._analyzer.save_model(self.output_path)

            self._last_analysis = datetime.now()
            duration = time.time() - start_time

            logger.info(
                f"Code introspection complete: "
                f"{self._model.total_files} files, "
                f"{self._model.total_lines} lines "
                f"({duration:.2f}s)"
            )

            # Call callback if provided
            if self.on_analysis_complete and self._model:
                try:
                    self.on_analysis_complete(self._model)
                except Exception as e:
                    logger.warning(f"Analysis callback error: {e}")

        except Exception as e:
            logger.error(f"Introspection analysis failed: {e}")

    def run_now(self) -> Optional[CodeModel]:
        """
        Run analysis immediately (blocking).

        Returns:
            CodeModel or None if analysis fails
        """
        self._run_analysis()
        return self._model

    def get_model(self) -> Optional[CodeModel]:
        """
        Get the latest analysis model.

        Returns:
            Latest CodeModel or None if no analysis yet
        """
        # Try to load from file if no model in memory
        if self._model is None and os.path.exists(self.output_path):
            try:
                self._model = CodeAnalyzer.load_model(self.output_path)
            except Exception:
                pass
        return self._model

    def get_last_analysis_time(self) -> Optional[datetime]:
        """Get timestamp of last analysis."""
        return self._last_analysis

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    def get_human_summary(self) -> Optional[str]:
        """
        Get human-readable summary of Maria's code.

        Returns:
            Natural language description or None
        """
        model = self.get_model()
        if not model:
            return None

        reporter = DualReporter(model)
        return reporter.human.summary()

    def get_technical_summary(self) -> Optional[str]:
        """
        Get technical summary of Maria's code.

        Returns:
            Technical report or None
        """
        model = self.get_model()
        if not model:
            return None

        reporter = DualReporter(model)
        return reporter.tech.detailed_stats()

    def get_dual_summary(self) -> tuple:
        """
        Get both human and technical summaries.

        Returns:
            (human_text, technical_text) or (None, None)
        """
        model = self.get_model()
        if not model:
            return None, None

        reporter = DualReporter(model)
        return reporter.full_report()


# Global instance for easy access
_scheduler: Optional[IntrospectionScheduler] = None


def get_introspection_scheduler(
    project_root: Optional[str] = None,
) -> Optional[IntrospectionScheduler]:
    """
    Get or create the global introspection scheduler.

    Args:
        project_root: Project root path (required on first call)

    Returns:
        IntrospectionScheduler instance or None
    """
    global _scheduler

    if _scheduler is None and project_root:
        _scheduler = IntrospectionScheduler(project_root)

    return _scheduler


def init_introspection(
    project_root: str,
    start_scheduler: bool = True,
    interval_sec: int = 3600,
) -> IntrospectionScheduler:
    """
    Initialize the introspection system.

    Args:
        project_root: Path to M.A.R.I.A. project root
        start_scheduler: Whether to start periodic analysis
        interval_sec: Analysis interval in seconds

    Returns:
        Initialized scheduler
    """
    global _scheduler

    _scheduler = IntrospectionScheduler(
        project_root=project_root,
        interval_sec=interval_sec,
    )

    if start_scheduler:
        _scheduler.start()

    return _scheduler
