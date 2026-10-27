# M.A.R.I.A. - Persistence Contract v1.0

> **Historical inventory, April 2026.** Later chat request receipts use SQLite;
> not every current state writer is atomic. See the [runtime guide](runtime-guide.md#configuration-and-persistence)
> and [chat receipt implementation](../maria_ui/chat_turns.py). Retained design
> rules below should not be read as verified guarantees for every store.

---

> One file of truth: how we persist data, in what format, under what paths, who reads and writes what.
> Date: 2026-04-14. Author: Eryk (decision) + Claude (audit).

## A. Governing principles

1. **JSONL as source of truth** (ADR-001). Every record is a single JSON line.
2. **Local files** - no cloud, no remote sync at runtime.
3. **Append-first** - by default we append, we do not overwrite.
4. **Explicit save** - if a store has `save()`, you MUST call it after a mutation. Otherwise the data lives in RAM only.
5. **Thread-safe** - every store uses `threading.Lock` or `threading.RLock`.
6. **Graceful degradation** - a missing file means an empty store, not a crash.

## B. Four write patterns

### B1. APPEND_ONLY
The file only grows. New records are appended at the end. Old ones are archived by LogArchiver.

```python
# Pattern:
with open(path, "a") as f:
    f.write(json.dumps(record) + "\n")
```

**Used by:** homeostasis_events, action_audit, decision_traces, llm_tape, critique_reports, self_analysis_reports, exam_results

### B2. MERGE (last-wins-by-key)
Append-only on disk, but on LOAD the last record per key wins. The file grows with every update.

```python
# WRITE: append
with open(path, "a") as f:
    f.write(json.dumps(record) + "\n")

# READ: last-wins dedup
records = {}
for line in open(path):
    r = json.loads(line)
    records[r[KEY_FIELD]] = r  # overwrites older ones
```

**Compaction:** rewrite the file with unique records once the file exceeds 2x the in-memory set.

**Used by:** goals (key=id), beliefs (key=belief_id), knowledge_index (key=id), reminders (key=reminder_id), todos (key=todo_id), workflows (key=workflow_id), web_fetch_registry (key=url), creative_meta_goals (key=goal_id), cognitive_bulletin (key=entry_id)

### B3. OVERWRITE (atomic JSON)
The whole file is overwritten atomically (temp + rename). For a state singleton.

```python
# Pattern:
import tempfile, os
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(state, f, indent=2)
os.replace(tmp, path)  # atomic on same filesystem
```

**Used by:** planner_state.json, user_profile.json, operator_model.json, consciousness_identity.json, environment_state.json, model_health.json, nim_token_usage.json, authority_config.json, code_self_model.json

### B4. BUFFERED
Accumulates in memory, flushes every N seconds or every N records.

```python
# Pattern:
self._buffer.append(record)
if len(self._buffer) >= FLUSH_SIZE or time.time() - self._last_flush > FLUSH_INTERVAL:
    self._flush()
```

**Used by:** homeostasis_events (10s/50 events), personality_experiences (session flush)

## C. File catalog

### C1. meta_data/ - runtime data

| File | Pattern | Key | Writer | Readers | Max/Rotation |
|------|---------|-----|--------|---------|--------------|
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

### C2. memory/ - knowledge data (legacy)

| File | Pattern | Key | Writer | Readers |
|------|---------|-----|--------|---------|
| `knowledge_index.jsonl` | MERGE | `id` | LearningAgent | Teacher, Planner, MemoryQuery |
| `exam_results.jsonl` | APPEND | - | ExamAgent | Teacher, Evaluation |
| `maria_knowledge_base.jsonl` | APPEND | - | LearningAgent (compressed) | MemoryQuery |
| `maria_longterm_memory.jsonl` | APPEND | - | Legacy episodic | MemoryQuery |

### C3. /mnt/storage/data/ - archive (6TB)

| Path | Contents | Writer |
|------|----------|--------|
| `logs/` | Old JSONL records (rotation) | LogArchiver |
| `summaries/` | Daily summaries (compacted) | DailySummary |
| `backups/` | Daily copies of meta_data/ | cron backup.sh |

## D. Rules for new modules

### D1. Adding a new store? Pick a pattern:
- Data only grows (logs, events) -> **APPEND_ONLY**
- Data has an ID and can change -> **MERGE** with an explicit `save()`
- A single state object -> **OVERWRITE** with atomic rename

### D2. MERGE store checklist:
- [ ] The class inherits the load/save/compact logic
- [ ] KEY_FIELD defined as a constant
- [ ] `save()` called after EVERY mutation (propose, update, delete)
- [ ] Compaction triggered when lines > 2x records
- [ ] Max records held in memory (smart prune if exceeded)

### D3. Naming convention:
- JSONL: `meta_data/{module_name}_{data_type}.jsonl` (e.g. `creative_events.jsonl`)
- JSON state: `meta_data/{module_name}_state.json` (e.g. `planner_state.json`)
- ID key: `{prefix}-{uuid_hex[:8]}` (e.g. `goal-k12-2b5fdcdc`, `belief-9ad96f67e297`)

### D4. Thread safety:
- Every write path guarded by `threading.Lock()`
- One lock per store (not per method)
- `with self._lock:` wraps the whole write + flush

### D5. Error handling:
- Missing file = empty store, log a warning, continue
- Corrupted JSONL line = skip + log a warning
- Missing directory = `mkdir(parents=True)` on first use

## E. Known issues (to be fixed)

| Issue | Status | Priority |
|-------|--------|----------|
| No shared base class for stores | OPEN | Medium |
| creative_store holds 6 files in one class | OPEN | Low |
| web_fetch_registry grows without a limit | OPEN | Low |
| topic_hints grows without a limit | OPEN | Low |
| No compaction for goals.jsonl | OPEN | Medium |
| deliberation_intents uses REWRITE (slow) | OPEN | Low |

---

*Version 1.0 - 2026-04-14*
