# M.A.R.I.A. - Plan Refaktoryzacji
> Version: 1.0 | Created: 2026-01-26

## Cel dokumentu

Etapowy plan migracji z obecnej struktury do docelowej architektury `agent_core/`.
Kazdy etap ma jasna definicje DONE i moze byc wykonany niezaleznie.

---

## Docelowa struktura katalogow

```
agent_core/
  homeostasis/
    __init__.py
    sensors/
      __init__.py
      resource_sensor.py    # RAM, CPU, disk
      cognitive_sensor.py   # LLM state, memory coherence
      thermal_sensor.py     # Temperature, throttle
      power_sensor.py       # Voltage, uptime (optional)
      time_sensor.py        # Circadian, idle tracking
    state_model.py          # Dataclasses: ResourceMetrics, CognitiveMetrics, SystemState
    interpreter.py          # Raw → semantic state conversion
    constraints.py          # ConstraintValidator, thresholds
    mode_regulator.py       # Mode enum, ModeRegulator, transitions
    actions.py              # CorrectiveActionGenerator, AlarmDispatcher
    core.py                 # HomeostasisCore, main_loop
    pulse.py                # HomeostasisPulseThread (100ms)
    api.py                  # HomeostasisInterface, HomeostasisEventBus
    snapshot.py             # Snapshot protocol, recovery

  memory/
    __init__.py
    manager.py              # MemoryManager interface
    episodic_store.py       # Episodic memory operations
    semantic_store.py       # Semantic graph operations
    snapshot_backend.py     # CoW snapshot implementation

  llm/
    __init__.py
    manager.py              # LLMManager interface
    latency_probe.py        # Quick latency measurement

  metacontrol/
    __init__.py
    controller.py           # MetaController interface

  executor/
    __init__.py
    module_executor.py      # ModuleExecutor, signal dispatch

  ui/
    __init__.py
    telemetry_api.py        # Read-only dashboard data
    operator_controls.py    # Safe operator commands

  tests/
    __init__.py
    test_sensors.py
    test_constraints.py
    test_mode_regulator.py
    test_core.py
    test_snapshot.py
    test_integration.py
```

---

## ETAP 0: Zachowanie stanu wyjsciowego

### Cel
Utworzenie snapshotu obecnego dzialajacego kodu przed jakakolwiek zmiana.

### Zadania
- [x] Utworz git tag: `v0.1-pre-refactor`
- [x] Utworz branch: `refactor/homeostasis`
- [x] Skopiuj caly `maria_core/` do `archive/maria_core_backup_YYYYMMDD/`
- [x] Zweryfikuj ze wszystkie importy dzialaja: `python -c "from main import main"`

### Definicja DONE
- [x] Tag `v0.1-pre-refactor` istnieje
- [x] Branch `refactor/homeostasis` aktywny
- [x] Backup w `archive/` z data
- [x] Importy dzialaja bez bledow

### Ryzyko
NISKIE - tylko backup, zero zmian w kodzie produkcyjnym

---

## ETAP 1: Szkielet struktury (empty files + __init__)

### Cel
Utworzenie calej struktury katalogow i pustych plikow z docstringami.

### Zadania
- [x] Utworz katalog `agent_core/` w root projektu
- [x] Utworz wszystkie podkatalogi zgodnie ze struktura powyzej
- [x] Utworz `__init__.py` w kazdym katalogu z odpowiednim docstringiem
- [x] Utworz puste pliki `.py` z docstringami opisujacymi cel modulu
- [x] Dodaj `agent_core/` do `sys.path` w `config.py`

### Przykladowy plik szkieletowy

```python
# agent_core/homeostasis/sensors/resource_sensor.py
"""
Resource sensor for homeostasis system.

Monitors:
- RAM usage (used, free, swap)
- CPU usage (%, load average)
- Disk usage (%, I/O queue depth)

Source of truth: homeostasis_spec.md section A.1
"""

from typing import Optional
from ..state_model import ResourceMetrics

class ResourceSensor:
    """Reads hardware resource metrics."""

    def __init__(self):
        # TODO: Etap 2 - adapter do resource_watchdog
        pass

    def read_metrics(self) -> Optional[ResourceMetrics]:
        """
        Non-blocking read of system metrics.

        Returns:
            ResourceMetrics or None on failure
        """
        raise NotImplementedError("Etap 2")
```

