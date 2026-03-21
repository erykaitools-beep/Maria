# Sesja 2026-03-21 (3/3) - ModelScheduler Implementation

## Co zrobilismy

### ModelScheduler - multi-organ model stack infrastructure
- **model_registry.py:** ModelRole(6), ModelSpec (frozen dataclass), statyczny REGISTRY, RAM tiery, set_triage_model()
- **model_scheduler.py:** ModelScheduler - load/unload via Ollama, RAM guard (psutil), heavy mutex (threading.Lock), idle timeout, health persist (model_health.json)
- **routing_rules.py:** TaskType(8) -> ModelRole mapping, heuristic_classify (keyword-based fallback dla MODEL-04)
- **router.py rozszerzony:** ask_as_role(role, prompt) + set_model_scheduler()
- **Wiring:** SharedContext.model_scheduler, HomeostasisCore Phase 9.5 tick, homeostasis_module auto-register MODEL-02
- **75 testow**, 1587 total passing

### Kluczowe decyzje:
1. Scheduler to warstwa infrastruktury (ktory model w RAM), router to warstwa decyzyjna (ktory model dla zadania)
2. ensure_ready() jako single entry point - sprawdza RAM, mutex, laduje, fallback
3. Heavy mutex na PLANNER/CODER - nigdy rownoczesnie, threading.Lock
4. tick() w homeostasis Phase 9.5 (przed plannerem) - idle timeout + RAM pressure
5. Backward compat 100% - think(), _ask_once(), analyze_task() bez zmian

### Architektura:
```
Router.ask_as_role(PLANNER, prompt)
  -> Scheduler.ensure_ready(PLANNER)
    -> RAM guard (psutil.virtual_memory)
    -> Heavy mutex (threading.Lock)
    -> _ollama_load("qwen2.5:14b")
  -> ollama.chat(model="qwen2.5:14b", ...)
  -> Scheduler.record_request(PLANNER, latency)
  -> Scheduler.release(PLANNER)
```

## Eryk
- Zaufal mojej rekomendacji zeby zaczac od Model Registry (nie OpenClaw)
- Potem zmienil zdanie na Model Registry first - mial racje, to infrastruktura
- Zweryfikowal czy plan uwzglednia docs/MODEL_REGISTRY.md i DEPLOYMENT_ORDER.md

## Nastepne kroki
- Model Registry Stage 2: benchmark phi3:mini vs qwen2.5:3b vs gemma2:2b na mini PC
- OpenClaw integration - efektor (plan gotowy w memory)
- Obserwowac logi czy ModelScheduler tick() dziala poprawnie
