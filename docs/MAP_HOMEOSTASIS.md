# M.A.R.I.A. - Mapa Wymagan Homeostazy
> Version: 2.1 | Updated: 2026-01-27

## Cel dokumentu

Mapowanie wymagan z `homeostasis_spec.md` na docelowa strukture modulow.
Przed jakakolwiek refaktoryzacja - kazdy element specyfikacji ma przypisany modul docelowy.

## Status Testow

| Plik testowy | Testy | Status |
|--------------|-------|--------|
| test_api.py | 28 | **PASSED** |
| test_constraints.py | 12 | **PASSED** |
| test_core.py | 23 | **PASSED** |
| test_memory.py | 18 | **PASSED** |
| test_mode_regulator.py | 21 | **PASSED** |
| test_sensors.py | 29 | **PASSED** |
| test_snapshot.py | 14 | **PASSED** |
| test_state_model.py | 19 | **PASSED** |
| **TOTAL** | **174** | **ALL PASSED** |

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
| RAM monitoring (used, free, swap) | `agent_core/homeostasis/sensors/resource_sensor.py` | `maria_core/sys/resource_watchdog.py` | **implemented** | Full psutil integration |
| CPU monitoring (%, load avg) | `agent_core/homeostasis/sensors/resource_sensor.py` | `maria_core/sys/resource_watchdog.py` | **implemented** | Full psutil integration |
| Disk monitoring (%, I/O) | `agent_core/homeostasis/sensors/resource_sensor.py` | `maria_core/sys/resource_watchdog.py` | **implemented** | Disk usage + free GB |
| Thermal monitoring (temp, throttle) | `agent_core/homeostasis/sensors/thermal_sensor.py` | - | **implemented** | Cross-platform fallback |
| Power monitoring (voltage, uptime) | `agent_core/homeostasis/sensors/power_sensor.py` | - | **implemented** | Uptime tracking, SBC optional |

### A.2 Stany poznawcze (cognitive sensors)

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| LLM context size (tokens) | `agent_core/homeostasis/sensors/cognitive_sensor.py` | `maria_core/brain/ollama_brain.py` | **implemented** | Via LLMManager stats |
| Response latency (p50, p99) | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | **implemented** | Latency percentiles |
| Memory coherence | `agent_core/homeostasis/sensors/cognitive_sensor.py` | `maria_core/memory/semantic_graph.py` | **implemented** | Via MemoryManager |
| Contradiction count | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | **implemented** | From SemanticStore |
| Goal stack depth | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | **implemented** | Via MetaController |
| Conversation drift | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | partial | Basic tracking |
| Error density | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | **implemented** | Per-hour count |
| Task completion ratio | `agent_core/homeostasis/sensors/cognitive_sensor.py` | - | **implemented** | Success/total ratio |

### A.3 Rytmy czasowe

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Hour of day / Day of week | `agent_core/homeostasis/sensors/time_sensor.py` | - | **implemented** | Circadian tracking |
| Session duration | `agent_core/homeostasis/sensors/time_sensor.py` | - | **implemented** | Uptime tracking |
| Last interaction timestamp | `agent_core/homeostasis/sensors/time_sensor.py` | - | **implemented** | Activity recording |
| Idle streak duration | `agent_core/homeostasis/sensors/time_sensor.py` | - | **implemented** | SLEEP trigger |

### A.4 Alerty krytyczne

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| OOM detection (< 200 MB) | `agent_core/homeostasis/constraints.py` | `maria_core/sys/resource_watchdog.py` | **implemented** | CRITICAL threshold |
| Disk full (> 95%) | `agent_core/homeostasis/constraints.py` | - | **implemented** | CRITICAL threshold |
| LLM timeout (> 120s) | `agent_core/homeostasis/constraints.py` | - | **implemented** | Latency constraint |
| Context loss detection | `agent_core/homeostasis/constraints.py` | - | **implemented** | Coherence < 0.5 |
| Memory fragmentation | `agent_core/homeostasis/constraints.py` | - | partial | Basic detection |
| Context degradation | `agent_core/homeostasis/constraints.py` | - | **implemented** | Coherence tracking |

