# M.A.R.I.A. - Persistence Contract v1.0

> Jeden plik prawdy: jak zapisujemy dane, jaki format, jakie sciezki, kto co czyta i pisze.
> Data: 2026-04-14. Autor: Eryk (decyzja) + Claude (audit).

## A. Zasady nadrzedne

1. **JSONL jako source of truth** (ADR-001). Kazdy rekord to jedna linia JSON.
2. **Lokalne pliki** - zero chmury, zero remote sync w runtime.
3. **Append-first** - domyslnie dopisujemy, nie nadpisujemy.
4. **Explicit save** - jesli store ma `save()`, MUSISZ go zawolac po mutacji. Inaczej dane zyja tylko w RAM.
5. **Thread-safe** - kazdy store uzywa `threading.Lock` lub `threading.RLock`.
6. **Graceful degradation** - brak pliku = pusty store, nie crash.

## B. Cztery wzorce zapisu

### B1. APPEND_ONLY
Plik tylko rosnie. Nowe rekordy dopisywane na koniec. Stare archiwizowane przez LogArchiver.

```python
# Wzorzec:
with open(path, "a") as f:
    f.write(json.dumps(record) + "\n")
```

**Uzywa:** homeostasis_events, action_audit, decision_traces, llm_tape, critique_reports, self_analysis_reports, exam_results

### B2. MERGE (last-wins-by-key)
Append-only na dysku, ale na LOAD ostatni rekord per klucz wygrywa. Plik rosnie z kazdym updatem.

```python
# WRITE: append
with open(path, "a") as f:
    f.write(json.dumps(record) + "\n")

# READ: last-wins dedup
records = {}
for line in open(path):
    r = json.loads(line)
    records[r[KEY_FIELD]] = r  # nadpisuje starsze
```

**Compaction:** przepisz plik z unikalnymi rekordami gdy plik > 2x pamiec.

**Uzywa:** goals (key=id), beliefs (key=belief_id), knowledge_index (key=id), reminders (key=reminder_id), todos (key=todo_id), workflows (key=workflow_id), web_fetch_registry (key=url), creative_meta_goals (key=goal_id), cognitive_bulletin (key=entry_id)

### B3. OVERWRITE (atomic JSON)
Caly plik nadpisywany atomowo (temp + rename). Dla singletonu stanu.

```python
# Wzorzec:
import tempfile, os
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(state, f, indent=2)
os.replace(tmp, path)  # atomic on same filesystem
```

**Uzywa:** planner_state.json, user_profile.json, operator_model.json, consciousness_identity.json, environment_state.json, model_health.json, nim_token_usage.json, authority_config.json, code_self_model.json

### B4. BUFFERED
Akumuluje w pamiec, flush co N sekund lub N rekordow.

```python
# Wzorzec:
self._buffer.append(record)
if len(self._buffer) >= FLUSH_SIZE or time.time() - self._last_flush > FLUSH_INTERVAL:
    self._flush()
```

**Uzywa:** homeostasis_events (10s/50 events), personality_experiences (session flush)

## C. Katalog plikow

### C1. meta_data/ - dane runtime

| Plik | Wzorzec | Klucz | Writer | Readers | Max/Rotacja |
|------|---------|-------|--------|---------|-------------|
| `goals.jsonl` | MERGE | `id` | GoalStore.save() | Planner, K7, K12, Telegram | 20 active (pruned) |
| `beliefs.jsonl` | MERGE | `belief_id` | BeliefStore.save() | K6, MemoryQuery, Critic | 2000 (smart prune) |
| `planner_decisions.jsonl` | APPEND | - | PlannerCore._log_decision() | K12, Web UI | Archival (LogArchiver) |
| `planner_state.json` | OVERWRITE | - | PlannerCore._save_state() | Planner (reload) | 1 file |
| `decision_traces.jsonl` | APPEND | `episode_id` | TraceStore.record() | K7, K10, Web UI | 200 in-memory |
| `action_audit.jsonl` | APPEND | - | AuditLog.record() | K10, K12 | 200 in-memory |
| `homeostasis_events.jsonl` | BUFFERED | - | EventLogger._flush() | Web UI, Storage | 5000 -> keep 2000 |
| `llm_tape.jsonl` | APPEND | - | LLMTape.record() | K12, EvidenceCollector | 50MB rotate |
| `evaluation_reports.jsonl` | APPEND | - | EvaluationObserver | K12, Web UI | Archival |
| `self_analysis_reports.jsonl` | APPEND | - | SelfAnalysis | K12, Web UI | Archival |
| `critique_reports.jsonl` | APPEND | - | CriticAgent | Web UI, Telegram | Archival |
| `creative_events.jsonl` | APPEND | - | CreativeStore | Creative module | 1000 in-memory |
| `creative_journal.jsonl` | APPEND | `entry_id` | CreativeStore | Creative reflection | 500 entries |
| `creative_meta_goals.jsonl` | MERGE | `goal_id` | CreativeStore | Creative module | 500 goals |
| `creative_workspace_sessions.jsonl` | APPEND | - | CreativeStore | Creative module | 200 sessions |
| `creative_tension_streaks.jsonl` | APPEND | - | CreativeStore | Priority escalation | 200 records |
| `cognitive_bulletin.jsonl` | MERGE | `entry_id` | BulletinStore | GapPlanner, ExpertBridge | configurable |
| `deliberation_intents.jsonl` | APPEND+REWRITE | - | IntentTracker | K8, Planner | 500 records |
| `reflections.jsonl` | APPEND+REWRITE | `reflection_id` | ReflectionStore | K9, K12 | 5000 records |
| `conversation_history.jsonl` | APPEND | - | ConversationMemory | Consciousness, REPL | last 20 loaded |
| `conversation_summaries.jsonl` | APPEND | - | ConversationMemory | Session restore | unbounded |
| `personality_experiences.jsonl` | BUFFERED | - | ExperienceTracker | Trait evolution | session flush |
| `web_fetch_registry.jsonl` | MERGE | `url` | FetchRegistry | Web fetcher dedup | unbounded |
| `topic_hints.jsonl` | APPEND | - | K12 RecommendationApplier | TopicSuggester | unbounded |
| `semantic_vectors.jsonl` | APPEND | - | VectorStore | SemanticMemory | 10k vectors |
| `reminders.jsonl` | MERGE | `reminder_id` | ReminderStore | Scheduler, Telegram | unbounded |
| `todos.jsonl` | MERGE | `todo_id` | TodoStore | Telegram, Web UI | unbounded |
| `workflows.jsonl` | MERGE+COMPACT | `workflow_id` | WorkflowStore | WorkflowEngine | auto-compact |
| `incidents.jsonl` | APPEND | `incident_id` | IncidentMemory | TrustScorer | 500 in-memory |
| `promotion_history.jsonl` | APPEND | - | AutoPromotion | TrustScorer, Telegram | unbounded |
| `claude_tasks.jsonl` | MERGE | `task_id` | TaskStore | Telegram /tasks | unbounded |
| `claude_interactions.jsonl` | APPEND | - | ClaudeClient | K12 | unbounded |
| `codex_interactions.jsonl` | APPEND | - | CodexClient | K12 | unbounded |
| `user_profile.json` | OVERWRITE | - | UserProfile._save() | Brain, Telegram, Web UI | 1 file |
| `operator_model.json` | OVERWRITE | - | OperatorModel | Salience, Planning | 1 file |
| `consciousness_identity.json` | OVERWRITE | - | IdentityStore._save() | Identity, Session | 1 file |
| `environment_state.json` | OVERWRITE | - | EnvironmentManager | Mode detection | 1 file |
| `model_health.json` | OVERWRITE | - | ModelScheduler | Model selection | 1 file |
| `nim_token_usage.json` | OVERWRITE | - | TokenBudget | NIM routing | 1 file |
| `authority_config.json` | OVERWRITE | - | AuthorityManager | K7, Telegram | 1 file |
| `code_self_model.json` | OVERWRITE | - | CodeAnalyzer | Introspection | 1 file |

