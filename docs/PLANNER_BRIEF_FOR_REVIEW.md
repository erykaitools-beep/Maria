# M.A.R.I.A. - Brief: Warstwa 2 (Planner) - do review

> Ten dokument to kontekst dla zewnetrznego LLM (ChatGPT/Grok) do review koncepcji Plannera.
> Prosze o feedback na temat architektury, ryzyk i brakujacych elementow.

---

## Co to jest M.A.R.I.A.?

Lokalny, autonomiczny agent AI do samodzielnego uczenia sie z plikow tekstowych.
- **LLM:** Ollama (llama3.1:8b) offline + NVIDIA NIM API (mocniejszy model) z fallbackiem
- **Platforma:** Python 3.8+, Linux Mini PC (32GB RAM)
- **Stan:** 941 testow, dziala produkcyjnie

Maria ma system homeostazy (1Hz tick loop, 10 faz) ktory monitoruje zasoby, reguluje tryby pracy (ACTIVE/REDUCED/SLEEP/SURVIVAL) i utrzymuje system stabilnym.

---

## Zaimplementowane warstwy (Warstwa 0-1)

### Warstwa 0.5: Kontrakty K1-K4 (DONE, 941 testow)

#### K1: Unified Perception
- **PerceptionEvent** (frozen dataclass): event_id, source (7 typow), event_type (22 typow), priority (0.0-1.0), timestamp, payload, ttl, parent_event_id
- **PerceptionBuffer**: sliding window (deque maxlen=200), query po source/priority/event_type/parent
- **6 adapterow**: sensor, user, learning, exam, consciousness, teacher
- **Tick Aggregator** (ADR-009): Phase 8 tick loop agreguje eventy + external queue (thread-safe deque)

API:
```python
buffer.push(event)
buffer.get_recent(n=10, source=PerceptionSource.LEARNING)
buffer.get_by_priority(min_priority=0.7)
buffer.get_by_event_type("exam_result")
buffer.get_children(parent_event_id)
buffer.drain_expired()
```

#### K2: Sandbox / Production Boundary
- **Kazda nauka** idzie przez sandbox. `promote()` to JEDYNY most do produkcji.
- SandboxSession: create -> seed_from_production -> learn -> exam -> promote/discard
- Transaction log (START/COMMIT/ROLLBACK), startup recovery
- Max 1 aktywna sesja, auto-discard po 24h

API:
```python
session = mgr.create_session()
mgr.seed_from_production(file_ids=["file1.txt"])
mgr.record_chunk_learned(file_id="file1.txt")
mgr.record_exam_result(file_id="file1.txt", score=0.85, passed=True)
result = mgr.promote()  # PromoteResult(success, files_promoted, chunks_promoted)
mgr.discard(reason="bad_quality")
```

Kryteria promote: chunks_learned > 0, exams_total > 0, avg_score >= 0.6, zero validation errors.

#### K3: Goal System
- **4 typy celow**: META (misja), USER (od usera), LEARNING (od teachera), MAINTENANCE (zdrowie systemu)
- **6 statusow**: PROPOSED -> PENDING -> ACTIVE -> ACHIEVED/FAILED/ABANDONED
- Audit trail (kazda zmiana statusu = AuditEntry z reason i actor)
- Max 20 aktywnych, max 3 PROPOSED, 24h timeout na PROPOSED
- PROPOSED NIE wplywa na system (izolacja) - dopiero po CONFIRM wchodzi do planowania
- Seed goals: 1 META ("autonomiczna nauka") + 3 MAINTENANCE (health, RAM, CPU)

API:
```python
goal = create_goal(GoalType.LEARNING, "Naucz sie pliku X", priority=0.8, created_by="planner")
store.create(goal)
store.get_active(GoalType.LEARNING)  # PENDING + ACTIVE
store.update_status(goal_id, GoalStatus.ACTIVE, reason="planner started", actor="planner")
store.update_progress(goal_id, 0.5)  # Auto-ACHIEVED przy >= 1.0
store.propose(goal)  # PROPOSED - czeka na usera
store.confirm(goal_id)  # PROPOSED -> PENDING
```

#### K4: Agent Evaluation (READ-ONLY)
- 5 metryk: learning_velocity (chunks/h), retention_rate (pass/total), knowledge_coverage (completed/total files), system_stability (avg health), personality_growth
- Threshold-based recommendations (zero LLM)
- Pisze TYLKO do evaluation_reports.jsonl

API:
```python
report = observer.generate_report(period_hours=1.0)
report.metrics["learning_velocity"]  # 2.5 chunks/h
report.metrics["retention_rate"]     # 0.85
report.recommendations               # ["Retention < 80% - wiecej powtórek"]
```