### Definicja DONE
- [x] Wszystkie katalogi istnieja
- [x] Wszystkie `__init__.py` z docstringami
- [x] Wszystkie `.py` z docstringami i `raise NotImplementedError`
- [x] Import `from agent_core.homeostasis import core` dziala (zwraca NotImplementedError przy uzyciu)

### Ryzyko
NISKIE - tylko puste pliki, stary kod dziala bez zmian

---

## ETAP 2: Adaptery (nowe moduly deleguja do starego kodu)

### Cel
Nowe moduly sa wrapperami wokol istniejacego kodu. Zero duplikacji logiki.

### Kolejnosc implementacji adapterow

| Priorytet | Adapter | Stary kod | Nowy modul |
|-----------|---------|-----------|------------|
| 1 | ResourceSensor | `resource_watchdog.py` | `sensors/resource_sensor.py` |
| 2 | MemoryManager | `memory_store.py` | `memory/manager.py` |
| 3 | SemanticStore | `semantic_graph.py` | `memory/semantic_store.py` |
| 4 | EpisodicStore | `brain_memory_integration.py` | `memory/episodic_store.py` |
| 5 | LLMManager | `ollama_brain.py` | `llm/manager.py` |
| 6 | MetaController | `meta_controller.py` | `metacontrol/controller.py` |

### Przyklad adaptera

```python
# agent_core/homeostasis/sensors/resource_sensor.py

from typing import Optional
from ..state_model import ResourceMetrics

# Import starego kodu
from maria_core.sys.resource_watchdog import ResourceWatchdog

class ResourceSensor:
    """Adapter wrapping ResourceWatchdog."""

    def __init__(self):
        self._watchdog = ResourceWatchdog()

    def read_metrics(self) -> Optional[ResourceMetrics]:
        """Delegate to old implementation, convert to new format."""
        try:
            old_stats = self._watchdog.get_system_stats()
            old_memory = self._watchdog.get_memory_usage()

            return ResourceMetrics(
                timestamp=time.time(),
                ram_used_mb=old_memory['used'] / 1024 / 1024,
                ram_total_mb=old_memory['total'] / 1024 / 1024,
                cpu_percent=old_stats['cpu_percent'],
                temp_c=50.0,  # TODO: Etap 3 - thermal sensor
                disk_used_pct=old_stats.get('disk_percent', 0),
                inference_latency_ms=0  # TODO: Etap 3 - latency probe
            )
        except Exception:
            return None
```

### Zasady adapterow

1. **Jeden adapter = jeden stary modul** - nie mieszac
2. **Adapter NIE dodaje logiki** - tylko konwersja formatu
3. **Adapter loguje ostrzezenia** - jesli stary kod zwraca nieoczekiwane dane
4. **Adapter ma fallback** - jesli stary kod rzuci exception, zwroc None/default

### Definicja DONE
- [x] Wszystkie 6 adapterow zaimplementowane
- [x] Kazdy adapter ma unit test sprawdzajacy delegacje
- [x] Stary kod dalej dziala niezaleznie
- [x] `python -c "from agent_core.homeostasis.sensors.resource_sensor import ResourceSensor; print(ResourceSensor().read_metrics())"` zwraca dane

### Ryzyko
SREDNIE - moga byc edge cases w konwersji formatow

---

## ETAP 3: Implementacja nowych modulow (wlasciwa logika)

### Cel
Implementacja modulow ktore nie maja odpowiednika w starym kodzie.

### Kolejnosc implementacji

