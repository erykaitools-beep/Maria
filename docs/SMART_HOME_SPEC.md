# M.A.R.I.A. Smart Home Integration Specification

> Maria jako centralny mozg inteligentnego domu

## 1. Architektura

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
        | (kamery) |   | (Shelly) |   | (Android)|
        +----------+   +----------+   +----------+
              |              |              |
        [USB/WiFi]    [REST API]     [ADB/Tasker]
```

## 2. Warstwa IoT - Urzadzenia

### 2.1 Wspierane protokoly

| Protokol | Priorytet | Urzadzenia |
|----------|-----------|------------|
| **REST API (HTTP)** | Wysoki | Shelly, Tasmota, ESPHome |
| MQTT | Sredni | Wszystkie IoT |
| WebSocket | Niski | Real-time updates |

### 2.2 Rekomendowane urzadzenia

**Gniazdka smart:**
- Shelly Plug S / Plus (~60-80 zl) - lokalne API, bez chmury
- Sonoff S26 z Tasmota (~50 zl) - wymaga flashowania
- Tuya z Tasmota (~40 zl) - wymaga flashowania

**Czujniki:**
- Shelly Door/Window - kontaktrony
- Shelly Motion - ruch
- Shelly H&T - temperatura/wilgotnosc

**Oswietlenie:**
- Shelly Dimmer - sciemniacz
- Shelly RGBW2 - LED RGB
- Tasmota bulbs - zarowki WiFi

### 2.3 Konfiguracja sieci

```
[Router glowny]
    |
    +--- VLAN 1: Siec domowa (laptop, telefon)
    |       IP: 192.168.1.0/24
    |
    +--- VLAN 2: Siec IoT (Shelly, kamery)
    |       IP: 192.168.2.0/24
    |
    +--- VLAN 3: Siec Maria (serwer Maria)
            IP: 192.168.3.0/24
            Ma dostep do VLAN 1 i 2
```

**Prostsza opcja (Guest Network):**
- Siec glowna: urzadzenia osobiste
- Guest Network: urzadzenia IoT
- Maria na sieci glownej z dostepem do Guest

## 3. API Urzadzen

### 3.1 Shelly REST API

```python
# Wlacz urzadzenie
GET http://192.168.2.10/relay/0?turn=on

# Wylacz urzadzenie
GET http://192.168.2.10/relay/0?turn=off

# Status
GET http://192.168.2.10/status

# Przyklad odpowiedzi status:
{
    "relays": [{"ison": true, "power": 45.2}],
    "meters": [{"power": 45.2, "total": 12345}]
}
```

### 3.2 Tasmota REST API

```python
# Wlacz
GET http://192.168.2.20/cm?cmnd=Power%20On

# Wylacz
GET http://192.168.2.20/cm?cmnd=Power%20Off

# Status
GET http://192.168.2.20/cm?cmnd=Status%200
```

## 4. Modul smart_home/

### 4.1 Struktura

```
agent_core/
    smart_home/
        __init__.py
        device_registry.py    # Rejestr urzadzen
        shelly_client.py      # Klient Shelly API
        tasmota_client.py     # Klient Tasmota API
        automation_engine.py  # Silnik automatyzacji
        rules.py              # Reguly (trigger -> action)
```

### 4.2 Interfejs bazowy

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
    """Bazowy interfejs dla urzadzen smart home."""

    @abstractmethod
    def get_state(self) -> DeviceState:
        """Pobierz aktualny stan."""
        pass

    @abstractmethod
    def set_state(self, state: DeviceState) -> bool:
        """Ustaw stan. Zwraca True jesli sukces."""
        pass

    @abstractmethod
    def get_info(self) -> DeviceInfo:
        """Pobierz informacje o urzadzeniu."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Sprawdz czy urzadzenie jest dostepne."""
        pass
```

### 4.3 Shelly Client

