# Audyt M.A.R.I.A. - 2026-04-09

## Kontekst
Eryk poprosil o pelny audyt systemu - zero kodowania, tylko analiza.
Sprawdzilismy: moduly, zaleznosci, K1-K13, pliki JSONL, planner, Web UI, Telegram, testy.
Potem naprawilismy 7 z 8 znalezionych problemow.

## NAPRAWIONE PROBLEMY

### 1. NIESKONCZONA PETLA CRITIQUE (KRYTYCZNY) - NAPRAWIONY
- Cel `goal-e8a0fd7887ab` ("Krytyka jakosci wiedzy") - CRITIQUE co ~60s od 163h
- `_exec_critique()` nie mial logiki zakonczenia celu
- 6300/28282 decyzji (22%) to CRITIQUE
- **Fix:** dodany `_complete_oneshot_goal()` helper w action_executor.py
- Zamyka cel po udanym critique/self_analyze/creative
- Naprawiono dane: 2x critique ACHIEVED, 5x kamera ABANDONED, 1x autoanaliza ACHIEVED

### 2. STALE GOALS - AUTO-ABANDON (KRYTYCZNY) - NAPRAWIONY
- Cele PENDING > 7 dni bez progressu sa auto-abandonowane
- `_cleanup_stale_goals()` w planner_core.py
- Uruchamia sie w kazdym `_select_goal()` (lightweight)

### 3. LOG ROTATION W ACTIVE MODE (WYSOKI) - NAPRAWIONY
- Phase 9.7 w tick loop: `_maybe_archive_logs()` co 24h
- Dodane do MANAGED_LOGS: decision_traces, critique_reports, creative_events, dream_log
- Archiwizacja dziala nawet bez SLEEP mode

### 4. SharedContext - 10 BRAKUJACYCH POL (WYSOKI) - NAPRAWIONY
- Dodane: cross_validator, dispute_log, critic_agent, bulletin_store
- knowledge_auditor, gap_planner, expert_bridge
- authority_manager, approval_queue, tool_budget

### 5. STALE SUBSYSTEMS (SREDNI) - NAPRAWIONY
- Wiekszosc stale plikow to efekt critique loop (beliefs, evaluation, vectors)
- code_self_model.json: IntrospectionScheduler nigdy nie byl auto-started
- Fix: wired scheduler w homeostasis_module.py (24h interval)

### 6. NOTIFIER TERNARY BUG (SREDNI) - NAPRAWIONY
- notifier.py:213 - operator precedence f-stringa vs ternary
- Wiadomosc notify_needs_human byla ucietoa przy pustym reason

### 7. DORMANT FILES (NISKI) - NAPRAWIONY
- Usuniete: trauma_events.jsonl (empty), rewards_log.jsonl (defunct), decisions_log.jsonl (superseded)
- Usuniete: topic_hints.jsonl.bak

## NIENAPRAWIONE (na pozniej)

### 8. BRAKUJACE TESTY
- homeostasis/ (5284 LOC) - 0 bezposrednich testow
- adapters/ (1221 LOC) - 0 testow
- routing/ (1149 LOC) - 0 bezposrednich
- metacontrol/ (273 LOC) - 0 testow
- ui/ (746 LOC) - 0 testow

## CO DZIALA DOBRZE (potwierdzone audytem)
- K1-K13 pelna zgodnosc kontraktowa
- Brak circular imports
- Brak korupcji danych JSONL (wszystkie waliduja)
- Telegram/Web UI bezpieczne (PIN, XSS, None checks)
- Teacher agent 95% success rate
- Health 0.91, 3454 testow passing
- Signal handling, graceful shutdown

## OBSERWACJE
- Eryk przyznal ze rzadko sprawdza logi - warto dodac automatyczne alerty o anomaliach
- Critique loop dzialal 163h bez wykrycia - potrzebna lepsza observability
- Maria generalnie dziala dobrze, ale potrzebuje "oka" na stuck loops
- Flaky test_tick_latency (200ms limit, czasem przekracza na obciazonym CPU)
