"""
Power Sensor - Voltage and uptime monitoring

Monitors (spec section 1.1.A):
- Supply voltage (for SBC like Raspberry Pi)
- Uptime (relative to last critical event)
- Shutdown predictability (graceful vs dirty)

Note: This sensor is optional and primarily for single-board computers.

Spec reference: homeostasis_spec.md lines 38-41
"""

import os
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class PowerMetrics:
    """Power sensor readings."""
    timestamp: float
    uptime_seconds: float
    voltage_v: Optional[float]
    is_on_battery: bool
    last_shutdown_clean: bool


class PowerSensor:
    """
    Reads power-related metrics.

    Primarily for SBC (Raspberry Pi, etc.) but provides
    uptime tracking on all platforms.
    """

    def __init__(self):
        """Initialize power sensor."""
        self._start_time = time.time()
        self._last_shutdown_clean = True  # Assume clean start

        # Try to detect if last shutdown was dirty
        self._check_last_shutdown()

    def read_metrics(self) -> PowerMetrics:
        """
        Read power metrics.

        Returns:
            PowerMetrics with current values
        """
        return PowerMetrics(
            timestamp=time.time(),
            uptime_seconds=self.get_uptime(),
            voltage_v=self._read_voltage(),
            is_on_battery=self._check_battery(),
            last_shutdown_clean=self._last_shutdown_clean,
        )

    def get_uptime(self) -> float:
        """Get system uptime in seconds."""
        # Try system uptime first
        system_uptime = self._read_system_uptime()
        if system_uptime is not None:
            return system_uptime

        # Fallback to process uptime
        return time.time() - self._start_time

    def _read_system_uptime(self) -> Optional[float]:
        """Read system uptime from /proc/uptime (Linux)."""
        try:
            if os.path.exists('/proc/uptime'):
                with open('/proc/uptime', 'r') as f:
                    uptime_str = f.read().split()[0]
                    return float(uptime_str)
        except (IOError, ValueError, IndexError):
            pass

        # Windows: use psutil if available
        try:
            import psutil
            boot_time = psutil.boot_time()
            return time.time() - boot_time
        except Exception:
            pass

        return None

    def _read_voltage(self) -> Optional[float]:
        """
        Read supply voltage (SBC only).

        Supports Raspberry Pi voltage monitoring.
        """
        # Raspberry Pi voltage file
        vcgencmd_output = self._run_vcgencmd()
        if vcgencmd_output is not None:
            return vcgencmd_output

        # Try hwmon voltage sensors
        voltage = self._read_hwmon_voltage()
        if voltage is not None:
            return voltage

        return None

    def _run_vcgencmd(self) -> Optional[float]:
        """Run vcgencmd to get Raspberry Pi voltage."""
        try:
            import subprocess
            result = subprocess.run(
                ['vcgencmd', 'measure_volts'],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                # Output format: volt=1.2000V
                output = result.stdout.strip()
                if 'volt=' in output:
                    voltage_str = output.split('=')[1].rstrip('V')
                    return float(voltage_str)
        except Exception:
            pass
        return None

    def _read_hwmon_voltage(self) -> Optional[float]:
        """Read voltage from hwmon sensors."""
        hwmon_base = '/sys/class/hwmon'
        try:
            if os.path.exists(hwmon_base):
                for hwmon in os.listdir(hwmon_base):
                    hwmon_path = os.path.join(hwmon_base, hwmon)
                    # Look for in0_input (voltage in millivolts)
                    voltage_file = os.path.join(hwmon_path, 'in0_input')
                    if os.path.exists(voltage_file):
                        with open(voltage_file, 'r') as f:
                            mv = int(f.read().strip())
                            return mv / 1000.0
        except Exception:
            pass
        return None

    def _check_battery(self) -> bool:
        """Check if system is running on battery."""
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery:
                return not battery.power_plugged
        except Exception:
            pass
        return False

    def _check_last_shutdown(self) -> None:
        """
        Detect if last shutdown was dirty.

        Checks for crash indicators.
        """
        # Check for crash dump files (Linux)
        crash_indicators = [
            '/var/crash',
            '/var/log/kern.log',
        ]

        for path in crash_indicators:
            try:
                if os.path.exists(path):
                    # Check if modified recently (within boot time)
                    stat = os.stat(path)
                    if time.time() - stat.st_mtime < 60:
                        self._last_shutdown_clean = False
                        return
            except Exception:
                pass

    def mark_shutdown_initiated(self) -> None:
        """Mark that a clean shutdown has been initiated."""
        # Could write a marker file for next boot
        pass
