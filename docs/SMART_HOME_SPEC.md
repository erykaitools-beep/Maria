# M.A.R.I.A. Smart Home Integration Specification

> Maria as the central brain of a smart home

> **[DEFERRED - NOT IMPLEMENTED]** This document is a design specification, not a description
> of running code. There is no `agent_core/smart_home/` package in the repository, no device
> clients, and none of the REPL commands listed below are registered. Phase E is DEFERRED
> pending IoT hardware (see `docs/ROADMAP.md`). All code in this file is proposed design,
> written in the indicative mood for brevity; treat it as a plan, not as runtime truth.

## 1. Architecture

```
                    +------------------+
                    |     M.A.R.I.A.   |
                    |   (Main Brain)   |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
        +-----v----+   +-----v----+   +-----v----+
        |  Vision  |   |   IoT    |   |  Mobile  |
        |(cameras) |   | (Shelly) |   | (Android)|
        +----------+   +----------+   +----------+
              |              |              |
        [USB/WiFi]    [REST API]     [ADB/Tasker]
```

## 2. IoT Layer - Devices

### 2.1 Supported protocols

| Protocol | Priority | Devices |
|----------|-----------|------------|
| **REST API (HTTP)** | High | Shelly, Tasmota, ESPHome |
| MQTT | Medium | All IoT |
| WebSocket | Low | Real-time updates |

### 2.2 Recommended devices

**Smart plugs:**
- Shelly Plug S / Plus (~60-80 PLN) - local API, no cloud
- Sonoff S26 with Tasmota (~50 PLN) - requires flashing
- Tuya with Tasmota (~40 PLN) - requires flashing

**Sensors:**
- Shelly Door/Window - reed switches
- Shelly Motion - motion
- Shelly H&T - temperature/humidity

**Lighting:**
- Shelly Dimmer - dimmer
- Shelly RGBW2 - RGB LED
- Tasmota bulbs - WiFi bulbs

### 2.3 Network configuration

```
[Main router]
    |
    +--- VLAN 1: Home network (laptop, phone)
    |       IP: 192.168.1.0/24
    |
    +--- VLAN 2: IoT network (Shelly, cameras)
    |       IP: 192.168.2.0/24
    |
    +--- VLAN 3: Maria network (Maria server)
            IP: 192.168.3.0/24
            Has access to VLAN 1 and 2
```

**Simpler option (Guest Network):**
- Main network: personal devices
- Guest Network: IoT devices
- Maria on the main network with access to Guest

## 3. Device APIs

### 3.1 Shelly REST API

```python
# Turn the device on
GET http://192.168.2.10/relay/0?turn=on

# Turn the device off
GET http://192.168.2.10/relay/0?turn=off

# Status
GET http://192.168.2.10/status

# Example status response:
{
    "relays": [{"ison": true, "power": 45.2}],
    "meters": [{"power": 45.2, "total": 12345}]
}
```

### 3.2 Tasmota REST API

```python
# Turn on
GET http://192.168.2.20/cm?cmnd=Power%20On

# Turn off
GET http://192.168.2.20/cm?cmnd=Power%20Off

# Status
GET http://192.168.2.20/cm?cmnd=Status%200
```

## 4. The smart_home/ module

### 4.1 Structure

```
agent_core/
    smart_home/
        __init__.py
        device_registry.py    # Device registry
        shelly_client.py      # Shelly API client
        tasmota_client.py     # Tasmota API client
        automation_engine.py  # Automation engine
        rules.py              # Rules (trigger -> action)
```

### 4.2 Base interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum


class DeviceType(Enum):
    SWITCH = "switch"      # on/off
    DIMMER = "dimmer"      # 0-100%
    SENSOR = "sensor"      # read-only
    RGB = "rgb"            # color


class DeviceState(Enum):
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


@dataclass
class DeviceInfo:
    id: str
    name: str
    device_type: DeviceType
    ip_address: str
    protocol: str  # "shelly", "tasmota", "mqtt"
    room: Optional[str] = None


class SmartDevice(ABC):
    """Base interface for smart home devices."""

    @abstractmethod
    def get_state(self) -> DeviceState:
        """Return the current state."""
        pass

    @abstractmethod
    def set_state(self, state: DeviceState) -> bool:
        """Set the state. Returns True on success."""
        pass

    @abstractmethod
    def get_info(self) -> DeviceInfo:
        """Return device information."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether the device is reachable."""
        pass
```

### 4.3 Shelly Client

```python
import requests
from typing import Optional


