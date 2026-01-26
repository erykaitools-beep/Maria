# M.A.R.I.A. - Mapa Wymagan Homeostazy
> Version: 1.0 | Created: 2026-01-26

## Cel dokumentu

Mapowanie wymagan z `homeostasis_spec.md` na docelowa strukture modulow.
Przed jakakolwiek refaktoryzacja - kazdy element specyfikacji ma przypisany modul docelowy.

---

## Legenda statusow

| Status | Znaczenie |
|--------|-----------|
| `missing` | Brak implementacji, do napisania od zera |
| `stub` | Plik istnieje, ale pusta/minimalna implementacja |
| `partial` | Czesciowa implementacja, wymaga rozbudowy |
| `adapter` | Nowy modul bedzie wrapperem starego kodu |
| `implemented` | Zaimplementowane, wymaga review/testow |
| `tested` | Zaimplementowane i przetestowane |

---

## A. SENSOR LAYER (Parametry monitorowane)

### A.1 Zasoby systemowe (hardware)

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| RAM monitoring (used, free, swap) | `agent_core/homeostasis/sensors/resource_sensor.py` | `maria_core/sys/resource_watchdog.py` | adapter | ResourceWatchdog ma `get_memory_usage()` |
| CPU monitoring (%, load avg) | `agent_core/homeostasis/sensors/resource_sensor.py` | `maria_core/sys/resource_watchdog.py` | adapter | ResourceWatchdog ma `get_system_stats()` |
| Disk monitoring (%, I/O) | `agent_core/homeostasis/sensors/resource_sensor.py` | `maria_core/sys/resource_watchdog.py` | partial | Brak I/O queue depth |
| Thermal monitoring (temp, throttle) | `agent_core/homeostasis/sensors/thermal_sensor.py` | - | missing | Spec wymaga `/sys/class/thermal` |
| Power monitoring (voltage, uptime) | `agent_core/homeostasis/sensors/power_sensor.py` | - | missing | Opcjonalne dla SBC |

### A.2 Stany poznawcze (cognitive sensors)

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| LLM context size (tokens) | `agent_core/homeostasis/sensors/cognitive_sensor.py` | `maria_core/brain/ollama_brain.py` | partial | Brak explicit token counting |
| Response latency (p50, p99) | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | missing | Spec wymaga latency_probe |
| Memory coherence | `agent_core/homeostasis/sensors/cognitive_sensor.py` | `maria_core/memory/semantic_graph.py` | partial | Graf ma consistency check |
| Contradiction count | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | missing | Spec wymaga w short-term memory |
| Goal stack depth | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | missing | Brak goal stack |
| Conversation drift | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | missing | Semantic distance tracking |
| Error density | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | missing | Agregacja per hour/day |
| Task completion ratio | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | missing | % ukonczonych taskow |

### A.3 Rytmy czasowe

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Hour of day / Day of week | `agent_core/homeostasis/sensors/time_sensor.py` | - | missing | Proste, stdlib |
| Session duration | `agent_core/homeostasis/sensors/time_sensor.py` | - | missing | Tracking uptime |
| Last interaction timestamp | `agent_core/homeostasis/sensors/time_sensor.py` | - | missing | Idle detection |
| Idle streak duration | `agent_core/homeostasis/sensors/time_sensor.py` | - | missing | Trigger dla SLEEP |

### A.4 Alerty krytyczne

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| OOM detection (< 200 MB) | `agent_core/homeostasis/constraints.py` | `maria_core/sys/resource_watchdog.py` | partial | Ma threshold ale inny |
| Disk full (> 95%) | `agent_core/homeostasis/constraints.py` | - | missing | |
| LLM timeout (> 120s) | `agent_core/homeostasis/constraints.py` | - | missing | |
| Context loss detection | `agent_core/homeostasis/constraints.py` | - | missing | Snapshot corruption |
| Memory fragmentation | `agent_core/homeostasis/constraints.py` | - | missing | Soft constraint |
| Context degradation | `agent_core/homeostasis/constraints.py` | - | missing | Incoherent responses |

---

## B. STATE PROCESSING

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| State buffer (exponential smoothing) | `agent_core/homeostasis/state_model.py` | - | missing | EMA na metrykach |
| StateInterpreter | `agent_core/homeostasis/interpreter.py` | - | missing | Raw → semantic state |
| ConstraintValidator | `agent_core/homeostasis/constraints.py` | `maria_core/sys/resource_watchdog.py` | adapter | Rozszerzyc o cognitive |
| ResourceMetrics dataclass | `agent_core/homeostasis/state_model.py` | - | missing | Spec: linie 907-915 |
| CognitiveMetrics dataclass | `agent_core/homeostasis/state_model.py` | - | missing | Spec: linie 917-923 |
| SystemState dataclass | `agent_core/homeostasis/state_model.py` | - | missing | Spec: linie 925-931 |

