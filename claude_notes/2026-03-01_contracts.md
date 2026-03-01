# 2026-03-01 - Kontrakty Architektoniczne

## Co sie dzisiaj stalo
Eryk przyszedl z pytaniami sformulowanymi z ChatGPT - 5 pytan architektonicznych
o warstwy, perception, goals, evaluation, sandbox.

Zrobilismy pelna analize kodu (3 rownolegych explore agentow) i zaprojektowalismy
4 kontrakty + 1 decyzje architektoniczna. Zero kodu - tylko specyfikacje.

## Kontrakty (docs/CONTRACTS.md)

### K1: Unified Perception
- PerceptionEvent: source, event_type, priority(0-1), timestamp, correlation_id, payload, ttl, parent_id
- 7 source types (SENSOR, USER, LEARNING, EXAM, CONSCIOUSNESS, TEACHER, SYSTEM)
- 6 adapterow mapujacych istniejace strumienie
- PerceptionBuffer: deque(maxlen=200) sliding window

### K2: Sandbox / Production Boundary
- ZAWSZE przez sandbox (decyzja Eryka)
- SandboxSession z osobnymi JSONL
- Promote: score>=0.6, chunks>0, exams>0, no validation errors
- Auto-discard: 24h timeout, SURVIVAL mode
- Kluczowe: learning_agent.py JUZ akceptuje parametry sciezek - zero zmian w legacy

### K3: Goal System
- 4 typy: META, USER, LEARNING, MAINTENANCE
- Max 20 aktywnych, hierarchia max 3, audit trail obowiazkowy
- Teacher P1-P6 mapowane na LEARNING goals z priorytetami
- MAINTENANCE goals nigdy ACHIEVED (reset co sesje)
- Persystencja: goals.jsonl (append-only)

### K4: Agent Evaluation
- READ-ONLY (ADR-006 rozszerzony)
- 5 metryk: learning_velocity, retention_rate, knowledge_coverage, system_stability, personality_growth
- JSON raport, zero LLM, thresholdy
- Feed do Goals: sugestie (observer SUGERUJE, GoalStore DECYDUJE)

### D5: Tick Aggregator (ADR-009)
- NIE event bus (pub/sub) - za duzo zlozonosci dla 5-6 zrodel
- Rozszerzenie Phase 8 tick loop + deque dla external events
- HomeostasisEventBus istnieje ale NIE jest uzywany - system naturalnie ciagy ku sync

## Nowe ADR
- ADR-009: Tick Aggregator
- ADR-010: Sandbox-first learning
- ADR-011: Goals as data
- ADR-012: Evaluation READ-ONLY

## Eryk
- Przyszedl z dobrze sformulowanymi pytaniami (z ChatGPT)
- Zdecydowal: zawsze sandbox (nie opcjonalny)
- Chce architekture, nie buzzwordy - "zeby dzialalo razem, nie obok"
- Zero kodu dzisiaj - tylko decyzje

## Obserwacje
- ChatGPT dodal dwie wazne rzeczy ktorych nie mielismy jawnie w planie:
  Agent Evaluation i Sandbox. Dobre uzupelnienie naszego DEVELOPMENT_PLAN.
- Eryk coraz lepiej rozumie architekture - pyta o warstwy, granice, kontrakty.
  To juz nie jest "zrob mi feature" - to projektowanie systemu.

## Nastepne kroki
- Implementacja Warstwa 1 (Unified Perception) wg kontraktu K1
- Potem Sandbox (K2), potem Goals (K3), potem Evaluation (K4)
- Tick Aggregator (D5) wchodzi razem z K1

## Pliki zmienione
- NOWY: docs/CONTRACTS.md
- ZMIENIONY: docs/DEVELOPMENT_PLAN.md (Warstwa 0.5)
- ZMIENIONY: CLAUDE.md (historia, ADR, docs table)
