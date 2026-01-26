"""
Homeostasis Sensor Layer

Collects raw metrics from system and cognitive sources.
Spec reference: homeostasis_spec.md section 1.1

Sensors:
- ResourceSensor: RAM, CPU, disk monitoring (wraps resource_watchdog.py)
- CognitiveSensor: LLM state, memory coherence, error rates
- ThermalSensor: CPU temperature, throttle state
- PowerSensor: Voltage, uptime (optional, for SBC)
- TimeSensor: Circadian rhythms, idle tracking
"""

from .resource_sensor import ResourceSensor
from .cognitive_sensor import CognitiveSensor
from .thermal_sensor import ThermalSensor
from .power_sensor import PowerSensor
from .time_sensor import TimeSensor

__all__ = [
    "ResourceSensor",
    "CognitiveSensor",
    "ThermalSensor",
    "PowerSensor",
    "TimeSensor",
]