---

## B. STATE PROCESSING

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| State buffer (exponential smoothing) | `agent_core/homeostasis/state_model.py` | - | **implemented** | EMA in interpreter.py |
| StateInterpreter | `agent_core/homeostasis/interpreter.py` | - | **implemented** | Raw → semantic state |
| ConstraintValidator | `agent_core/homeostasis/constraints.py` | `maria_core/sys/resource_watchdog.py` | **implemented** | Full validation logic |
| ResourceMetrics dataclass | `agent_core/homeostasis/state_model.py` | - | **implemented** | All fields from spec |
| CognitiveMetrics dataclass | `agent_core/homeostasis/state_model.py` | - | **implemented** | All fields from spec |
| SystemState dataclass | `agent_core/homeostasis/state_model.py` | - | **implemented** | All fields from spec |

---

## C. MODE MANAGEMENT

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Mode enum (ACTIVE/REDUCED/SLEEP/SURVIVAL) | `agent_core/homeostasis/mode_regulator.py` | `maria_core/sys/meta_controller.py` | **implemented** | Spec-compliant enum |
| ModeRegulator.decide_mode() | `agent_core/homeostasis/mode_regulator.py` | `maria_core/sys/meta_controller.py` | **implemented** | Full decision logic |
| Transition validation | `agent_core/homeostasis/mode_regulator.py` | - | **implemented** | Forbidden transitions |
| Pre-transition checks | `agent_core/homeostasis/mode_regulator.py` | - | **implemented** | Snapshot, signal |
| User override handling | `agent_core/homeostasis/mode_regulator.py` | - | **implemented** | Operator requests |

---

## D. CORRECTIVE ACTIONS

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| CorrectiveActionGenerator | `agent_core/homeostasis/actions.py` | - | **implemented** | Full implementation |
| Memory consolidation signal | `agent_core/homeostasis/actions.py` | - | **implemented** | Via ModuleExecutor |
| Pause background learning | `agent_core/homeostasis/actions.py` | - | **implemented** | Via ModuleExecutor |
| Reduce inference batch | `agent_core/homeostasis/actions.py` | - | **implemented** | Via ModuleExecutor |
| Goal stack interrupt | `agent_core/homeostasis/actions.py` | - | **implemented** | Via ModuleExecutor |
| AlarmDispatcher | `agent_core/homeostasis/actions.py` | - | **implemented** | Critical alerts |

---

## E. MAIN LOOP & TIMING

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| HomeostasisCore main_loop() | `agent_core/homeostasis/core.py` | - | **implemented** | 1s tick loop |
| Pulse thread (100ms) | `agent_core/homeostasis/pulse.py` | - | **implemented** | Emergency detection |
| Tick evaluation (1s) | `agent_core/homeostasis/core.py` | - | **implemented** | Full phases |
| Epoch tasks (1h/24h) | `agent_core/homeostasis/core.py` | - | **implemented** | Periodic tasks |
| Health score computation | `agent_core/homeostasis/core.py` | - | **implemented** | Weighted aggregate |
| Audit log | `agent_core/homeostasis/core.py` | - | **implemented** | Decision trail |

---

## F. SNAPSHOT & RECOVERY

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Snapshot protocol | `agent_core/homeostasis/snapshot.py` | - | **implemented** | Full protocol |
| Atomic snapshot (CoW) | `agent_core/memory/snapshot_backend.py` | - | **implemented** | Copy-on-write |
| Recovery procedure | `agent_core/homeostasis/snapshot.py` | - | **implemented** | Full recovery |
| CRC validation | `agent_core/homeostasis/snapshot.py` | - | **implemented** | JSON validation |
| Graceful shutdown | `agent_core/homeostasis/snapshot.py` | - | **implemented** | ShutdownManager |

