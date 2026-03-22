# Sesja 2026-03-21 - Bug fixes, Storage, K11 start

## Co zrobilismy

### 1. Analiza logow 12h
- Maria stabilna: health 0.837-0.985, zero alertow, 64MB RSS
- Znaleziono 3 bugi:
  - Bug 1: falszywy 100% exam pass rate (run_exam_if_ready zwracal bool)
  - Bug 2: beliefs nigdy nie aktualizowane (brak score/file w result dict)
  - Bug 3: deliberation consolidate trap (weak_topics zawsze 0.2 confidence)

### 2. Bug fixes (commit 24a3570)
- run_exam_if_ready() zwraca dict {executed, passed, score, file_id}
- Propagacja score/file przez teacher -> executor -> planner -> world_model
- Deliberation: 24h sliding window dla abandon count, confidence filtering
- Template priority: new_files -> learn_topic (nie explore_new)
- 1429 testow

### 3. Dysk 6TB (commit dfffaf5)
- /dev/sdb1 ext4 "maria-storage" zamontowany na /mnt/storage/
- fstab z nofail
- Struktura: backups/, data/{knowledge,logs,summaries}, vision/{snapshots,recordings,models}
- Backup przeniesiony na /mnt/storage/backups/ (30 kopii zamiast 7)

### 4. Storage Manager (commit dfffaf5)
- agent_core/storage/ - LogArchiver + DailySummary
- Archiwizacja: stare rekordy JSONL -> /mnt/storage/data/logs/ (raw) + summaries (kompakcja)
- Zintegrowane z SleepProcessor (faza archiwizacji przed REM)
- Pierwszy run: 3514 rekordow zarchiwizowanych
- 1445 testow

### 5. K11 Experiment System - fazy 1-2 (commit 09492d9)
- experiment_model.py: Proposal, Experiment, ExperimentReport, ParameterSpec
- parameter_registry.py: 12 parametrow z bounds i risk levels
- proposal_engine.py: 4 reguly (LOW_RETENTION, CONSECUTIVE_FAILURES, HIGH_COVERAGE, SLOW_EXECUTION)
- 34 testow, 1479 total

## Co zostaje na nastepna sesje

### K11 fazy 3-6:
- Faza 3: experiment_runner.py (setattr, health guard, timeout)
- Faza 4: report_generator.py (ADOPT/REJECT/INCONCLUSIVE)
- Faza 5: Facade + wiring + planner integration + REPL
- Faza 6: Web UI panel /experiments (approve/reject/comments/export)

### Plan w pliku:
/home/maria/.claude/plans/expressive-strolling-crab.md

### Hardware do kupienia:
- Tapo C200 (kamera WiFi z RTSP) - do Vision module

### Do monitorowania:
- Logi Mari po restarcie - czy bugi naprawione
- Czy deliberation zmienia strategie (nie tylko consolidate)
- Czy beliefs confidence rosnie po egzaminach
- NIM token usage (97k/100k dziennie)