### C2. memory/ - dane wiedzy (legacy)

| Plik | Wzorzec | Klucz | Writer | Readers |
|------|---------|-------|--------|---------|
| `knowledge_index.jsonl` | MERGE | `id` | LearningAgent | Teacher, Planner, MemoryQuery |
| `exam_results.jsonl` | APPEND | - | ExamAgent | Teacher, Evaluation |
| `maria_knowledge_base.jsonl` | APPEND | - | LearningAgent (compressed) | MemoryQuery |
| `maria_longterm_memory.jsonl` | APPEND | - | Legacy episodic | MemoryQuery |

### C3. /mnt/storage/data/ - archiwum (6TB)

| Sciezka | Zawartosc | Writer |
|---------|-----------|--------|
| `logs/` | Stare rekordy JSONL (rotacja) | LogArchiver |
| `summaries/` | Dzienne podsumowania (compacted) | DailySummary |
| `backups/` | Codzienne kopie meta_data/ | cron backup.sh |

## D. Reguly dla nowych modulow

### D1. Tworzysz nowy store? Wybierz wzorzec:
- Dane tylko rosna (logi, eventy) -> **APPEND_ONLY**
- Dane maja ID i moga sie zmieniac -> **MERGE** z explicit `save()`
- Jeden obiekt stanu -> **OVERWRITE** z atomic rename

### D2. MERGE store checklist:
- [ ] Klasa dziedziczy logike load/save/compact
- [ ] KEY_FIELD zdefiniowany jako stala
- [ ] `save()` wolane po KAZDEJ mutacji (propose, update, delete)
- [ ] Compaction triggerowana gdy lines > 2x records
- [ ] Max records w pamieci (smart prune jesli przekroczony)

### D3. Naming convention:
- JSONL: `meta_data/{module_name}_{data_type}.jsonl` (np. `creative_events.jsonl`)
- JSON state: `meta_data/{module_name}_state.json` (np. `planner_state.json`)
- Klucz ID: `{prefix}-{uuid_hex[:8]}` (np. `goal-k12-2b5fdcdc`, `belief-9ad96f67e297`)

### D4. Thread safety:
- Kazdy write path chroniony `threading.Lock()`
- Jeden lock per store (nie per method)
- `with self._lock:` opakowuje caly write + flush

### D5. Error handling:
- Brak pliku = pusty store, log warning, kontynuuj
- Uszkodzona linia JSONL = skip + log warning
- Brak katalogu = `mkdir(parents=True)` przy pierwszym uzyciu

## E. Znane problemy (do naprawienia)

| Problem | Status | Priorytet |
|---------|--------|-----------|
| Brak wspolnej klasy bazowej dla store'ow | OPEN | Sredni |
| creative_store ma 6 plikow w jednej klasie | OPEN | Niski |
| web_fetch_registry rosnie bez limitu | OPEN | Niski |
| topic_hints rosnie bez limitu | OPEN | Niski |
| Brak compaction dla goals.jsonl | OPEN | Sredni |
| deliberation_intents uzywa REWRITE (powolne) | OPEN | Niski |

---

*Wersja 1.0 - 2026-04-14*
