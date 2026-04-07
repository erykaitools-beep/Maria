# M.A.R.I.A. - Status Report
## Meta Analysis Recalibration Intelligence Architecture
### Ostatnia aktualizacja: 2026-04-07 | Wersja: V3 DEPLOYED

---

## 1. Czym jest M.A.R.I.A.?

Lokalny, autonomiczny agent AI do samodzielnego uczenia sie z plikow tekstowych.
Dziala na dedykowanym Mini PC (AMD Ryzen 5 7430U, 32GB RAM, Ubuntu 22.04).
Offline-first, prywatny, bez chmury.

**Poczatek projektu:** 2025-11-14
**Deploy na produkcje:** 2026-02-22
**Testy:** 3352 passing
**Runtime:** maria.py (daemon + Web UI, jeden proces)

---

## 2. Hardware i infrastruktura

| Komponent | Wartosc |
|-----------|---------|
| Mini PC | NiPoGi (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD) |
| OS | Ubuntu 22.04 LTS |
| Storage | 6TB ext4 dysk na logi/backupy (/mnt/storage/) |
| Siec | LAN 192.168.178.32, WireGuard VPN |
| Bezpieczenstwo | UFW, fail2ban, SSH key-only, no root |
| Backup | Codziennie 3:00, 30 kopii na 6TB |
| Kamera | Innomaker U20CAM-1080PD&N-S1 (USB, /dev/video0) |
| Komunikacja | Telegram Bot (ClawBot) - 20+ komend |
| Web UI | Flask+SocketIO :5000, PIN auth, 10 stron |
| Systemd | maria.service (maria.py full mode, Restart=on-failure) |

---

## 3. Multi-Model LLM Stack (9 modeli)

| Model | Rola | RAM | Status |
|-------|------|-----|--------|
| llama3.1:8b | Executor / Brain (MODEL-02) | 5GB | **Warm** (always loaded) |
| qwen3:8b | Strategic Planner (MODEL-01) | 5.5GB | Cold (on-demand) |
| qwen2.5-coder:7b | Coder (MODEL-03) | 5GB | Cold (on-demand) |
| Rule-based | Triage (MODEL-04) | 0GB | Keyword classifier |
| nomic-embed-text | Embeddings (MODEL-05) | 274MB | Cold (on-demand) |
| llava | Vision (scene description) | 4.7GB | Cold (on-demand, 30s/call) |
| z-ai/glm5 (NIM) | Cloud API (MODEL-06) | 0GB | 40 RPM, expiry Aug 2026 |
| Claude Code CLI | Code analysis (MODEL-07) | 0GB | 3/h, 15/day, 5min timeout |
| Codex CLI (ChatGPT) | Encyclopedia (MODEL-08) | 0GB | 10/h, 5min timeout |
| qwen2.5:3b | OpenClaw Effector | 2GB | Separate instance |

**Heavy mutex:** MODEL-01 i MODEL-03 nigdy jednoczesnie (RAM guard).
**Golden rule:** MODEL-02 warm, reszta on-demand.

---

## 4. Architektura - tick loop

