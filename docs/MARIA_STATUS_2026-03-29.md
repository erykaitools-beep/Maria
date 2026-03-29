# M.A.R.I.A. - Status Report
## Meta Analysis Recalibration Intelligence Architecture
### Data: 2026-03-29 | Wersja: Cognitive Core K1-K13 + Stabilization + Faza F

---

## 1. Czym jest M.A.R.I.A.?

Lokalny, autonomiczny agent AI do samodzielnego uczenia sie z plikow tekstowych.
Dziala na dedykowanym Mini PC (AMD Ryzen 5 7430U, 32GB RAM, Ubuntu 22.04).
Offline-first, prywatny, bez chmury.

**Poczatek projektu:** 2025-11-14
**Deploy na produkcje:** 2026-02-22
**Testy:** 2448 passing
**Sesji od narodzin:** ~1850+

---

## 2. Hardware i infrastruktura

| Komponent | Wartosc |
|-----------|---------|
| Mini PC | NiPoGi (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD) |
| OS | Ubuntu 22.04 LTS |
| Storage | 6TB ext4 dysk na logi/backupy/vision (/mnt/storage/) |
| Siec | LAN 192.168.178.32, WireGuard VPN |
| Bezpieczenstwo | UFW, fail2ban, SSH key-only, no root |
| Backup | Codziennie 3:00, 30 kopii na 6TB |
| Komunikacja | Telegram Bot (ClawBot) - 14 komend |
| Web UI | Flask+SocketIO :5000, PIN auth, 8 stron |

---

## 3. Multi-Model LLM Stack (7 modeli)

| Model | Rola | RAM | Status |
|-------|------|-----|--------|
| llama3.1:8b | Executor / Brain (MODEL-02) | 5GB | **Warm** (always loaded) |
| qwen3:8b | Strategic Planner (MODEL-01) | 5.5GB | Cold (on-demand) |
| qwen2.5-coder:7b | Coder (MODEL-03) | 5GB | Cold (on-demand) |
| Rule-based | Triage (MODEL-04) | 0GB | Keyword classifier |
| nomic-embed-text | Embeddings (MODEL-05) | 274MB | Cold (on-demand) |
| z-ai/glm5 (NIM) | Cloud API (MODEL-06) | 0GB | 40 RPM, expiry Aug 2026 |
| Codex CLI (ChatGPT) | Encyclopedia (MODEL-07) | 0GB | 10 calls/h |
| qwen2.5:3b | OpenClaw Effector | 2GB | Separate instance |

**Heavy mutex:** MODEL-01 i MODEL-03 nigdy jednoczesnie (RAM guard).
**Golden rule:** MODEL-02 warm, reszta on-demand.

---

## 4. Architektura modulow

```
                    +------------------+
                    |   Web UI (:5000)  |  8 stron: Status, Chat, Experiments,
                    |  Flask+SocketIO   |  Analysis, Traces, Validation,
                    +--------+---------+  Architecture, Login
                             |
                    +--------+---------+
                    |    main.py REPL   |     +-- Telegram (ClawBot, 14 cmds)
                    |   run_maria.py    |     |   /status /goals /validate
                    +--------+---------+     |   /trace /memory /learn /approve
                             |               |   /reject /priority /efapprove
              +--------------+---------------+   /efreject /efstatus /authority
              |
     +--------v---------+
     |  HomeostasisCore  |  12-phase tick loop (1Hz)
     |  (agent_core/)    |
     +--------+---------+
              |
   +----------+----------+----------+----------+
   |          |          |          |          |
   v          v          v          v          v
+------+  +------+  +------+  +------+  +------+
| K1   |  | K5   |  | K11  |  | K13  |  | Faza |
| Per- |  | Plan-|  | Exp- |  | Cre- |  |  F   |
| cep- |  | ner  |  | eri- |  | ati- |  | Vali-|
| tion |  |      |  | ment |  |  ve  |  | date |
+------+  +------+  +------+  +------+  +------+
   |          |          |          |          |
   v          v          v          v          v
+------+  +------+  +------+  +------+  +------+
| K2   |  | K6   |  | K12  |  | Sem  |  | Dis- |
| Sand-|  | World|  | Self-|  | Mem  |  | pute |
| box  |  | Model|  | Anal |  | (emb)|  | Log  |
+------+  +------+  +------+  +------+  +------+
   |          |
   v          v
+------+  +------+  +------+  +------+  +------+
| K3   |  | K7   |  | K8   |  | K9   |  | K10  |
| Goals|  | Auto-|  | Deli-|  | Meta-|  | Act  |
|      |  | nomy |  | bera |  | Cogn |  | Safe |
+------+  +------+  +------+  +------+  +------+
              |
              v
         +--------+     +---------+
         | Phase 5|     | OpenClaw|
         | Author-|     | Effector|
         | ity    |     | (ext)   |
         +--------+     +---------+
```