### Agent Nauczyciel (Teacher, istniejacy)
- 6-priorytetowy silnik decyzyjny (P1-P6):
  1. Kontynuuj czesciowa nauke
  2. Egzaminuj gotowe pliki
  3. Zacznij nowy plik
  4. Powtorka (spaced repetition)
  5. Retry trudnych tematow
  6. NIM analiza luk wiedzy
- Autonomiczny trigger: Phase 10 tick loop, ACTIVE + idle >= 10min -> auto-sesja (3 iteracje), cooldown 15min
- Zero LLM w decyzjach (czysta logika), LLM tylko do nauki/egzaminow

### Homeostasis Tick Loop (1Hz, 10 faz)
```
Phase 1: SENSE      - czytaj metryki (RAM, CPU, temp, idle)
Phase 2: INTERPRET   - konwertuj na stan semantyczny
Phase 3: VALIDATE    - sprawdz ograniczenia, generuj alerty
Phase 4: DECIDE      - tryb pracy (ACTIVE/REDUCED/SLEEP/SURVIVAL)
Phase 5: ACT         - akcje korekcyjne
Phase 6: (reserved)
Phase 7: HEALTH      - aktualizuj health_score (0-1)
Phase 8: PERCEIVE    - agreguj eventy do PerceptionBuffer (ADR-009)
Phase 9: AUDIT       - loguj co 60 tickow
Phase 10: TEACHER    - auto-nauka gdy idle >= 10min w ACTIVE
```

---

## Warstwa 2: Planner - koncepcja do review

### Cel
Maria sama planuje i dziala, zamiast czekac na komendy. Planner to **ReAct loop** (cel -> mysl -> dzialaj -> obserwuj -> powtorz) ktory laczy K1-K4 w jedna petla decyzyjna.

### Rola kazdego komponentu w Plannerze

| Komponent | Rola | Faza ReAct |
|-----------|------|-----------|
| PerceptionBuffer (K1) | Co sie dzieje? Ostatnie eventy, priorytety | OBSERVE |
| GoalStore (K3) | Co chce osiagnac? Aktywne cele | THINK |
| EvaluationObserver (K4) | Jak mi idzie? Metryki, trendy | EVALUATE |
| SandboxManager (K2) | Izolowane wykonanie nauki | ACT |
| TeacherAgent | Wykonawca nauki (P1-P6) | ACT |
| Homeostasis | Kontekst zdrowia systemu, tryb pracy | GATE |

### Proponowany przepyw (ReAct)

```
[Planner Loop - co N tickow lub on-demand]

1. OBSERVE
   - buffer.get_recent() - co sie wydarzylo od ostatniego cyklu?
   - goal_store.get_active() - jakie mam cele?
   - homeostasis.get_state() - jaki tryb? health_score?
   - Jesli SURVIVAL/SLEEP -> skip (nie planuj)

2. THINK
   - evaluation.generate_report() - jak mi idzie?
   - Priorytetyzuj cele wg: priority * urgency * feasibility
   - Wybierz nastepna akcje (1 akcja na cykl, nie wiele naraz)

3. ACT
   - Jesli cel LEARNING -> sandbox.create() + teacher.run_session()
   - Jesli cel MAINTENANCE -> deleguj do homeostasis (juz sie sam zajmuje)
   - Jesli cel USER -> zaplanuj kroki, ewentualnie zaproponuj sub-cele

4. OBSERVE (po akcji)
   - Sprawdz wynik akcji (perception events)
   - goal_store.update_progress()
   - Jesli osiagnieto -> goal ACHIEVED
   - Jesli nie -> skoryguj plan lub retry

5. LOG
   - Zapisz decyzje do planner_decisions.jsonl
   - Wyemituj PerceptionEvent(source=PLANNER, type="planner_decision")
```

### Kluczowe pytania architektoniczne

**Q1: LLM czy czysta logika w v1?**
- Teacher i Evaluation dzialaja BEZ LLM (czysta logika + thresholdy)
- Czy Planner tez powinien byc bez LLM w v1?
- Argumenty za: prostosc, determinizm, testowalnosc, zero kosztu tokenow
- Argumenty przeciw: LLM daje elastycznosc, lepsze rozumowanie o priorytetach
- **Moja propozycja:** v1 bez LLM (rule-based), v2 z opcjonalnym LLM reasoning