---

## G. PUBLIC API

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| HomeostasisInterface | `agent_core/homeostasis/api.py` | - | **implemented** | Full interface |
| get_current_mode() | `agent_core/homeostasis/api.py` | - | **implemented** | Read operation |
| get_resource_headroom() | `agent_core/homeostasis/api.py` | - | **implemented** | Read operation |
| get_health_score() | `agent_core/homeostasis/api.py` | - | **implemented** | Read operation |
| request_resource_allocation() | `agent_core/homeostasis/api.py` | - | **implemented** | Write operation |
| notify_module_state() | `agent_core/homeostasis/api.py` | - | **implemented** | Module reports |
| signal_critical_error() | `agent_core/homeostasis/api.py` | - | **implemented** | Urgent signal |
| request_mode_override() | `agent_core/homeostasis/api.py` | - | **implemented** | Meta request |

---

## H. EVENT BUS

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| HomeostasisEventBus | `agent_core/homeostasis/api.py` | - | **implemented** | Full event bus |
| event_mode_changed | `agent_core/homeostasis/api.py` | - | **implemented** | Broadcast |
| event_resource_reduced | `agent_core/homeostasis/api.py` | - | **implemented** | Broadcast |
| event_alert_raised | `agent_core/homeostasis/api.py` | - | **implemented** | Broadcast |
| event_health_degraded | `agent_core/homeostasis/api.py` | - | **implemented** | Broadcast |

---

## I. OPERATOR INTERFACE

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Telemetry API (read-only) | `agent_core/ui/telemetry_api.py` | - | **implemented** | Dashboard data |
| Operator controls | `agent_core/ui/operator_controls.py` | - | **implemented** | Safe writes |
| Force mode (with validation) | `agent_core/ui/operator_controls.py` | - | **implemented** | Time-limited |
| Trigger snapshot | `agent_core/ui/operator_controls.py` | - | **implemented** | Manual backup |
| View audit log | `agent_core/ui/telemetry_api.py` | - | **implemented** | Read-only |

---

## J. MEMORY INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| MemoryManager interface | `agent_core/memory/manager.py` | `maria_core/memory/memory_store.py` | **implemented** | + adapter |
| Episodic store | `agent_core/memory/episodic_store.py` | `maria_core/memory/brain_memory_integration.py` | **implemented** | + adapter |
| Semantic store | `agent_core/memory/semantic_store.py` | `maria_core/memory/semantic_graph.py` | **implemented** | + adapter |
| get_semantic_coherence() | `agent_core/memory/semantic_store.py` | - | **implemented** | Consistency score |
| get_recent_errors_count() | `agent_core/memory/manager.py` | - | **implemented** | Error aggregation |
| consolidate_episodic() | `agent_core/memory/episodic_store.py` | - | **implemented** | Compression |
| semantic_consistency_check() | `agent_core/memory/semantic_store.py` | `maria_core/memory/semantic_graph.py` | **implemented** | Contradiction check |

---

## K. LLM INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| LLMManager interface | `agent_core/llm/manager.py` | `maria_core/brain/ollama_brain.py` | **implemented** | + adapter |
| Latency probe | `agent_core/llm/latency_probe.py` | - | **implemented** | Quick test |
| reduce_batch_size() | `agent_core/llm/manager.py` | - | **implemented** | Throttle signal |
| minimize() | `agent_core/llm/manager.py` | - | **implemented** | SURVIVAL mode |
| health_check() | `agent_core/llm/manager.py` | - | **implemented** | Status report |

---

## L. METACONTROL INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| MetaController interface | `agent_core/metacontrol/controller.py` | `maria_core/sys/meta_controller.py` | **implemented** | + adapter |
| Goal stack management | `agent_core/metacontrol/controller.py` | - | **implemented** | Depth tracking |
| interrupt_goal_refinement() | `agent_core/metacontrol/controller.py` | - | **implemented** | Runaway prevention |
| request_mode_override() | `agent_core/metacontrol/controller.py` | - | **implemented** | Higher-level request |