```
maria.py (jeden proces, systemd)
  |
  +-- Daemon (main thread)
  |     +-- Homeostasis 1Hz tick loop
  |     |     Phase 1-7: sense, interpret, validate, mode, actions, health
  |     |     Phase 8: perception aggregation (K1)
  |     |     Phase 8.5: vision (USB cam + preprocessing + motion/scene)
  |     |     Phase 9: audit log (co 60 tickow)
  |     |     Phase 9.5: model scheduler (ollama load/unload)
  |     |     Phase 10: planner (K5 ReAct loop, co 60 tickow)
  |     |     Phase 11: telegram poll + commands
  |     |
  |     +-- Background threads (on demand):
  |           /claude, /codex -> subprocess (5min timeout, PDF export)
  |           Creative K13 reflection
  |           K12 self-analysis
  |
  +-- Web UI thread (Flask-SocketIO)
        Port 5000, PIN auth, shared Vision cortex
        Chat + grounding pipeline
        10 stron: Status, Chat, Experiments, Analysis,
        Traces, Validation, Architecture, Vision, Critique, Login
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
| K6 | World Model | BeliefStore v3 (evidence, compaction, decay) | 69 |
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

---

## 7. Vision (WIRED, 2026-04-06)

| Komponent | Opis |
|-----------|------|
| Sensor | USB webcam via OpenCV (640x480@30fps, auto-flip) |
| Preprocessing | Normalize, quality assess, degradation detect |
| Motion | Frame differencing (<8ms per tick) |
| Scene | Statistics in tick, LLaVA on-demand (30s) |
| LLaVA prompt | 3-warstwowy: OBIEKTY [PEWNE/MOZLIWE/NIEPEWNE] + OPIS faktyczny |
| Grounding | "co widzisz?" -> EvidenceCollector -> LLaVA |
| REPL | /vision, /vision snap, /vision health, /vision motion |
| Web UI | /api/vision/status, /last, /health, /frame |

---

## 8. Task Pipeline + PDF Export (2026-04-07)

| Komponent | Opis |
|-----------|------|
| TaskStore | JSONL persistence (meta_data/claude_tasks.jsonl) |
| Lifecycle | PENDING -> RUNNING -> COMPLETED/FAILED/TIMEOUT/INTERRUPTED |
| Recovery | recover_interrupted() at startup, operator notified |
| PDF | Auto-generated for every completed result (fpdf2 + DejaVu) |
| Telegram | /tasks [N], /pdf <task_id> |
| Timeout | 5min (was 3min), explicit error messages |

---

## 9. V3 Orchestrator (15 modulow, DEPLOYED)

| Phase | Moduly | Opis |
|-------|--------|------|
| A | UnifiedLauncher, OnboardingFlow, UserFacingSelfModel | maria.py, first-run, self-description |
| B | TaskOrchestrator, TaskDecomposer, ExecutionPlanBuilder | Task pipeline, decomposition, feasibility |
| C | CostEstimator, TimeEstimator, FreeVsPaidPlanner | Practical intelligence, budget planning |
| D | ExecutionRouter, ToolCapabilityRegistry, TaskProgressTracker, LimitationReporter | Execution bridge |
| E | ProductShell, V3Module | Unified facade, /v3 REPL |

---

## 10. Telegram (ClawBot) - 20+ komend

| Kategoria | Komendy |
|-----------|---------|
| System | /status, /restart, /authority [level], /help |
| Cele | /goals, /approve, /reject, /priority |
| Wiedza | /learn, /nauka, /memory, /beliefs, /validate, /board |
| Kodowanie | /code, /code approve/reject/cancel/history |
| AI asystenci | /claude, /codex, /analyze |
| Diagnostyka | /tasks, /pdf, /trace, /efapprove, /efreject, /efstatus |

---

## 11. Stabilnosc produkcyjna

| Metryka | Wartosc |
|---------|---------|
| RAM (Maria process) | ~95-170MB RSS |
| Health score | 0.84-0.99 |
| OOM crashes since deploy | 0 (fix 2026-03-18) |
| Uptime | 24/7 z systemd auto-restart |
| Ollama timeout | 120-180s per role |
| Claude/Codex timeout | 300s (5min) |
| Episode budget | max 10 LLM calls, 5min latency |
| Authority default | OBSERVE (safe, backward compatible) |
| Startup cooldown | 6h (Telegram notification) |

---

## 12. Co dalej

| Priorytet | Opis | Status |
|-----------|------|--------|
| Git remote | GitHub private repo, sync na laptop | PLANNED |
| Web UI + Telegram | Task pipeline w Web UI, /tasks podglad | PLANNED |
| Operator UX | Dense mode, sidebar, Web UI v2 polish | PLANNED |
| Smart Home (Warstwa 11) | Shelly/Tasmota IoT | CZEKA NA SPRZET |

---

*Wygenerowano: 2026-04-07*
*Testy: 3352 | K1-K13 COMPLETE | Stabilization 6/6 | V3 DEPLOYED | Vision WIRED | Task Pipeline + PDF*