```python
import requests
from typing import Optional


class ShellyDevice(SmartDevice):
    """Klient dla urzadzen Shelly."""

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
        """Pobierz aktualne zuzycie energii (W)."""
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
    """Rejestr wszystkich urzadzen smart home."""

    def __init__(self):
        self._devices: Dict[str, SmartDevice] = {}

    def register(self, device: SmartDevice) -> None:
        """Zarejestruj urzadzenie."""
        info = device.get_info()
        self._devices[info.id] = device

    def get(self, device_id: str) -> Optional[SmartDevice]:
        """Pobierz urzadzenie po ID."""
        return self._devices.get(device_id)

    def get_by_name(self, name: str) -> Optional[SmartDevice]:
        """Pobierz urzadzenie po nazwie."""
        for device in self._devices.values():
            if device.get_info().name.lower() == name.lower():
                return device
        return None

    def get_by_room(self, room: str) -> List[SmartDevice]:
        """Pobierz wszystkie urzadzenia w pokoju."""
        return [
            d for d in self._devices.values()
            if d.get_info().room and d.get_info().room.lower() == room.lower()
        ]

    def list_all(self) -> List[DeviceInfo]:
        """Lista wszystkich urzadzen."""
        return [d.get_info() for d in self._devices.values()]

    def scan_network(self, subnet: str = "192.168.2") -> List[str]:
        """Skanuj siec w poszukiwaniu urzadzen Shelly."""
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
    TIME = "time"           # O konkretnej godzinie
    EVENT = "event"         # Na zdarzenie (ruch, drzwi)
    STATE = "state"         # Zmiana stanu urzadzenia
    CONDITION = "condition" # Warunek (np. moc > 100W)


@dataclass
class AutomationRule:
    id: str
    name: str
    trigger_type: TriggerType
    trigger_config: dict
    action: Callable[[], Any]
    enabled: bool = True


class AutomationEngine:
    """Silnik automatyzacji - reaguje na zdarzenia."""

    def __init__(self, registry: DeviceRegistry):
        self.registry = registry
        self._rules: List[AutomationRule] = []
        self._running = False

    def add_rule(self, rule: AutomationRule) -> None:
        """Dodaj regule automatyzacji."""
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Usun regule."""
        for i, rule in enumerate(self._rules):
            if rule.id == rule_id:
                del self._rules[i]
                return True
        return False

    def process_event(self, event_type: str, event_data: dict) -> None:
        """Przetworz zdarzenie i wykonaj pasujace reguly."""
        for rule in self._rules:
            if not rule.enabled:
                continue

            if rule.trigger_type == TriggerType.EVENT:
                if rule.trigger_config.get("event") == event_type:
                    self._execute_rule(rule, event_data)

    def _execute_rule(self, rule: AutomationRule, context: dict) -> None:
        """Wykonaj akcje reguly."""
        try:
            rule.action()
            print(f"[Automation] Executed: {rule.name}")
        except Exception as e:
            print(f"[Automation] Error in {rule.name}: {e}")


# Przyklad uzycia:
#
# registry = DeviceRegistry()
# registry.register(ShellyDevice("192.168.2.10", "Czajnik", "kettle", "Kuchnia"))
#
# engine = AutomationEngine(registry)
#
# # Regula: gdy wykryto auto na kamerze -> wlacz czajnik
# engine.add_rule(AutomationRule(
#     id="auto_kettle",
#     name="Wlacz czajnik gdy przyjezdzam",
#     trigger_type=TriggerType.EVENT,
#     trigger_config={"event": "car_detected"},
#     action=lambda: registry.get("kettle").turn_on()
# ))
```

## 5. Integracja z Maria

### 5.1 REPL Commands

```
/devices              - lista urzadzen
/device <id> on       - wlacz urzadzenie
/device <id> off      - wylacz urzadzenie
/device <id> status   - status urzadzenia
/rooms                - lista pokojow
/room <name> off      - wylacz wszystko w pokoju
/scan                 - skanuj siec
/rules                - lista regul automatyzacji
```

### 5.2 Integracja z Vision

```python
# W module vision - po wykryciu obiektu:
def on_object_detected(object_type: str, confidence: float):
    if object_type == "car" and confidence > 0.8:
        automation_engine.process_event("car_detected", {
            "confidence": confidence,
            "timestamp": time.time()
        })
```

### 5.3 Integracja z Homeostasis

```python
# W SURVIVAL mode - wylacz wszystkie urzadzenia nie-krytyczne
def on_mode_change(old_mode: Mode, new_mode: Mode):
    if new_mode == Mode.SURVIVAL:
        for device in registry.list_all():
            if device.room != "Server":  # Nie wylaczaj serwera
                registry.get(device.id).turn_off()
```

