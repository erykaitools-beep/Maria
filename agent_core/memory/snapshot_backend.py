"""
Snapshot Backend - Copy-on-Write memory snapshots

Provides atomic snapshots of memory state for:
- Recovery after crashes
- Pre-transition checkpoints
- Periodic backups

Uses Copy-on-Write pattern for efficiency.
"""

import os
import time
import json
import hashlib
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class MemorySnapshotBackend:
    """
    Copy-on-Write snapshot backend for memory.

    Provides atomic, consistent snapshots of memory state.
    """

    SNAPSHOT_PREFIX = "memory_snapshot_"
    SNAPSHOT_SUFFIX = ".json"
    MAX_SNAPSHOTS = 5

    def __init__(self, snapshot_dir: str = "data/memory_snapshots"):
        """
        Initialize snapshot backend.

        Args:
            snapshot_dir: Directory to store snapshots
        """
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(
        self,
        episodic_data: List[Dict[str, Any]],
        semantic_nodes: Dict[str, Dict[str, Any]],
        semantic_edges: List[Dict[str, Any]],
        metadata: Dict[str, Any] = None,
    ) -> str:
        """
        Create atomic memory snapshot.

        Args:
            episodic_data: Episodic memory entries
            semantic_nodes: Semantic graph nodes
            semantic_edges: Semantic graph edges
            metadata: Additional metadata

        Returns:
            Path to created snapshot

        Raises:
            IOError: If snapshot creation fails
        """
        timestamp = time.time()

        snapshot_data = {
            "timestamp": timestamp,
            "version": 1,
            "episodic": {
                "entries": episodic_data,
                "count": len(episodic_data),
                "hash": self._compute_hash(json.dumps(episodic_data, sort_keys=True)),
            },
            "semantic": {
                "nodes": semantic_nodes,
                "edges": semantic_edges,
                "node_count": len(semantic_nodes),
                "edge_count": len(semantic_edges),
                "hash": self._compute_hash(
                    json.dumps({"nodes": semantic_nodes, "edges": semantic_edges}, sort_keys=True)
                ),
            },
            "metadata": metadata or {},
        }

        # Write atomically
        filename = f"{self.SNAPSHOT_PREFIX}{int(timestamp)}{self.SNAPSHOT_SUFFIX}"
        final_path = self.snapshot_dir / filename

        try:
            # Write to temp file first
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.snapshot_dir,
                suffix='.tmp',
                delete=False,
            ) as tmp:
                json.dump(snapshot_data, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name

            # Atomic rename
            shutil.move(tmp_path, final_path)

            # Cleanup old snapshots
            self._cleanup_old_snapshots()

            logger.info(f"Memory snapshot created: {final_path}")
            return str(final_path)

        except Exception as e:
            # Clean up temp file
            try:
                if 'tmp_path' in locals():
                    os.unlink(tmp_path)
            except:
                pass
            raise IOError(f"Snapshot creation failed: {e}")

    def restore_snapshot(
        self,
        snapshot_path: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Restore from snapshot.

        Args:
            snapshot_path: Path to specific snapshot, or None for latest

        Returns:
            Snapshot data dictionary, or None if restore fails
        """
        # Find snapshot to restore
        if snapshot_path:
            path = Path(snapshot_path)
        else:
            path = self._find_latest_snapshot()

        if not path or not path.exists():
            logger.warning("No snapshot found to restore")
            return None

        try:
            with open(path, 'r') as f:
                data = json.load(f)

            # Validate snapshot
            if not self._validate_snapshot(data):
                logger.warning(f"Snapshot validation failed: {path}")
                return self._try_previous_snapshot(path)

            logger.info(f"Restored from snapshot: {path}")
            return data

        except Exception as e:
            logger.error(f"Snapshot restore failed: {e}")
            return self._try_previous_snapshot(path)

    def _validate_snapshot(self, data: Dict[str, Any]) -> bool:
        """Validate snapshot integrity."""
        try:
            # Check required fields
            if "timestamp" not in data:
                return False
            if "episodic" not in data or "semantic" not in data:
                return False

            # Verify hashes
            episodic_hash = self._compute_hash(
                json.dumps(data["episodic"]["entries"], sort_keys=True)
            )
            if episodic_hash != data["episodic"]["hash"]:
                logger.warning("Episodic hash mismatch")
                return False

            semantic_data = {
                "nodes": data["semantic"]["nodes"],
                "edges": data["semantic"]["edges"],
            }
            semantic_hash = self._compute_hash(json.dumps(semantic_data, sort_keys=True))
            if semantic_hash != data["semantic"]["hash"]:
                logger.warning("Semantic hash mismatch")
                return False

            return True

        except Exception as e:
            logger.warning(f"Validation error: {e}")
            return False

    def _find_latest_snapshot(self) -> Optional[Path]:
        """Find most recent snapshot."""
        snapshots = self._list_snapshots()
        return snapshots[-1] if snapshots else None

    def _list_snapshots(self) -> List[Path]:
        """List all snapshots sorted by time."""
        pattern = f"{self.SNAPSHOT_PREFIX}*{self.SNAPSHOT_SUFFIX}"
        snapshots = list(self.snapshot_dir.glob(pattern))
        return sorted(snapshots, key=lambda p: p.stat().st_mtime)

    def _try_previous_snapshot(self, current: Path) -> Optional[Dict[str, Any]]:
        """Try previous snapshot if current fails."""
        snapshots = self._list_snapshots()
        try:
            idx = snapshots.index(current)
            if idx > 0:
                return self.restore_snapshot(str(snapshots[idx - 1]))
        except (ValueError, IndexError):
            pass
        return None

    def _cleanup_old_snapshots(self) -> None:
        """Remove old snapshots beyond MAX_SNAPSHOTS."""
        snapshots = self._list_snapshots()
        while len(snapshots) > self.MAX_SNAPSHOTS:
            old = snapshots.pop(0)
            try:
                old.unlink()
                logger.debug(f"Removed old snapshot: {old}")
            except Exception:
                pass

    def _compute_hash(self, data: str) -> str:
        """Compute SHA-256 hash."""
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def get_snapshot_count(self) -> int:
        """Get number of stored snapshots."""
        return len(self._list_snapshots())

    def get_latest_timestamp(self) -> Optional[float]:
        """Get timestamp of latest snapshot."""
        latest = self._find_latest_snapshot()
        if latest:
            try:
                with open(latest, 'r') as f:
                    data = json.load(f)
                    return data.get("timestamp")
            except:
                pass
        return None