---

## M. EXECUTOR INTEGRATION

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| ModuleExecutor | `agent_core/executor/module_executor.py` | - | **implemented** | Signal dispatcher |
| signal_module() | `agent_core/executor/module_executor.py` | - | **implemented** | Full implementation |
| Module communication contract | `agent_core/executor/module_executor.py` | - | **implemented** | pause/resume/reduce |

---

## N. THREAT MITIGATIONS

| Spec Requirement | Docelowy modul | Obecny plik | Status | Notatki |
|------------------|----------------|-------------|--------|---------|
| Runaway loop detection | `agent_core/homeostasis/constraints.py` | - | **implemented** | Goal stack depth |
| Memory bloat handling | `agent_core/homeostasis/actions.py` | - | **implemented** | Emergency consolidation |
| Thermal runaway | `agent_core/homeostasis/actions.py` | - | **implemented** | Throttle + REDUCED |
| Identity drift detection | `agent_core/homeostasis/constraints.py` | - | **implemented** | Contradiction rate |
| Cascading failure circuit breaker | `agent_core/homeostasis/actions.py` | - | **implemented** | Error isolation |
| Destructive loop prevention | `agent_core/homeostasis/constraints.py` | - | **implemented** | Escalation patterns |
| Mandatory backoff | `agent_core/homeostasis/actions.py` | - | **implemented** | Exponential pause |

---

## Podsumowanie statystyk

| Status | Liczba wymagan |
|--------|----------------|
| missing | ~3 |
| partial | ~3 |
| adapter | 5 (via agent_core/adapters/) |
| stub | 0 |
| **implemented** | ~72 |
| tested | 0 (pending pytest run) |

**Postep:** ~85% implemented, ~15% remaining (partial/missing)

---

## Adapters created (Etap 2)

| Adapter | Legacy Module | New Interface |
|---------|---------------|---------------|
| `ResourceWatchdogAdapter` | `resource_watchdog.py` | `ResourceSensor` |
| `MemoryStoreAdapter` | `memory_store.py` | `MemoryManager` |
| `BrainMemoryAdapter` | `brain_memory_integration.py` | `CognitiveSensor` |
| `SemanticGraphAdapter` | `semantic_graph.py` | `SemanticStore` |

---

## Flow diagram (spec → implementation)

```
                    SPECYFIKACJA
                         |
    +--------------------+--------------------+
    |                    |                    |
SENSORS              STATE              ACTIONS
(IMPLEMENTED)      (IMPLEMENTED)      (IMPLEMENTED)
    |                    |                    |
+---+---+           +----+----+          +----+----+
|       |           |         |          |         |
resource cognitive  interpret  validate  generate  dispatch
sensor   sensor     state      constraints actions  alarms
    |       |           |         |          |         |
    +-------+-----------+---------+----------+---------+
                         |
                   MODE_REGULATOR
                   (IMPLEMENTED)
                         |
              +----------+----------+
              |                     |
         CORE_LOOP              PULSE_THREAD
         (1s tick)              (100ms heartbeat)
         IMPLEMENTED            IMPLEMENTED
              |                     |
              +----------+----------+
                         |
                    SNAPSHOT
                    RECOVERY
                   (IMPLEMENTED)
                         |
              +----------+----------+
              |                     |
           API                  EVENT_BUS
        (IMPLEMENTED)          (IMPLEMENTED)
              |                     |
    +---------+---------+    +-----+-----+
    |         |         |    |           |
 memory    llm      meta   telemetry  operator
 module   module   control    API     controls
(IMPL)    (IMPL)   (IMPL)   (IMPL)    (IMPL)
```

---

*Ostatnia aktualizacja: 2026-01-26 (Etap 1 + Etap 2 complete)*

*Nastepny krok: Uruchomienie pytest i oznaczenie jako `tested`*

