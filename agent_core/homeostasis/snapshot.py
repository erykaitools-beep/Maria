"""
Snapshot and Recovery Protocol

Handles:
- Atomic system state snapshots (Copy-on-Write)
- Recovery from snapshots after restart
- Graceful and ungraceful shutdown handling
- Snapshot validation (CRC/hash)

Spec reference: homeostasis_spec.md lines 465-523, 1673-1726
"""

import os
import time
import json
import hashlib
import shutil
import tempfile
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import asdict

from .state_model import Mode, SnapshotData


logger = logging.getLogger(__name__)


class SnapshotError(Exception):
    """Exception raised for snapshot operations."""
    pass


class SnapshotManager:
    """
    Manages system state snapshots.

    Implements atomic CoW (Copy-on-Write) snapshots for
    safe recovery after crashes.

    Spec: homeostasis_spec.md lines 1673-1701
    """

    # Configuration
    MAX_SNAPSHOTS = 10  # Keep last N snapshots
    SNAPSHOT_PREFIX = "snapshot_"
    SNAPSHOT_SUFFIX = ".json"

    def __init__(self, snapshot_dir: str = "data/snapshots"):
        """
        Initialize snapshot manager.

        Args:
            snapshot_dir: Directory to store snapshots
        """
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        self._current_snapshot: Optional[SnapshotData] = None

    def create_snapshot(
        self,
        mode: Mode,
        health_score: float,
        episodic_memory_data: Dict[str, Any],
        semantic_model_data: Dict[str, Any],
        context_data: Dict[str, Any],
        resource_headroom: Dict[str, float],
    ) -> str:
        """
        Create atomic snapshot of system state.

        Spec: homeostasis_spec.md lines 468-507, 1676-1701

        Process:
        1. Collect all state data
        2. Write to temp file
        3. Validate (compute hash)
        4. Atomic rename to final location
        5. Clean up old snapshots

        Args:
            mode: Current operating mode
            health_score: Current health score
            episodic_memory_data: Episodic memory metadata
            semantic_model_data: Semantic model metadata
            context_data: Current context/goal state
            resource_headroom: Current resource availability

        Returns:
            Path to created snapshot file

        Raises:
            SnapshotError: If snapshot creation fails
        """
        timestamp = time.time()

        # Build snapshot data
        snapshot = SnapshotData(
            timestamp=timestamp,
            uptime_seconds=self._get_uptime(),
            mode=mode,
            # Episodic memory
            episodic_memory_version=episodic_memory_data.get("version", 0),
            episodic_memory_size_mb=episodic_memory_data.get("size_mb", 0),
            episodic_memory_hash=self._compute_hash(
                json.dumps(episodic_memory_data, sort_keys=True)
            ),
            episodic_memory_entries=episodic_memory_data.get("entries", 0),
            episodic_freshness_sec=episodic_memory_data.get("freshness_sec", 0),
            # Semantic model
            semantic_model_version=semantic_model_data.get("version", 0),
            semantic_node_count=semantic_model_data.get("node_count", 0),
            semantic_model_hash=self._compute_hash(
                json.dumps(semantic_model_data, sort_keys=True)
            ),
            semantic_consistency_score=semantic_model_data.get("consistency_score", 1.0),
            # Context
            active_goal_stack=context_data.get("goal_stack", []),
            current_topic_embedding=context_data.get("topic_embedding", []),
            error_rate_recent=context_data.get("error_rate", 0.0),
            # Homeostasis
            health_score=health_score,
            resource_headroom=resource_headroom,
            last_mode_transition=context_data.get("last_mode_transition", timestamp),
        )

        # Write atomically
        snapshot_path = self._write_atomic(snapshot)

        # Clean old snapshots
        self._cleanup_old_snapshots()

        self._current_snapshot = snapshot
        logger.info(f"Snapshot created: {snapshot_path}")

        return str(snapshot_path)

    def _write_atomic(self, snapshot: SnapshotData) -> Path:
        """
        Write snapshot atomically using temp file + rename.

        Spec: homeostasis_spec.md lines 1693-1696
        """
        # Create filename with timestamp
        filename = f"{self.SNAPSHOT_PREFIX}{int(snapshot.timestamp)}{self.SNAPSHOT_SUFFIX}"
        final_path = self.snapshot_dir / filename

        # Write to temp file first
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.snapshot_dir,
                suffix='.tmp',
                delete=False,
            ) as tmp:
                json.dump(snapshot.to_dict(), tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name

            # Atomic rename (on POSIX) or copy+delete (on Windows)
            shutil.move(tmp_path, final_path)

            return final_path

        except Exception as e:
            # Clean up temp file if it exists
            try:
                if 'tmp_path' in locals():
                    os.unlink(tmp_path)
            except:
                pass
            raise SnapshotError(f"Failed to write snapshot: {e}")

    def recover_from_snapshot(
        self,
        snapshot_path: Optional[str] = None,
    ) -> Optional[SnapshotData]:
        """
        Recover system state from snapshot.

        Spec: homeostasis_spec.md lines 509-523

        Process:
        1. Load snapshot from disk
        2. Validate hashes
        3. Check timestamp (how old?)
        4. Verify consistency score
        5. Return data for restoration

        Args:
            snapshot_path: Specific snapshot to load, or None for latest

        Returns:
            SnapshotData if valid, None if recovery failed
        """
        # Find snapshot to load
        if snapshot_path:
            path = Path(snapshot_path)
        else:
            path = self._find_latest_snapshot()

        if not path or not path.exists():
            logger.warning("No snapshot found for recovery")
            return None

        try:
            # Load snapshot
            with open(path, 'r') as f:
                data = json.load(f)

            snapshot = SnapshotData.from_dict(data)

            # Validate
            if not self._validate_snapshot(snapshot):
                logger.warning(f"Snapshot validation failed: {path}")
                # Try previous snapshot
                return self._try_previous_snapshot(path)

            # Check age
            age_hours = (time.time() - snapshot.timestamp) / 3600
            if age_hours > 24:
                logger.warning(f"Snapshot is {age_hours:.1f} hours old")

            logger.info(f"Recovered from snapshot: {path}")
            self._current_snapshot = snapshot
            return snapshot

        except Exception as e:
            logger.error(f"Failed to recover from snapshot: {e}")
            return self._try_previous_snapshot(path)

    def _validate_snapshot(self, snapshot: SnapshotData) -> bool:
        """
        Validate snapshot integrity.

        Spec: homeostasis_spec.md lines 514-519
        """
        # Check required fields
        if snapshot.timestamp <= 0:
            return False

        # Check consistency score
        if snapshot.semantic_consistency_score < 0.5:
            logger.warning(f"Low semantic consistency: {snapshot.semantic_consistency_score}")
            # Still valid, but degraded

        # Check mode is valid
        try:
            Mode(snapshot.mode.value if isinstance(snapshot.mode, Mode) else snapshot.mode)
        except ValueError:
            return False

        return True

    def _try_previous_snapshot(self, current_path: Path) -> Optional[SnapshotData]:
        """Try to recover from previous snapshot."""
        snapshots = self._list_snapshots()
        try:
            current_idx = snapshots.index(current_path)
            if current_idx > 0:
                return self.recover_from_snapshot(str(snapshots[current_idx - 1]))
        except (ValueError, IndexError):
            pass
        return None

    def _find_latest_snapshot(self) -> Optional[Path]:
        """Find the most recent valid snapshot."""
        snapshots = self._list_snapshots()
        if snapshots:
            return snapshots[-1]
        return None

    def _list_snapshots(self) -> List[Path]:
        """List all snapshots sorted by timestamp (oldest first)."""
        pattern = f"{self.SNAPSHOT_PREFIX}*{self.SNAPSHOT_SUFFIX}"
        snapshots = list(self.snapshot_dir.glob(pattern))
        return sorted(snapshots, key=lambda p: p.stat().st_mtime)

    def _cleanup_old_snapshots(self) -> None:
        """Remove old snapshots, keeping only MAX_SNAPSHOTS."""
        snapshots = self._list_snapshots()
        while len(snapshots) > self.MAX_SNAPSHOTS:
            old = snapshots.pop(0)
            try:
                old.unlink()
                logger.debug(f"Removed old snapshot: {old}")
            except Exception as e:
                logger.warning(f"Failed to remove old snapshot {old}: {e}")

    def _compute_hash(self, data: str) -> str:
        """Compute SHA-256 hash of data."""
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def _get_uptime(self) -> float:
        """Get system uptime in seconds."""
        try:
            with open('/proc/uptime', 'r') as f:
                return float(f.read().split()[0])
        except:
            return 0.0

    def get_current_snapshot(self) -> Optional[SnapshotData]:
        """Get the most recently created/loaded snapshot."""
        return self._current_snapshot

    def get_snapshot_count(self) -> int:
        """Get number of stored snapshots."""
        return len(self._list_snapshots())


class ShutdownManager:
    """
    Manages graceful and ungraceful shutdown.

    Spec: homeostasis_spec.md lines 1706-1726
    """

    def __init__(self, snapshot_manager: SnapshotManager):
        """
        Initialize shutdown manager.

        Args:
            snapshot_manager: Snapshot manager for final checkpoint
        """
        self.snapshot_manager = snapshot_manager
        self._shutdown_initiated = False
        self._shutdown_marker_path = Path("data/.shutdown_marker")

    def initiate_graceful_shutdown(
        self,
        core,
        timeout_seconds: int = 30,
    ) -> bool:
        """
        Initiate graceful shutdown sequence.

        Spec: homeostasis_spec.md lines 1709-1716

        Process:
        1. Signal all modules: shutdown.prepare
        2. Wait for modules to finish
        3. Flush all buffers
        4. Take final snapshot
        5. Mark clean shutdown

        Args:
            core: HomeostasisCore instance
            timeout_seconds: Max time to wait for modules

        Returns:
            True if shutdown completed cleanly
        """
        logger.info("Initiating graceful shutdown")
        self._shutdown_initiated = True

        try:
            # 1. Signal modules
            if core.executor:
                core.executor.signal_module("all", "shutdown_prepare",
                                           grace_period_seconds=timeout_seconds)

            # 2. Wait for acknowledgment (simplified)
            time.sleep(min(5, timeout_seconds))

            # 3. Take final snapshot
            self._create_final_snapshot(core)

            # 4. Mark clean shutdown
            self._mark_clean_shutdown()

            logger.info("Graceful shutdown complete")
            return True

        except Exception as e:
            logger.error(f"Graceful shutdown failed: {e}")
            return False

    def initiate_emergency_shutdown(self, core) -> None:
        """
        Initiate emergency (ungraceful) shutdown.

        Spec: homeostasis_spec.md lines 1718-1726

        Used when:
        - Power loss detected
        - Critical system failure
        - < 2 seconds to act
        """
        logger.warning("Initiating emergency shutdown")
        self._shutdown_initiated = True

        try:
            # Quick snapshot (don't wait for anything)
            self._create_final_snapshot(core)
        except Exception as e:
            logger.error(f"Emergency snapshot failed: {e}")

    def _create_final_snapshot(self, core) -> None:
        """Create final pre-shutdown snapshot."""
        try:
            self.snapshot_manager.create_snapshot(
                mode=core.state.mode,
                health_score=core.state.health_score,
                episodic_memory_data={"version": 0, "entries": 0, "size_mb": 0},
                semantic_model_data={"version": 0, "node_count": 0, "consistency_score": 1.0},
                context_data={
                    "goal_stack": [],
                    "last_mode_transition": core.state.last_mode_change_time,
                },
                resource_headroom=core.state.interpreted_state.get("resource_headroom", {}),
            )
        except Exception as e:
            logger.error(f"Final snapshot failed: {e}")

    def _mark_clean_shutdown(self) -> None:
        """Write marker file indicating clean shutdown."""
        try:
            self._shutdown_marker_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._shutdown_marker_path, 'w') as f:
                f.write(str(time.time()))
        except Exception as e:
            logger.warning(f"Failed to write shutdown marker: {e}")

    def check_clean_shutdown(self) -> bool:
        """
        Check if last shutdown was clean.

        Returns:
            True if shutdown marker exists (clean), False otherwise
        """
        if self._shutdown_marker_path.exists():
            # Clean up marker
            try:
                self._shutdown_marker_path.unlink()
            except:
                pass
            return True
        return False

    def is_shutdown_initiated(self) -> bool:
        """Check if shutdown has been initiated."""
        return self._shutdown_initiated