---

## 5. Cognitive Core - Kontrakty K1-K13 (COMPLETE)

| K# | Nazwa | Opis | Testy |
|----|-------|------|-------|
| K1 | Unified Perception | PerceptionEvent, Buffer, 6 adapterow | 131 |
| K2 | Sandbox/Production | SandboxManager, transaction log, recovery | 44 |
| K3 | Goal System | 4 typy celow, 6 statusow, PROPOSED flow | 63 |
| K4 | Evaluation | READ-ONLY observer, 5 metryk | 35 |
| K5 | Planner | ReAct loop, 13 action types, hybrid frequency | 136 |
| K6 | World Model | BeliefStore (JSONL, MERGE, cap 2000) | 69 |
| K7 | Autonomy Policy | FREE/GUARDED/RESTRICTED/FORBIDDEN + Phase 5 authority | 45 |
| K8 | Deliberation | 3 strategy templates, IntentTracker | 49 |
| K9 | Meta-Cognition | ReflectionStore, ConfidenceTracker, needs_human() | 73 |
| K10 | Action Safety | SafetyMode(3), AuditLog, EffectValidator | 52 |
| K11 | Experiments | ProposalEngine, ParameterRegistry, ADOPT/REJECT | 67 |
| K12 | Self-Analysis | NIM cascade analyzer, PROPOSED goals | 45 |
| K13 | Creative Module | TensionDetector, NIM engines, meta-goals | 130 |

---

## 6. Stabilization Roadmap (6 faz - COMPLETE)

| Phase | Nazwa | Opis | ADR |
|-------|-------|------|-----|
| 1 | Decision Traceability | Episode-based traces, correlation IDs | ADR-022 |
| 2 | Memory Consistency | MemoryQuery API, staleness fixes, grounding | ADR-023 |
| 3 | Scheduler Hardening | Execution budgets, Ollama timeouts, degradation | ADR-024 |
| 4 | Autonomy Governance | Cross-metric validation, promotion audit | ADR-025 |
| 5 | Effector Safety | 5-level authority, approval queue, anti-cascade | ADR-026 |
| 6 | Readiness Review | 100-cycle marathon, 15-point checklist | - |

**All 5 gates passed:** Gate A (tracing) -> Gate B (memory) -> Gate C (budgets) -> Gate D (governance) -> Gate E (readiness).

---

## 7. Faza F: Multi-Source Learning (COMPLETE)

Maria uczy sie z jednego LLM (Ollama), potem drugi LLM (NIM) niezaleznie analizuje ten sam material. Roznice logowane jako spory.

| Komponent | Opis |
|-----------|------|
| CrossValidator | Porownanie primary (Ollama) vs secondary (NIM) |
| ConfidenceScorer | Rule-based scoring (Jaccard similarity, 3 wymiary) |
| DisputeLog | JSONL persistence sporow, thread-safe |
| Planner trigger | _maybe_validate() co 6h, K7 GUARDED |
| Belief update | OBSERVATION->FACT (>0.7), demotion HYPOTHESIS (<0.3) |
| Web UI | /validation page (stats, disputes, history) |
| Telegram | /validate [disputes\|unresolved] |

---

## 8. Homeostasis - 12-fazowy tick loop