---

## C. MODE MANAGEMENT

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Mode enum (ACTIVE/REDUCED/SLEEP/SURVIVAL) | `agent_core/homeostasis/mode_regulator.py` | `maria_core/sys/meta_controller.py` | adapter | Ma tryby ale inne nazwy |
| ModeRegulator.decide_mode() | `agent_core/homeostasis/mode_regulator.py` | `maria_core/sys/meta_controller.py` | partial | Ma logike ale prostsza |
| Transition validation | `agent_core/homeostasis/mode_regulator.py` | - | missing | Spec: forbidden transitions |
| Pre-transition checks | `agent_core/homeostasis/mode_regulator.py` | - | missing | Snapshot, signal, drain |
| User override handling | `agent_core/homeostasis/mode_regulator.py` | - | missing | Operator requests |

---

## D. CORRECTIVE ACTIONS

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| CorrectiveActionGenerator | `agent_core/homeostasis/actions.py` | - | missing | Spec: linie 1222-1286 |
| Memory consolidation signal | `agent_core/homeostasis/actions.py` | - | missing | Signal to memory module |
| Pause background learning | `agent_core/homeostasis/actions.py` | - | missing | Signal to learning |
| Reduce inference batch | `agent_core/homeostasis/actions.py` | - | missing | Signal to LLM |
| Goal stack interrupt | `agent_core/homeostasis/actions.py` | - | missing | Signal to metacontroller |
| AlarmDispatcher | `agent_core/homeostasis/actions.py` | - | missing | Critical interrupt |

---

## E. MAIN LOOP & TIMING

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| HomeostasisCore main_loop() | `agent_core/homeostasis/core.py` | - | missing | Spec: linie 1316-1478 |
| Pulse thread (100ms) | `agent_core/homeostasis/pulse.py` | - | missing | Spec: linie 1504-1560 |
| Tick evaluation (1s) | `agent_core/homeostasis/core.py` | - | missing | Main loop cycle |
| Epoch tasks (1h/24h) | `agent_core/homeostasis/core.py` | - | missing | Archival, planning |
| Health score computation | `agent_core/homeostasis/core.py` | - | missing | Aggregate 0-1 |
| Audit log | `agent_core/homeostasis/core.py` | - | missing | Decision trail |

---

## F. SNAPSHOT & RECOVERY

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Snapshot protocol | `agent_core/homeostasis/snapshot.py` | - | missing | Spec: linie 1676-1701 |
| Atomic snapshot (CoW) | `agent_core/memory/snapshot_backend.py` | - | missing | Copy-on-write |
| Recovery procedure | `agent_core/homeostasis/snapshot.py` | - | missing | Spec: linie 509-523 |
| CRC validation | `agent_core/homeostasis/snapshot.py` | - | missing | Integrity check |
| Graceful shutdown | `agent_core/homeostasis/snapshot.py` | - | missing | Spec: linie 1706-1726 |

---

## G. PUBLIC API

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| HomeostasisInterface | `agent_core/homeostasis/api.py` | - | missing | Spec: linie 712-798 |
| get_current_mode() | `agent_core/homeostasis/api.py` | - | missing | Read operation |
| get_resource_headroom() | `agent_core/homeostasis/api.py` | - | missing | Read operation |
| get_health_score() | `agent_core/homeostasis/api.py` | - | missing | Read operation |
| request_resource_allocation() | `agent_core/homeostasis/api.py` | - | missing | Write operation |
| notify_module_state() | `agent_core/homeostasis/api.py` | - | missing | Module reports |
| signal_critical_error() | `agent_core/homeostasis/api.py` | - | missing | Urgent signal |
| request_mode_override() | `agent_core/homeostasis/api.py` | - | missing | Meta-controller request |

---

## H. EVENT BUS

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| HomeostasisEventBus | `agent_core/homeostasis/api.py` | - | missing | Spec: linie 801-817 |
| event_mode_changed | `agent_core/homeostasis/api.py` | - | missing | Broadcast |
| event_resource_reduced | `agent_core/homeostasis/api.py` | - | missing | Broadcast |
| event_alert_raised | `agent_core/homeostasis/api.py` | - | missing | Broadcast |
| event_health_degraded | `agent_core/homeostasis/api.py` | - | missing | Broadcast |

---

## I. OPERATOR INTERFACE

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Telemetry API (read-only) | `agent_core/ui/telemetry_api.py` | - | missing | Dashboard data |
| Operator controls | `agent_core/ui/operator_controls.py` | - | missing | Safe writes |
| Force mode (with validation) | `agent_core/ui/operator_controls.py` | - | missing | Time-limited override |
| Trigger snapshot | `agent_core/ui/operator_controls.py` | - | missing | Manual backup |
| View audit log | `agent_core/ui/telemetry_api.py` | - | missing | Read-only |