| Priorytet | Modul | Zlozonosc | Zaleznosci |
|-----------|-------|-----------|------------|
| 1 | `state_model.py` | NISKA | brak |
| 2 | `interpreter.py` | SREDNIA | state_model |
| 3 | `constraints.py` | SREDNIA | state_model |
| 4 | `mode_regulator.py` | WYSOKA | constraints |
| 5 | `actions.py` | SREDNIA | mode_regulator |
| 6 | `pulse.py` | NISKA | sensors |
| 7 | `core.py` | WYSOKA | wszystko powyzej |
| 8 | `api.py` | SREDNIA | core |
| 9 | `snapshot.py` | WYSOKA | memory, state_model |

### Przyklad implementacji z spec

```python
# agent_core/homeostasis/constraints.py
"""
Constraint validator for homeostasis.
Source: homeostasis_spec.md section 6 (linie 1089-1139)
"""

from typing import List, Tuple
from .state_model import SystemState

class ConstraintValidator:
    """Check invariants and alarm thresholds."""

    # Thresholds from spec (section 5.1)
    THRESHOLDS = {
        "ram_critical_mb": 100,      # → SURVIVAL
        "ram_orange_mb": 200,        # → REDUCED
        "ram_yellow_mb": 500,        # → consider REDUCED
        "cpu_orange_pct": 80,        # → throttle
        "temp_critical_c": 95,       # → shutdown prep
        "temp_orange_c": 85,         # → REDUCED
        "coherence_low": 0.80,       # → alert
        "errors_high_rate": 20,      # per hour → alert
        "goal_stack_max": 25,        # → interrupt
    }

    def validate(self, state: dict) -> Tuple[bool, List[str]]:
        """
        Validate state against constraints.

        Returns:
            (all_ok, alerts) where alerts is list of strings
        """
        alerts = []

        # Critical (SURVIVAL triggers)
        if state.get("ram_available_mb", 0) < self.THRESHOLDS["ram_critical_mb"]:
            alerts.append("CRITICAL: OOM imminent")

        # ... rest of validation per spec

        return (len(alerts) == 0, alerts)
```

### Testy dla nowych modulow

Kazdy modul musi miec:
1. Unit test podstawowej funkcjonalnosci
2. Test edge cases (None inputs, extreme values)
3. Test zgodnosci ze spec (uzyj przykladow z spec jako test cases)

### Definicja DONE
- [x] Wszystkie 9 modulow zaimplementowane
- [x] Kazdy modul ma >= 3 unit testy
- [x] Testy pokrywaja przykladowe scenariusze ze spec
- [x] `HomeostasisCore` mozna zinstancjonowac i wywolac jeden tick

### Ryzyko
WYSOKIE - to glowna praca implementacyjna

---

## ETAP 4: Integracja i smoke test

### Cel
Polaczenie wszystkich modulow i uruchomienie pelnego cyklu homeostazy.

### Zadania

1. **Integracja z main.py**
   - [x] Dodaj import `HomeostasisCore` do main.py
   - [x] Uruchom homeostasis w osobnym watku przy starcie REPL
   - [x] Dodaj komende `/homeostasis status` do REPL

2. **Integracja z run_maria.py**
   - [x] Homeostasis kontroluje czy `learning_cycle` moze dzialac
   - [x] Jesli tryb REDUCED/SLEEP - pauzuj learning

3. **Smoke test**
   - [x] Uruchom system przez 5 minut
   - [x] Zweryfikuj ze logi homeostazy pojawiaja sie co sekunde
   - [x] Zweryfikuj ze tryb ACTIVE jest utrzymany przy normalnym obciazeniu
   - [x] Zasymuluj memory pressure - sprawdz czy przechodzi do REDUCED

4. **Testy integracyjne**
   - [x] `test_integration.py`: Pelny cykl sense→interpret→validate→decide→act
   - [x] Test mode transitions (ACTIVE↔REDUCED, ACTIVE→SLEEP)
   - [x] Test snapshot/recovery

### Przykladowy smoke test

