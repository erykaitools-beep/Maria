"""
Thermal Sensor - Temperature and throttle monitoring

Monitors (spec section 1.1.A):
- Temperature: CPU, SoC (if available)
- Throttle state: whether CPU is throttling
- Fan speed: if hardware monitors it

Spec reference: homeostasis_spec.md lines 33-36
"""

import os
import time
from typing import Optional, Tuple
from dataclasses import dataclass

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class ThermalMetrics:
    """Thermal sensor readings."""
    timestamp: float
    cpu_temp_c: float
    is_throttling: bool
    fan_speed_rpm: Optional[int]


class ThermalSensor:
    """
    Reads thermal metrics from system.

    Cross-platform implementation:
    - Linux: /sys/class/thermal, /sys/class/hwmon
    - Windows: WMI (limited support)
    - Fallback: psutil.sensors_temperatures()

    Spec: homeostasis_spec.md lines 976-988
    """

    # Temperature thresholds from spec
    TEMP_ORANGE_C = 85
    TEMP_CRITICAL_C = 95

    def __init__(self):
        """Initialize thermal sensor."""
        self._last_temp = 50.0  # Default assumption
        self._throttle_detected = False

    def read_metrics(self) -> ThermalMetrics:
        """
        Read thermal metrics.

        Returns:
            ThermalMetrics with current temperature and throttle state
        """
        temp = self._read_temperature()
        throttling = self._check_throttling(temp)
        fan_speed = self._read_fan_speed()

        self._last_temp = temp
        self._throttle_detected = throttling

        return ThermalMetrics(
            timestamp=time.time(),
            cpu_temp_c=temp,
            is_throttling=throttling,
            fan_speed_rpm=fan_speed,
        )

    def get_temperature(self) -> float:
        """Get current CPU temperature in Celsius."""
        return self._read_temperature()

    def is_critical(self) -> bool:
        """Check if temperature is at critical level."""
        return self._last_temp >= self.TEMP_CRITICAL_C

    def is_warning(self) -> bool:
        """Check if temperature is at warning level."""
        return self._last_temp >= self.TEMP_ORANGE_C

    def _read_temperature(self) -> float:
        """
        Read CPU temperature.

        Tries multiple sources in order of preference.
        """
        # Try Linux thermal zone first
        temp = self._read_linux_thermal()
        if temp is not None:
            return temp

        # Try psutil sensors
        temp = self._read_psutil_temp()
        if temp is not None:
            return temp

        # Fallback to default
        return 50.0

    def _read_linux_thermal(self) -> Optional[float]:
        """Read temperature from Linux thermal zone."""
        thermal_paths = [
            '/sys/class/thermal/thermal_zone0/temp',
            '/sys/class/thermal/thermal_zone1/temp',
            '/sys/devices/virtual/thermal/thermal_zone0/temp',
        ]

        for path in thermal_paths:
            try:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        # Value is in millidegrees
                        return int(f.read().strip()) / 1000.0
            except (IOError, ValueError):
                continue

        return None

    def _read_psutil_temp(self) -> Optional[float]:
        """Read temperature using psutil."""
        if not HAS_PSUTIL:
            return None

        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return None

            # Try common sensor names
            for name in ['coretemp', 'cpu_thermal', 'k10temp', 'zenpower', 'acpitz']:
                if name in temps:
                    readings = temps[name]
                    if readings:
                        # Return highest temperature
                        return max(r.current for r in readings)

            # Fallback: return first available
            for readings in temps.values():
                if readings:
                    return max(r.current for r in readings)

        except Exception:
            pass

        return None

    def _check_throttling(self, current_temp: float) -> bool:
        """
        Detect if CPU is throttling.

        Uses temperature as primary indicator.
        """
        # Simple heuristic: if temp is high, assume throttling possible
        if current_temp >= self.TEMP_ORANGE_C:
            return True

        # Try to read throttle state on Linux
        throttle_path = '/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq'
        max_freq_path = '/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq'

        try:
            if os.path.exists(throttle_path) and os.path.exists(max_freq_path):
                with open(throttle_path, 'r') as f:
                    cur_freq = int(f.read().strip())
                with open(max_freq_path, 'r') as f:
                    max_freq = int(f.read().strip())

                # If current frequency is significantly below max, likely throttling
                if cur_freq < max_freq * 0.8:
                    return True
        except (IOError, ValueError):
            pass

        return False

    def _read_fan_speed(self) -> Optional[int]:
        """Read fan speed in RPM if available."""
        if not HAS_PSUTIL:
            return None

        try:
            fans = psutil.sensors_fans()
            if fans:
                for readings in fans.values():
                    if readings:
                        return int(readings[0].current)
        except Exception:
            pass

        return None