---

## J. MEMORY INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| MemoryManager interface | `agent_core/memory/manager.py` | `maria_core/memory/memory_store.py` | adapter | Wrap existing |
| Episodic store | `agent_core/memory/episodic_store.py` | `maria_core/memory/brain_memory_integration.py` | adapter | episodic_memory list |
| Semantic store | `agent_core/memory/semantic_store.py` | `maria_core/memory/semantic_graph.py` | adapter | SemanticGraph |
| get_semantic_coherence() | `agent_core/memory/semantic_store.py` | - | missing | Consistency score |
| get_recent_errors_count() | `agent_core/memory/manager.py` | - | missing | Error aggregation |
| consolidate_episodic() | `agent_core/memory/episodic_store.py` | - | missing | Compression |
| semantic_consistency_check() | `agent_core/memory/semantic_store.py` | `maria_core/memory/semantic_graph.py` | partial | validate_integrity() |

---

## K. LLM INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| LLMManager interface | `agent_core/llm/manager.py` | `maria_core/brain/ollama_brain.py` | adapter | Wrap existing |
| Latency probe | `agent_core/llm/latency_probe.py` | - | missing | Quick test prompt |
| reduce_batch_size() | `agent_core/llm/manager.py` | - | missing | Throttle signal |
| minimize() | `agent_core/llm/manager.py` | - | missing | SURVIVAL mode |
| health_check() | `agent_core/llm/manager.py` | - | missing | Status report |

---

## L. METACONTROL INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| MetaController interface | `agent_core/metacontrol/controller.py` | `maria_core/sys/meta_controller.py` | adapter | Wrap existing |
| Goal stack management | `agent_core/metacontrol/controller.py` | - | missing | Depth tracking |
| interrupt_goal_refinement() | `agent_core/metacontrol/controller.py` | - | missing | Runaway prevention |
| request_mode_override() | `agent_core/metacontrol/controller.py` | - | missing | Higher-level request |

---

## M. EXECUTOR INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| ModuleExecutor | `agent_core/executor/module_executor.py` | - | missing | Signal dispatcher |
| signal_module() | `agent_core/executor/module_executor.py` | - | missing | Spec: linie 1731-1753 |
| Module communication contract | `agent_core/executor/module_executor.py` | - | missing | pause/resume/reduce |

---

## N. THREAT MITIGATIONS

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Runaway loop detection | `agent_core/homeostasis/constraints.py` | - | missing | Goal stack + timeout |
| Memory bloat handling | `agent_core/homeostasis/actions.py` | - | missing | Emergency consolidation |
| Thermal runaway | `agent_core/homeostasis/actions.py` | - | missing | Throttle + REDUCED |
| Identity drift detection | `agent_core/homeostasis/constraints.py` | - | missing | Contradiction rate |
| Cascading failure circuit breaker | `agent_core/homeostasis/actions.py` | - | missing | Error rate isolation |
| Destructive loop prevention | `agent_core/homeostasis/constraints.py` | - | missing | Escalation patterns |
| Mandatory backoff | `agent_core/homeostasis/actions.py` | - | missing | Exponential pause |

---

## Podsumowanie statystyk

| Status | Liczba wymagan |
|--------|----------------|
| missing | ~65 |
| partial | ~8 |
| adapter | ~10 |
| stub | 0 |
| implemented | 0 |
| tested | 0 |

**Szacunkowy naklad pracy:** ~65 nowych komponentow do napisania

---

## Flow diagram (spec → implementation)

```
                    SPECYFIKACJA
                         |
    +--------------------+--------------------+
    |                    |                    |
SENSORS              STATE              ACTIONS
    |                    |                    |
+---+---+           +----+----+          +----+----+
|       |           |         |          |         |
resource cognitive  interpret  validate  generate  dispatch
sensor   sensor     state      constraints actions  alarms
    |       |           |         |          |         |
    +-------+-----------+---------+----------+---------+
                         |
                   MODE_REGULATOR
                         |
              +----------+----------+
              |                     |
         CORE_LOOP              PULSE_THREAD
         (1s tick)              (100ms heartbeat)
              |                     |
              +----------+----------+
                         |
                    SNAPSHOT
                    RECOVERY
                         |
              +----------+----------+
              |                     |
           API                  EVENT_BUS
        (public)               (broadcasts)
              |                     |
    +---------+---------+    +-----+-----+
    |         |         |    |           |
 memory    llm      meta   telemetry  operator
 module   module   control    API     controls
```

---

*Aktualizuj ten dokument w miare postepow implementacji - zmieniaj statusy na implemented/tested.*