class ShellyDevice(SmartDevice):
    """Client for Shelly devices."""

    def __init__(self, ip: str, name: str, device_id: str, room: str = None):
        self.ip = ip
        self.name = name
        self.device_id = device_id
        self.room = room
        self._timeout = 5.0

    def get_state(self) -> DeviceState:
        try:
            resp = requests.get(
                f"http://{self.ip}/relay/0",
                timeout=self._timeout
            )
            data = resp.json()
            return DeviceState.ON if data.get("ison") else DeviceState.OFF
        except Exception:
            return DeviceState.UNKNOWN

    def set_state(self, state: DeviceState) -> bool:
        try:
            action = "on" if state == DeviceState.ON else "off"
            resp = requests.get(
                f"http://{self.ip}/relay/0?turn={action}",
                timeout=self._timeout
            )
            return resp.status_code == 200
        except Exception:
            return False

    def turn_on(self) -> bool:
        return self.set_state(DeviceState.ON)

    def turn_off(self) -> bool:
        return self.set_state(DeviceState.OFF)

    def toggle(self) -> bool:
        current = self.get_state()
        new_state = DeviceState.OFF if current == DeviceState.ON else DeviceState.ON
        return self.set_state(new_state)

    def get_power(self) -> Optional[float]:
        """Return the current power draw (W)."""
        try:
            resp = requests.get(
                f"http://{self.ip}/status",
                timeout=self._timeout
            )
            data = resp.json()
            meters = data.get("meters", [])
            if meters:
                return meters[0].get("power", 0.0)
            return None
        except Exception:
            return None

    def is_available(self) -> bool:
        try:
            resp = requests.get(
                f"http://{self.ip}/shelly",
                timeout=2.0
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_info(self) -> DeviceInfo:
        return DeviceInfo(
            id=self.device_id,
            name=self.name,
            device_type=DeviceType.SWITCH,
            ip_address=self.ip,
            protocol="shelly",
            room=self.room
        )
```

### 4.4 Device Registry

```python
from typing import Dict, List, Optional


class DeviceRegistry:
    """Registry of all smart home devices."""

    def __init__(self):
        self._devices: Dict[str, SmartDevice] = {}

    def register(self, device: SmartDevice) -> None:
        """Register a device."""
        info = device.get_info()
        self._devices[info.id] = device

    def get(self, device_id: str) -> Optional[SmartDevice]:
        """Return a device by ID."""
        return self._devices.get(device_id)

    def get_by_name(self, name: str) -> Optional[SmartDevice]:
        """Return a device by name."""
        for device in self._devices.values():
            if device.get_info().name.lower() == name.lower():
                return device
        return None

    def get_by_room(self, room: str) -> List[SmartDevice]:
        """Return all devices in a room."""
        return [
            d for d in self._devices.values()
            if d.get_info().room and d.get_info().room.lower() == room.lower()
        ]

    def list_all(self) -> List[DeviceInfo]:
        """List all devices."""
        return [d.get_info() for d in self._devices.values()]

    def scan_network(self, subnet: str = "192.168.2") -> List[str]:
        """Scan the network for Shelly devices."""
        found = []
        for i in range(1, 255):
            ip = f"{subnet}.{i}"
            try:
                resp = requests.get(f"http://{ip}/shelly", timeout=0.5)
                if resp.status_code == 200:
                    found.append(ip)
            except Exception:
                pass
        return found
```

### 4.5 Automation Engine

```python
from dataclasses import dataclass
from typing import Callable, List, Any
from enum import Enum
import time


class TriggerType(Enum):
    TIME = "time"           # At a specific time of day
    EVENT = "event"         # On an event (motion, door)
    STATE = "state"         # Device state change
    CONDITION = "condition" # Condition (e.g. power > 100W)


@dataclass
class AutomationRule:
    id: str
    name: str
    trigger_type: TriggerType
    trigger_config: dict
    action: Callable[[], Any]
    enabled: bool = True


class AutomationEngine:
    """Automation engine - reacts to events."""

    def __init__(self, registry: DeviceRegistry):
        self.registry = registry
        self._rules: List[AutomationRule] = []
        self._running = False

    def add_rule(self, rule: AutomationRule) -> None:
        """Add an automation rule."""
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule."""
        for i, rule in enumerate(self._rules):
            if rule.id == rule_id:
                del self._rules[i]
                return True
        return False

    def process_event(self, event_type: str, event_data: dict) -> None:
        """Process an event and run the matching rules."""
        for rule in self._rules:
            if not rule.enabled:
                continue

            if rule.trigger_type == TriggerType.EVENT:
                if rule.trigger_config.get("event") == event_type:
                    self._execute_rule(rule, event_data)

    def _execute_rule(self, rule: AutomationRule, context: dict) -> None:
        """Execute a rule action."""
        try:
            rule.action()
            print(f"[Automation] Executed: {rule.name}")
        except Exception as e:
            print(f"[Automation] Error in {rule.name}: {e}")


# Example usage:
#
# registry = DeviceRegistry()
# registry.register(ShellyDevice("192.168.2.10", "Kettle", "kettle", "Kitchen"))
#
# engine = AutomationEngine(registry)
#
# # Rule: when a car is detected on camera -> turn the kettle on
# engine.add_rule(AutomationRule(
#     id="auto_kettle",
#     name="Turn the kettle on when I arrive",
#     trigger_type=TriggerType.EVENT,
#     trigger_config={"event": "car_detected"},
#     action=lambda: registry.get("kettle").turn_on()
# ))
```

## 5. Integration with Maria

### 5.1 REPL Commands

```
/devices              - list devices
/device <id> on       - turn a device on
/device <id> off      - turn a device off
/device <id> status   - device status
/rooms                - list rooms
/room <name> off      - turn everything off in a room
/scan                 - scan the network
/rules                - list automation rules
```

### 5.2 Integration with Vision

```python
# In the vision module - after an object is detected:
def on_object_detected(object_type: str, confidence: float):
    if object_type == "car" and confidence > 0.8:
        automation_engine.process_event("car_detected", {
            "confidence": confidence,
            "timestamp": time.time()
        })
```

### 5.3 Integration with Homeostasis

```python
# In SURVIVAL mode - turn off all non-critical devices
def on_mode_change(old_mode: Mode, new_mode: Mode):
    if new_mode == Mode.SURVIVAL:
        for device in registry.list_all():
            if device.room != "Server":  # Do not turn off the server
                registry.get(device.id).turn_off()
```

## 6. Security

### 6.1 Principles

1. **Local API only** - no cloud (Tuya cloud, etc.)
2. **Network isolation** - IoT on a separate VLAN/Guest
3. **Firewall** - IoT has no internet access
4. **Authorization** - PIN/password for critical actions
5. **Audit log** - log every action

### 6.2 Critical devices

Devices that require confirmation:
- Door locks
- Alarms
- Heating/air conditioning
- Garage door

```python
CRITICAL_DEVICES = ["door_lock", "alarm", "garage"]

def safe_action(device_id: str, action: str) -> bool:
    if device_id in CRITICAL_DEVICES:
        # Require confirmation via the Web UI or voice
        return request_confirmation(device_id, action)
    return True
```

## 7. Mobile Body (Android)

### 7.1 Role

Android as Maria's "mobile body":
- Mobile camera (IP Webcam)
- Microphone (speech recognition)
- Speaker (TTS - Maria speaks)
- GPS (location)
- Sensors (accelerometer, gyroscope)

### 7.2 Applications

| Application | Function | API |
|-----------|---------|-----|
| IP Webcam | Camera over WiFi | HTTP stream |
| Termux | Python/Linux | SSH/ADB |
| Tasker | Automation | Intent/HTTP |
| AutoVoice | Voice commands | Tasker plugin |
| MacroDroid | Simpler Tasker | HTTP webhook |

### 7.3 IP Webcam configuration

```
Stream URL:   http://192.168.1.100:8080/video
Snapshot URL: http://192.168.1.100:8080/shot.jpg
Audio URL:    http://192.168.1.100:8080/audio.wav

# In Python:
import cv2
cap = cv2.VideoCapture("http://192.168.1.100:8080/video")
```

### 7.4 Termux + Maria

```bash
# On Android, in Termux:
pkg install python
pip install flask requests

# Simple agent:
python maria_mobile_agent.py
```

```python
# maria_mobile_agent.py
from flask import Flask, jsonify
import subprocess

app = Flask(__name__)

@app.route("/speak/<text>")
def speak(text):
    # TTS via Termux:API
    subprocess.run(["termux-tts-speak", text])
    return jsonify({"status": "ok"})

@app.route("/location")
def location():
    result = subprocess.run(
        ["termux-location"],
        capture_output=True,
        text=True
    )
    return result.stdout

@app.route("/battery")
def battery():
    result = subprocess.run(
        ["termux-battery-status"],
        capture_output=True,
        text=True
    )
    return result.stdout

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

## 8. Shopping list

### Phase 1 - Basics (~500 PLN)
- [ ] Logitech C270 USB camera (~100 PLN)
- [ ] Shelly Plug S x3 (~200 PLN)
- [ ] Used Android phone (Samsung S8/Xiaomi) (~200 PLN)

### Phase 2 - Expansion (~400 PLN)
- [ ] Shelly Door/Window x2 (~100 PLN)
- [ ] Shelly Motion (~80 PLN)
- [ ] Shelly H&T (temp/humidity) (~80 PLN)
- [ ] Router with VLAN support (Mikrotik hAP) (~150 PLN)

### Phase 3 - Advanced (~500 PLN)
- [ ] Second camera (external IP) (~200 PLN)
- [ ] Shelly Dimmer x2 (~150 PLN)
- [ ] ESP32 + DIY sensors (~100 PLN)
- [ ] USB microphone (~50 PLN)

## 9. Implementation schedule

### Sprint 1: Device Registry (4h)
- [ ] SmartDevice interface
- [ ] ShellyDevice implementation
- [ ] DeviceRegistry
- [ ] Unit tests

### Sprint 2: REPL Integration (2h)
- [ ] /device, /devices commands
- [ ] /room, /rooms commands
- [ ] /scan command

### Sprint 3: Automation Engine (4h)
- [ ] AutomationRule dataclass
- [ ] AutomationEngine
- [ ] Basic triggers
- [ ] Vision integration (event dispatch)

### Sprint 4: Mobile Body (4h)
- [ ] IP Webcam integration
- [ ] Termux agent script
- [ ] TTS (Maria speaks)
- [ ] GPS location

---

*Specification: 2026-02-02*
*Version: 1.0*