```
Phase  1: SENSE (5 sensors: resource, cognitive, thermal, power, time)
Phase  2: INTERPRET (raw -> semantic state)
Phase  3: VALIDATE (constraints + CRITICAL alarms)
Phase  4: DECIDE MODE (ACTIVE -> REDUCED -> SLEEP -> SURVIVAL)
Phase  5: GENERATE CORRECTIVE ACTIONS
Phase  6: EXECUTE CORRECTIVE ACTIONS
Phase  7: UPDATE HEALTH SCORE
Phase  8: PERCEIVE (K1 - aggregate events -> PerceptionBuffer)
Phase  9: TEACHER TRIGGER (idle >= 10min -> auto-learn)
Phase  9.5: MODEL SCHEDULER (load/unload, RAM guard, heavy mutex)
Phase 10: PLANNER (K5-K13: guard -> select -> plan -> execute -> trace)
Phase 11: TELEGRAM (poll co 30s, operator commands)
Phase 12: AUDIT & LOG
```

---

## 9. Telegram (ClawBot) - 14 komend

| Komenda | Opis |
|---------|------|
| /status | Stan systemu (mode, health, planner, knowledge) |
| /goals | Lista celow (active + proposed, ID, priority) |
| /validate | Cross-validation stats |
| /validate disputes | Ostatnie spory |
| /trace [N\|stats\|failed\|ep-ID] | Decision traces |
| /memory \<temat\> | Co Maria wie o temacie |
| /memory gaps | Luki w wiedzy |
| /learn \<temat\> | Naucz sie o temacie |
| /approve \<id\> | Zatwierdz proposed goal |
| /reject \<id\> | Odrzuc proposed goal |
| /priority \<id\> \<0-1\> | Zmien priorytet celu |
| /efapprove \<id\> | Zatwierdz akcje efektora |
| /efreject \<id\> | Odrzuc akcje efektora |
| /efstatus | Status efektora i approval queue |
| /authority [level] | Zmien poziom autoryzacji (observe/confirm/bounded) |
| /restart | Restart Marii (systemd wskrzesi po 10s) |

---

## 10. Web UI (8 stron)

| Strona | URL | Opis |
|--------|-----|------|
| Status | /status | 8-panel Metaoperator dashboard |
| Chat | / | WebSocket chat z Maria |
| Experiments | /experiments | K11 propozycje, raporty, parametry |
| Analysis | /analysis | K12 self-analysis raporty |
| Traces | /traces | Decision traces (Phase 1) |
| Validation | /validation | Cross-validation stats + disputes (Faza F) |
| Architecture | /architecture | Force graph + pipeline + data flow |
| Login | /login | PIN authentication |

---

## 11. Stabilnosc produkcyjna

| Metryka | Wartosc |
|---------|---------|
| RAM (Maria process) | ~67MB RSS |
| Health score | 0.84-0.99 |
| OOM crashes since deploy | 0 (fix 2026-03-18) |
| Uptime (typical) | 24/7 z systemd auto-restart |
| Ollama timeout | 120-180s per role (Phase 3) |
| Episode budget | max 10 LLM calls, 5min latency |
| Authority default | OBSERVE (safe, backward compatible) |

---

## 12. Decyzje architektoniczne (ADR)

26 ADR zarejestrowanych (ADR-001 do ADR-027), pelna lista w `docs/ROADMAP.md`.

Kluczowe:
- **ADR-001:** JSONL jako source of truth
- **ADR-013:** Planner rule-based (zero LLM, deterministic)
- **ADR-014:** Najpierw mozg, potem zmysly
- **ADR-015:** Multi-organ model stack (heavy mutex)
- **ADR-021:** Semantic Memory via embeddings
- **ADR-026:** Effector safety envelope (5-level authority)
- **ADR-027:** Multi-Source Learning via post-learning cross-validation

---

## 13. Co dalej

| Priorytet | Opis | Status |
|-----------|------|--------|
| Belief Store compaction | Compaction oparta na waznosci, dedup | PLANNED |
| CDL dopracowanie | Lepsze rozpoznawanie intencji, feedback loop | PLANNED |
| Web UI polish | Dense mode, sidebar | PLANNED |
| Vision (Warstwa 10) | Kamera Tapo C200 z RTSP | CZEKA NA SPRZET |
| Smart Home (Warstwa 11) | Shelly/Tasmota IoT | CZEKA NA SPRZET |

---

*Wygenerowano: 2026-03-29*
*Testy: 2448 passing | Kontrakty: K1-K13 COMPLETE | Stabilization: 6/6 COMPLETE | Faza F: COMPLETE*
