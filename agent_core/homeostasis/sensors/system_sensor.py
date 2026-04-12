"""
SystemSensor v2 - Service-level health monitoring.

Checks: Ollama alive, systemd restarts, disk space.
Separate from ResourceSensor (hardware metrics via psutil).
"""

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemHealth:
    """Service-level health snapshot."""

    ollama_alive: bool
    ollama_latency_ms: float  # 0 if dead
    service_restarts: int
    service_uptime_sec: float
    disk_free_gb: float
    disk_free_pct: float
    storage_warning: bool  # True if < 5GB or < 10%
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "ollama_alive": self.ollama_alive,
            "ollama_latency_ms": self.ollama_latency_ms,
            "service_restarts": self.service_restarts,
            "service_uptime_sec": self.service_uptime_sec,
            "disk_free_gb": round(self.disk_free_gb, 1),
            "disk_free_pct": round(self.disk_free_pct, 1),
            "storage_warning": self.storage_warning,
        }

    def format_alerts(self) -> list:
        """Return list of Polish alert strings (empty if all ok)."""
        alerts = []
        if not self.ollama_alive:
            alerts.append("Ollama nie odpowiada!")
        if self.service_restarts > 0:
            alerts.append(f"maria.service restartowana {self.service_restarts}x")
        if self.storage_warning:
            alerts.append(f"Mala ilosc miejsca: {self.disk_free_gb:.1f}GB ({self.disk_free_pct:.0f}%)")
        return alerts


class SystemSensor:
    """Service-level health monitoring."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        service_name: str = "maria.service",
        disk_path: str = "/",
        cache_ttl: int = 60,
    ):
        self._ollama_url = ollama_url
        self._service_name = service_name
        self._disk_path = disk_path
        self._cache_ttl = cache_ttl
        self._cached: Optional[SystemHealth] = None
        self._cached_at: float = 0.0

    def read_health(self) -> SystemHealth:
        """Read current system health (cached with TTL)."""
        now = time.time()
        if self._cached and (now - self._cached_at) < self._cache_ttl:
            return self._cached

        ollama_alive, ollama_latency = self._check_ollama()
        restarts, uptime = self._check_service()
        disk_free_gb, disk_free_pct = self._check_disk()
        storage_warning = disk_free_gb < 5.0 or disk_free_pct < 10.0

        health = SystemHealth(
            ollama_alive=ollama_alive,
            ollama_latency_ms=ollama_latency,
            service_restarts=restarts,
            service_uptime_sec=uptime,
            disk_free_gb=disk_free_gb,
            disk_free_pct=disk_free_pct,
            storage_warning=storage_warning,
            timestamp=now,
        )

        self._cached = health
        self._cached_at = now
        return health

    def _check_ollama(self) -> tuple:
        """Ping Ollama API. Returns (alive, latency_ms)."""
        try:
            start = time.time()
            resp = requests.get(f"{self._ollama_url}/api/tags", timeout=3)
            latency = (time.time() - start) * 1000
            return resp.status_code == 200, latency
        except Exception:
            return False, 0.0

    def _check_service(self) -> tuple:
        """Check systemd service. Returns (restart_count, uptime_sec)."""
        restarts = 0
        uptime = 0.0
        try:
            result = subprocess.run(
                ["systemctl", "show", self._service_name,
                 "--property=NRestarts,ActiveEnterTimestamp", "--value"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 1:
                    try:
                        restarts = int(lines[0])
                    except ValueError:
                        pass
                # Uptime from ActiveEnterTimestamp is complex to parse
                # Use simpler approach: ExecMainStartTimestamp via another call
        except Exception:
            pass

        # Uptime via /proc/uptime as fallback (system uptime, not service)
        try:
            with open("/proc/uptime", "r") as f:
                uptime = float(f.read().split()[0])
        except Exception:
            pass

        return restarts, uptime

    def _check_disk(self) -> tuple:
        """Check disk space. Returns (free_gb, free_pct)."""
        try:
            usage = shutil.disk_usage(self._disk_path)
            free_gb = usage.free / (1024 ** 3)
            free_pct = (usage.free / usage.total) * 100 if usage.total > 0 else 0
            return free_gb, free_pct
        except Exception:
            return 0.0, 0.0