## 6. Bezpieczenstwo

### 6.1 Zasady

1. **Lokalne API tylko** - zadnej chmury (Tuya cloud, etc.)
2. **Izolacja sieci** - IoT na osobnym VLAN/Guest
3. **Firewall** - IoT nie ma dostepu do internetu
4. **Autoryzacja** - PIN/haslo dla krytycznych akcji
5. **Audit log** - logowanie wszystkich akcji

### 6.2 Krytyczne urzadzenia

Urzadzenia wymagajace potwierdzenia:
- Zamki do drzwi
- Alarmy
- Ogrzewanie/klimatyzacja
- Brama garazowa

```python
CRITICAL_DEVICES = ["door_lock", "alarm", "garage"]

def safe_action(device_id: str, action: str) -> bool:
    if device_id in CRITICAL_DEVICES:
        # Wymagaj potwierdzenia przez Web UI lub glos
        return request_confirmation(device_id, action)
    return True
```

## 7. Mobile Body (Android)

### 7.1 Rola

Android jako "cialo mobilne" Marii:
- Kamera mobilna (IP Webcam)
- Mikrofon (rozpoznawanie glosu)
- Glosnik (TTS - Maria mowi)
- GPS (lokalizacja)
- Sensory (akcelerometr, zyroskop)

### 7.2 Aplikacje

| Aplikacja | Funkcja | API |
|-----------|---------|-----|
| IP Webcam | Kamera przez WiFi | HTTP stream |
| Termux | Python/Linux | SSH/ADB |
| Tasker | Automatyzacja | Intent/HTTP |
| AutoVoice | Komendy glosowe | Tasker plugin |
| MacroDroid | Prostsze Tasker | HTTP webhook |

### 7.3 Konfiguracja IP Webcam

```
URL streamu: http://192.168.1.100:8080/video
URL zdjecia: http://192.168.1.100:8080/shot.jpg
URL audio:   http://192.168.1.100:8080/audio.wav

# W Python:
import cv2
cap = cv2.VideoCapture("http://192.168.1.100:8080/video")
```

### 7.4 Termux + Maria

```bash
# Na Android w Termux:
pkg install python
pip install flask requests

# Prosty agent:
python maria_mobile_agent.py
```

```python
# maria_mobile_agent.py
from flask import Flask, jsonify
import subprocess

app = Flask(__name__)

@app.route("/speak/<text>")
def speak(text):
    # TTS przez Termux:API
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

## 8. Lista zakupow

### Faza 1 - Podstawy (~500 zl)
- [ ] Kamera USB Logitech C270 (~100 zl)
- [ ] Shelly Plug S x3 (~200 zl)
- [ ] Android uzywany (Samsung S8/Xiaomi) (~200 zl)

### Faza 2 - Rozszerzenie (~400 zl)
- [ ] Shelly Door/Window x2 (~100 zl)
- [ ] Shelly Motion (~80 zl)
- [ ] Shelly H&T (temp/wilgotnosc) (~80 zl)
- [ ] Router z VLAN (Mikrotik hAP) (~150 zl)

### Faza 3 - Zaawansowane (~500 zl)
- [ ] Druga kamera (zewnetrzna IP) (~200 zl)
- [ ] Shelly Dimmer x2 (~150 zl)
- [ ] ESP32 + czujniki DIY (~100 zl)
- [ ] Mikrofon USB (~50 zl)

## 9. Harmonogram implementacji

### Sprint 1: Device Registry (4h)
- [ ] Interfejs SmartDevice
- [ ] ShellyDevice implementation
- [ ] DeviceRegistry
- [ ] Testy jednostkowe

### Sprint 2: REPL Integration (2h)
- [ ] Komendy /device, /devices
- [ ] Komendy /room, /rooms
- [ ] Komenda /scan

### Sprint 3: Automation Engine (4h)
- [ ] AutomationRule dataclass
- [ ] AutomationEngine
- [ ] Podstawowe triggery
- [ ] Integracja z Vision (event dispatch)

### Sprint 4: Mobile Body (4h)
- [ ] IP Webcam integration
- [ ] Termux agent script
- [ ] TTS (Maria mowi)
- [ ] Lokalizacja GPS

---

*Specyfikacja: 2026-02-02*
*Wersja: 1.0*