**Q2: Relacja Planner <-> Teacher**
- Teacher ma juz 6-priorytetowy silnik decyzyjny (P1-P6)
- Teacher ma auto-trigger w Phase 10 (idle >= 10min)
- Opcja A: Planner ZASTEPUJE Phase 10 (sam decyduje kiedy uruchomic Teachera)
- Opcja B: Planner KOORDYNUJE z Phase 10 (Phase 10 zostaje, Planner moze tez zlecac)
- Opcja C: Phase 10 staje sie czescia Plannera (migracja)
- **Moja propozycja:** Opcja A - Planner przejmuje trigger, Teacher zostaje jako executor

**Q3: Czestotliwosc Plannera**
- Opcja A: Co tick (1Hz) - duzo overhead
- Opcja B: Co 60 tickow (1 min) - rozsadne
- Opcja C: Co 300 tickow (5 min) - rzadko
- Opcja D: Event-driven (planuj gdy cos waznego sie stalo)
- **Moja propozycja:** Hybrid - co 60 tickow routine check + natychmiast na high-priority events (exam_result, alert, user_command)

**Q4: Scope v1 (minimum viable planner)**
- Cel: Planner ktory laczy GoalStore + Teacher + Sandbox + Evaluation
- NIE w v1: LLM reasoning, multi-step planning, user goal suggestions, planner_decision -> sub-goals
- v1 = "wybierz najwazniejszy cel -> deleguj do Teachera -> mierz postep -> raportuj"

**Q5: trace_id / correlation_id**
- CONTRACTS.md mowi: "dodac trace_id gdy pojawi sie Planner"
- Planner bedzie sledzic wiele rownoczesnych akcji (np. nauka + ewaluacja)
- Czy dodac opcjonalne pole trace_id do PerceptionEvent teraz?
- **Moja propozycja:** Tak, opcjonalne pole, backward-compatible (None domyslnie)

**Q6: Nowa Phase w tick loop czy osobny watek?**
- Opcja A: Phase 11 w tick loop (synchronicznie, max 1s)
- Opcja B: Osobny watek z wlasna petla (asynchronicznie)
- Opcja C: Hybrid - Phase 11 sprawdza czy trzeba planowac, osobny watek wykonuje plan
- **Moja propozycja:** Opcja A (Phase 11) z guard "co 60 tickow" - zgodne z ADR-009 (tick aggregator, nie event bus)

**Q7: Persystencja stanu Plannera**
- Planner potrzebuje pamietac: aktualny plan, historia decyzji, kontekst
- Opcja A: planner_state.json (jak meta_controller.json)
- Opcja B: planner_decisions.jsonl (append-only, jak reszta systemu)
- **Moja propozycja:** Oba - state.json dla biezacego stanu + decisions.jsonl dla historii

---

## Ograniczenia i kontekst

- **ADR-001:** JSONL jako source of truth
- **ADR-002:** Threading, nie asyncio
- **ADR-009:** Tick Aggregator zamiast event bus
- **ADR-010:** Sandbox-first learning
- **ADR-011:** Goals as data (nie hardcoded logika)
- **ADR-012:** Evaluation READ-ONLY
- Maria uczy sie z ~10-20 plikow tekstowych, nie z milionow
- 1Hz tick loop, 1s latency jest OK
- Max 1 sandbox sesja aktywna jednoczesnie
- Max 20 aktywnych celow

## Diagram docelowy (z Plannerem)

```
Bodźce (Stimuli)
  |
  v
[Unified Perception (K1)] <-- sensory, user, nauka, egzaminy, consciousness, teacher
  |
  v
[PerceptionBuffer] ──────────────────────────┐
  |                                           |
  v                                           v
[Planner / ReAct Loop] <── GoalStore (K3)  [Homeostasis]
  |                    <── Evaluation (K4)  (tryby, zdrowie)
  v
[Actions] ──> Teacher (nauka)
          ──> Sandbox (K2, izolacja)
          ──> odpowiedz userowi
          ──> (przyszlosc: Vision, Smart Home)
  |
  v
[Goal Progress Update] ──> GoalStore audit trail
```

---

## Pytanie do reviewera

1. Czy ReAct loop (rule-based, bez LLM) to dobry wybor na v1?
2. Czy Planner powinien zastapic Phase 10 (teacher auto-trigger) czy koordynowac z nim?
3. Czy Phase 11 w tick loop (synchronicznie) to lepsze niz osobny watek?
4. Jakie ryzyka widzisz w tej architekturze?
5. Czego brakuje w tej koncepcji?
6. Czy proponowana czestotliwosc (co 60 tickow + event-driven) jest odpowiednia?
7. Jak powinien wygladac "plan" jako struktura danych? (sekwencja krokow? drzewo? cos prostszego?)

---

*Kontekst: branch `refactor/homeostasis`, 941 testow, Python 3.8+, Ollama llama3.1:8b*