```python
# agent_core/tests/test_integration.py

import time
import threading
from agent_core.homeostasis.core import HomeostasisCore

def test_full_cycle():
    """Smoke test: run 10 ticks of homeostasis."""

    # Mock dependencies
    memory = MockMemoryManager()
    llm = MockLLMManager()
    executor = MockExecutor()

    core = HomeostasisCore(memory, llm, executor)

    # Run in thread
    thread = threading.Thread(target=core.main_loop)
    thread.daemon = True
    thread.start()

    # Let it run for 10 seconds
    time.sleep(10)

    # Assertions
    assert core.state.mode.value in ["active", "reduced", "sleep", "survival"]
    assert 0 <= core.state.health_score <= 1
    assert len(core.audit_log) >= 1  # At least one log entry
```

### Definicja DONE
- [x] `main.py` uruchamia homeostasis w tle
- [x] `/homeostasis status` pokazuje aktualny tryb i health
- [x] System dziala stabilnie przez 30 minut bez crashy
- [x] Logi pokazuja regularne ticki (co ~1s)
- [x] Wszystkie testy integracyjne przechodza

### Ryzyko
SREDNIE - moga byc problemy z watkami i synchronizacja

---

## ETAP 5: Cleanup i dokumentacja (opcjonalny)

### Cel
Usuniecie duplikacji i aktualizacja dokumentacji.

### Zadania
- [ ] Usun stary kod ktory jest w 100% zastapiony adapterami
- [x] Zaktualizuj `ARCHITECTURE.md` z nowa struktura
- [x] Zaktualizuj `MAP_HOMEOSTASIS.md` - zmien statusy na `implemented`/`tested`
- [ ] Dodaj sekcje "Homeostasis" do `README.md` (jesli istnieje)

### Definicja DONE
- [ ] Zero duplikacji kodu
- [x] Dokumentacja zgodna z kodem
- [x] Wszystkie statusy w MAP_HOMEOSTASIS.md zaktualizowane

### Ryzyko
NISKIE - tylko cleanup

### Status: IN PROGRESS
- Dokumentacja zaktualizowana
- Usuniecie starego kodu planowane na kolejna sesje

---

## Timeline (szacunkowy)

| Etap | Sesje | Kumulatywny czas |
|------|-------|------------------|
| Etap 0 | 0.5 sesji | 0.5 |
| Etap 1 | 1 sesja | 1.5 |
| Etap 2 | 2 sesje | 3.5 |
| Etap 3 | 4-5 sesji | 7.5-8.5 |
| Etap 4 | 2 sesje | 9.5-10.5 |
| Etap 5 | 1 sesja | 10.5-11.5 |

**TOTAL: ~10-12 sesji roboczych**

---

## Checkpointy bezpieczenstwa

Po kazdym etapie:
1. [ ] Commit z opisem "Etap X: [krotki opis]"
2. [ ] Zweryfikuj ze stary kod dalej dziala
3. [ ] Zaktualizuj STABILIZATION_PLAN.md jesli naprawiono bugi
4. [ ] Zaktualizuj CHANGELOG.md

---

## Decyzje do podjecia przed startem

### D-001: Czy zachowac kompatybilnosc wsteczna?
**Opcje:**
A) TAK - stare importy dalej dzialaja (np. `from maria_core.sys.resource_watchdog import ...`)
B) NIE - wymus migracje na nowe importy

**Rekomendacja:** A (TAK) na czas Etapu 2-3, potem B w Etapie 5

### D-002: Gdzie umiesci agent_core/?
**Opcje:**
A) W root projektu: `./agent_core/`
B) Jako submodul maria_core: `./maria_core/agent_core/`

**Rekomendacja:** A (root) - czystsza separacja

### D-003: Python threading vs asyncio?
**Opcje:**
A) threading (jak w spec)
B) asyncio (nowoczesniejsze)

**Rekomendacja:** A (threading) - zgodnosc ze spec, mniej zmian w istniejacym kodzie

---

*Ten plan jest dokumentem zywym - aktualizuj statusy checkboxow w miare postepow.*
