# M.A.R.I.A. - Development Roadmap (Maria 1.0)
> Version: 2.2 | Last updated: 2026-05-16
>
> **Strategiczna mapa kierunkowa.** Dla bieżącej rzeczywistości desk/milestone — patrz `docs/PROGRESS_LOG.md` (operacyjna prawda).
> **Szczegolowy plan rozwoju:** `docs/DEVELOPMENT_PLAN.md` (zatwierdzony 2026-02-28)
> **Design docs dla aktualnej fazy:** `docs/plans/DESIGN_INTENT_ROUTER.md`, `docs/plans/DESIGN_PLANNER_V2.md`
> **Werdykt Fazy J:** `docs/plans/FAZA_J_WERDYKT_2026-05-16.md` (MIXED — silnik pomaga, strukturalne luki pozostają)
>
> **Hipoteza 1 w AGI experiment** (znany paradygmat skalowany do AGI).
> Hipoteza 2 = Maria 2.0 (`docs/MARIA_2.0/`). Meta: `docs/AGI_HYPOTHESES.md`.
> Faza L (AGI Direction) to końcowy horyzont tej ścieżki — kryteria
> AGI-capable opisane w AGI_HYPOTHESES.md.
>
> **Zasada split (od 2026-05-16):** ROADMAP = strategia długoterminowa (kierunek, cele faz, AGI vision).
> PROGRESS_LOG = bieżąca rzeczywistość (deski, daty, link do dowodów). Gdy się rozjeżdżają, PROGRESS_LOG ma rację.

## Overview

Rozwoj M.A.R.I.A. podzielony jest na fazy:

| Faza | Nazwa | Cel | Status |
|------|-------|-----|--------|
| A | Stabilizacja | Naprawic bledy, stabilny runtime | **COMPLETE** (2026-01-27) |
| B | Full Homeostasis | Pelna autonomia z petlami regulacji | **COMPLETE** (2026-01-28) |
| C | Consciousness | Samowiedza, percepcja, tozsamosc | **COMPLETE** (2026-02-27) |
| C.5 | Kontrakty K1-K4 | Perception, Sandbox, Goals, Evaluation | **COMPLETE** (2026-03-01) |
| C.6 | Cognitive Core K5-K13 | Planner, World Model, Autonomy, Creative | **COMPLETE** (2026-03-25) |
| C.7 | Infrastructure | Telegram, Semantic Memory, OpenClaw, Web UI v2 | **COMPLETE** (2026-03-27) |
| C.8 | Stabilization Roadmap | Tracing, Memory, Budgets, Safety (6 faz) | **COMPLETE** (2026-03-29) |
| F | Multi-Source Learning | Cross-LLM validation, dispute tracking | **COMPLETE** (2026-03-29) |
| G | Agent Krytyk + Learning Upgrade | Knowledge quality gate, bulletin, auditor, expert bridge | **COMPLETE** (2026-04-01) |
| H | V3 Orchestrator | UnifiedLauncher, Task Pipeline, ProductShell (15 modulow) | **COMPLETE** (2026-04-05) |
| I | Vision + Operator UX | Kamera, LLaVA, reminders, user profile, grounded chat | **COMPLETE** (2026-04-10) |
| J | API Brain Test | glm-5.1 multi-day validation (werdykt MIXED) | **COMPLETE** (2026-05-16) |
| K | Statek Teseusza | Plank-by-plank evolution (IntentRouter, Planner v2, World Model symbolic) | **IN PROGRESS** (re-target) |
| M | Procedural Memory | Skills as artifact (Hermes-inspired), lifecycle DRAFT→SANDBOX→PRODUCTION | **IN PROGRESS** (Phase 1+2a done 2026-05-15) |
| D | Vision Phase 2+ | IP camera RTSP, face recognition, OCR | DEFERRED (czeka na sprzet) |
| E | Smart Home | Integracja IoT, mobilne cialo | DEFERRED (czeka na sprzet) |
| L | AGI Direction | Symbolic world model, meta-learning, self-modification, embodiment | **LONG-HORIZON** (local-only) |

---

## Faza A: STABILIZACJA

### Cel
Naprawic wszystkie bledy krytyczne i uzyskac system ktory:
- Uruchamia sie bez bledow
- Dziala stabilnie przez podstawowa sesje uczenia
- Ma spojne sciezki plikow
- Poprawnie obsluguje polskie znaki

**STATUS: COMPLETE** (2026-01-27)

---

## Faza B: FULL HOMEOSTASIS

### Cel
System dziala autonomicznie przez dlugie okresy (8h+) z automatyczna regulacja.

**STATUS: COMPLETE** (2026-01-28)

---

## Faza C: CONSCIOUSNESS / OPTYMALIZACJA

### Cel
Rozszerzenie o swiadomosc, osobowosc, percepcje czasu, autonomiczna nauke.

- [x] Introspection module (samowiedza kodu, READ-ONLY AST)
- [x] TimeAwareness (percepcja czasu - dzien, godzina, pora)
- [x] Self-model w semantic_graph (osobowosc) - TraitEvolver + SelfModelBuilder
- [x] Pamiec rozmow z kondensacja - ConversationMemory
- [x] Ciaglosc tozsamosci (birth date, uptime) - IdentityStore
- [x] SLEEP z "snami" - SleepProcessor + DreamGenerator
- [x] Agent Nauczyciel z autonomicznym triggerem w homeostasis
- [x] NIM API + Token Budget + LLM Router (ADR-008)

**STATUS: COMPLETE** (2026-02-27, 668 tests)

---

## Faza C.5: KONTRAKTY K1-K4 (Warstwa 1)

- [x] **K1 Unified Perception** - PerceptionEvent, Buffer, 6 adapterow, Tick Aggregator (ADR-009)
- [x] **K2 Sandbox/Production** - SandboxManager, transaction log, startup recovery (ADR-010)
- [x] **K3 Goal System** - 4 typy celow, 6 statusow, PROPOSED flow, audit trail (ADR-011)
- [x] **K4 Evaluation** - READ-ONLY observer, 5 metryk, threshold recommendations (ADR-012)

**STATUS: COMPLETE** (2026-03-01, 941 tests)

---

## Faza C.6: COGNITIVE CORE K5-K13 (Warstwa 2-3)

### Warstwa 2: Petla sterowania (K5-K10, 2026-03-01 - 2026-03-20)
- [x] **K5 Planner** - ReAct loop, PlannerGuard, GoalSelector, ActionExecutor (ADR-013)
- [x] **K5.1 Topic-Aware Learning** - KnowledgeAnalyzer topic map, auto-goal creation
- [x] **K6 World Model** - Belief system, BeliefStore (JSONL, cap 2000), BeliefBuilder
- [x] **K7 Autonomy Policy** - FREE/GUARDED/RESTRICTED/FORBIDDEN, rate limiter, PolicyEngine
- [x] **K8 Deliberation** - Multi-step strategies, 3 templates, IntentTracker
- [x] **K9 Meta-Cognition** - ReflectionStore, ConfidenceTracker, pattern detection, needs_human()
- [x] **K10 Action Safety** - SafetyMode(3), AuditLog, EffectValidator, safe-by-default

### Warstwa 3: Rozszerzenia (K11-K13, 2026-03-21 - 2026-03-25)
- [x] **K11 Experiment System** - ProposalEngine, ParameterRegistry, runner, ADOPT/REJECT
- [x] **K12 Self-Analysis Phase 2** - StateCollector, ExternalAnalyzer (NIM cascade), Web UI /analysis
- [x] **K13 Creative Module Phase 2** - TensionDetector, MetaGoalEngine, ReframeEngine (NIM), TokenBudget RPM

**STATUS: COMPLETE** (2026-03-25, 1876 tests - cognitive core)

---

## Faza C.7: INFRASTRUKTURA

- [x] **Model Registry v2** - 7 modeli, heavy mutex, rule-based triage (ADR-015)
- [x] **ModelScheduler** - load/unload via Ollama, RAM guard, idle timeout
- [x] **OpenClaw Effector** - subprocess client, gateway+node, qwen2.5:3b (ADR-016)
- [x] **Web UI v2** - Metaoperator Panel, 8 paneli, design system (ADR-017)
- [x] **Web Content Fetcher** - Wikipedia PL + RSS, TopicSuggester, FetchRegistry
- [x] **Telegram Bridge (ClawBot)** - 20+ komend, 7 typow alertow, poll co 30s
- [x] **Semantic Memory** - nomic-embed-text (768-dim), VectorStore, auto-indexer (ADR-021)
- [x] **Meta-goal Priority Escalation** - tension streaks, PROPOSED displacement
- [x] **Architecture Map** - force-directed graph, pipeline view, data flow (Web UI)
- [x] **Storage Manager** - LogArchiver, DailySummary, 6TB disk

**STATUS: COMPLETE** (2026-03-27, 2081 tests)

---

## Faza C.8: STABILIZATION ROADMAP (6 faz)

Zrodlo: `docs/plans/MARIA_full_scale_stabilization_roadmap.pdf`

- [x] **Phase 1: Decision Traceability** - episode_id, DecisionTrace, TraceStore, /trace (ADR-022)
- [x] **Phase 2: Memory Consistency** - MemoryQuery API, staleness fixes, grounding (ADR-023)
- [x] **Phase 3: Scheduler Hardening** - call_with_timeout(), EpisodeBudget, degradation routing (ADR-024)
- [x] **Phase 4: Autonomy Governance** - cross-metric validation, guard metrics, promotion audit (ADR-025)
- [x] **Phase 5: Effector Safety Envelope** - 5-level authority, ApprovalQueue, ToolBudgetManager (ADR-026)
- [x] **Phase 6: Readiness Review** - 100-cycle marathon, authority drills, 15-point checklist

All gates passed: Gate A (tracing), Gate B (memory), Gate C (budgets), Gate D (governance), Gate E (readiness).

**STATUS: COMPLETE** (2026-03-29, 2392 tests)

---

## Faza F: MULTI-SOURCE LEARNING

Maria uczy sie z wielu zrodel i porownuje odpowiedzi roznych LLM.

- [x] **CrossValidator** - porownanie odpowiedzi Ollama/NIM
- [x] **ConfidenceScorer** - rule-based ocena pewnosci (Jaccard, 3 wymiary)
- [x] **DisputeLog** - JSONL log rozbieznosci (bounded 200)
- [x] **Planner trigger** - _maybe_validate() co 6h
- [x] **K7 GUARDED + K10** - rate 5/h, SafetyProfile
- [x] **Belief confidence update** - po walidacji OBSERVATION → FACT / HYPOTHESIS
- [x] **Web UI /validation + Telegram /validate**
- [x] **Belief Store v2** - evidence tracking, compaction, smart pruning, confidence decay, dedup

**STATUS: COMPLETE** (2026-03-29, 2491 tests)

---

## Faza G: AGENT KRYTYK + LEARNING UPGRADE

Knowledge quality gate + bulletin board + auditor + expert bridge.

### Agent Krytyk (ADR-028)
- [x] **7 wymiarow analizy** - contradiction, overconfident, underconfident, shallow, disputes, coverage, stale
- [x] **READ-ONLY critic** - zero LLM, zero side effects
- [x] **CritiqueApplier** - PROPOSED goals, nie automatyczna naprawa
- [x] **Planner trigger** - 8h/post_validate/post_maintenance
- [x] **REPL /critique + Web UI /critique** - 3 taby, 4 API endpoints
- [x] **Auto-confirm** - low risk goals z creative/critic/self_analysis skip /approve

### Learning Upgrade (Phase 1-5)
Plan ChatGPT: `docs/plans/plan_upgrade_nauki_maria.pdf`
- [x] **Phase 1: BulletinStore** - tablica ogloszen, 5 EntryTypes, dedup, /board
- [x] **Phase 2: KnowledgeAuditor** - checks MemoryQuery, beliefs, critic, exams → AuditReport (7 gap types)
- [x] **Phase 3: GapPlanner** - decyzje: ASK_EXPERT (z context_prompt), REVIEW, RUN_EXAM, DECOMPOSE, WAIT_HUMAN
- [x] **Phase 4: ExpertBridge** - audit-aware queries, targeted prompts, cascade LLM
- [x] **Phase 5: Full wiring** - planner, CapabilityRouter, NEED_MATERIAL → resolved

### Capability/Task Router (ADR-027)
- [x] **CapabilityRouter** - registry-based dispatch replacing 13-way if/elif
- [x] **14 capabilities** z CapabilitySpec (frozen dataclass)
- [x] **Dual-path** - router dispatch gdy dostepny, legacy fallback

**STATUS: COMPLETE** (2026-04-01, 2730 tests)

---

## Faza H: V3 ORCHESTRATOR

Unified product layer - single entry point, onboarding, task pipeline, capability discovery.

Plan: `docs/plans/V3_TECHNICAL_ROADMAP.md`

### 5 Phase Build
- [x] **Phase A (Foundation)** - Module 1-3: UnifiedLauncher (maria.py), OnboardingFlow, UserFacingSelfModel
- [x] **Phase B (Task Pipeline)** - Module 4-6: TaskOrchestrator, TaskDecomposer, ExecutionPlanBuilder
- [x] **Phase C (Practical Intelligence)** - Module 7-9: CostEstimator, TimeEstimator, FreeVsPaidPlanner
- [x] **Phase D (Execution Bridge)** - Module 10-13: ExecutionRouter, ToolRegistry, ProgressTracker, LimitationReporter
- [x] **Phase E (Product Hardening)** - Module 14-15: ProductShell + V3Module REPL /v3

### Deployment
- [x] **maria.py full mode** - daemon + Web UI w jednym procesie pod systemd
- [x] **maria-ui.service disabled** - jedna droga startu

**STATUS: COMPLETE** (2026-04-05, 3317 tests, 15 modulow)

---

## Faza I: OPERATOR UX + VISION WIRING

### Vision
- [x] **Vision Phase 1-4** - sensor (Innomaker U20CAM), preprocessing, motion+scene, cortex (297 testow)
- [x] **Homeostasis tick Phase 8.5** - vision tick, REPL /vision, Web UI /api/vision/*
- [x] **LLaVA on-demand** - describe_scene_llava (30s timeout)
- [x] **Grounded chat** - "co widzisz?" → Ollama + EvidenceCollector + LLaVA

### Operator UX
- [x] **Master Prompt** - single source for all LLM paths (`agent_core/llm/master_prompt.py`)
- [x] **Reminders & Todos** - time-triggered notifications, PL+EN time parser, tick loop Phase 12
- [x] **UserProfile** - auto-learn from chat + ConversationMemory, Telegram /profile, Web UI /api/user/profile
- [x] **Task Pipeline Web UI** - /tasks page: submit, list, detail, PDF download
- [x] **PDF Auto-Export** - każdy wynik Claude/Codex wysyłany jako PDF (fpdf2 + DejaVu, polskie znaki)
- [x] **Telegram file upload** - docs/incoming/ + caption jako komenda
- [x] **External LLM** - Claude Code CLI (3/h, 15/day), Codex CLI (10/h)

**STATUS: COMPLETE** (2026-04-10, ~4200 tests)

---

## Faza J: API BRAIN TEST (COMPLETE)

Walidacja hipotezy: czy architektura Marii skaluje się do mocniejszego silnika?

### Werdykt: MIXED

Szczegółowy werdykt z metrykami: **[`docs/plans/FAZA_J_WERDYKT_2026-05-16.md`](plans/FAZA_J_WERDYKT_2026-05-16.md)**.

Skrót:
- **Silnik pomaga w wymiernych obszarach** — latency -36% (nemotron-49b vs glm-5.1), glm-5.1 stability 0% errors w 2222 calls, K13 quality (subiektywnie wyższa)
- **Silnik nie eliminuje strukturalnych luk** — exam parser bug (100% FAIL), konfabulacja w chat path (3 generacje), planner stuck-loops, asymetria user↔maria goal creation, NIM latency 50-90s (3× wolniej niż Ollama lokalnie)
- **Architektura nie pęka pod silnikiem** — model swap był pierwszoplanową operacją (glm-5.1 → nemotron-49b 2026-05-10 po server outage), routing przez `master_prompt.py` + `LLMManager` zniwelował różnice → **walidacja designu Marii**

### Wnioski dla strategii LLM
- **Nemotron-49b primary** w `NIM_PRIMARY_ROLES`. Daily budget 750k / monthly 15M
- **Ollama llama3.1:8b** zostaje jako lokalny executor + fallback (mass operations korzystają z lokalnej szybkości)
- **Hybrid LLM strategy** potwierdzona — local primary, NIM jako mentor/auditor dla complex reasoning
- **Anti-goal trzyma:** brak crutch na paid models. NIM outage 2026-05-10 pokazał ryzyko

### Implikacje dla Fazy K
- Wszystkie 4 deski Fazy K **trzymają zasadność** (strukturalne luki niezależne od silnika)
- M15 Deska #3: **Symboliczny World Model** (decyzja werdyktu — silnik nie redukuje LLM dependency, World Model symbolic to konieczność)
- M13/M14 re-targety w PROGRESS_LOG.md

**STATUS: COMPLETE** (deploy 2026-04-18, werdykt 2026-05-16)

---

## Faza K: STATEK TESEUSZA (PLANK EVOLUTION)

Stopniowa wymiana wnętrza przy żyjącym silniku — jak zmiany w Linux kernelu. Każdy redesign to osobna **deska**. Jedna deska na raz.

> **Reality check 2026-05-16:** Faza K poszła **w równoległych torach zamiast sekwencji**. Most #1 (BulletinEscalator), Most #2 (H1+H2), B0 (5/5 surprise modules + NIM switch), 24h autonomy test, 5 architectural bugs postmortem, Skills Phase 1+2a — wszystko żyje, nic z M13/M14/M15 sekwencji nie zaczęte. Pełna prawda desk: `docs/PROGRESS_LOG.md`.

### Zasada kardynalna
**Duszy Marii nigdy nie przerywamy.** `beliefs.jsonl`, `identity.json`, `decision_traces.jsonl`, `conversation_memory.jsonl`, `knowledge_index.jsonl`, `semantic_vectors.jsonl` — te pliki są święte. Każda zmiana architektury musi czytać i pisać do tych samych źródeł, nawet jeśli wewnętrznie je transformuje.

### Zasady dla każdej deski
1. **Design doc** (1-2 dni) — `docs/plans/DESIGN_<name>.md` z tradeoffs
2. **Branch + build obok** (3-5 dni) — feature flag, nowy moduł NIE zastępuje starego
3. **Tests** (równolegle) — nowe testy, stare muszą nadal przechodzić
4. **Parallel run** (3-7 dni) — flag off = stare, flag on = nowe
5. **Cutover** (1 dzień) — flag default on, obserwacja 24h
6. **Legacy removal** (1-2 dni) — dopiero gdy cutover stabilny

### Deski sekwencyjne (re-target)

#### Deska #1: IntentRouter
- **Problem:** `/do pogoda w Berlinie` → OpenClaw qwen2.5:3b → 10min timeout. Powinno być WeatherSensor → 1s.
- **Design:** `docs/plans/DESIGN_INTENT_ROUTER.md`
- **Feature flag:** `INTENT_ROUTER_ENABLED`
- **Re-target:** M13 ~2026-05-29

#### Deska #2: Planner v2 — szkielet
- **Problem:** Rule-based, stuck-in-evaluate-loop (mg-a0128 628× evaluate na 14h), brak LLM guidance dla nowych sytuacji
- **Design:** `docs/plans/DESIGN_PLANNER_V2.md`
- **Feature flag:** `PLANNER_V2_ENABLED`
- **Re-target:** M14 ~2026-06-12

#### Deska #3: Symboliczny World Model (decyzja werdyktu J)
- **Decyzja:** werdykt J MIXED → potrzebujemy reasoning bez LLM w pętli dla rutyny. K6 JSONL → structured knowledge graph + JSONL archive.
- **Re-target:** M15 ~2026-06-26

#### Deska #4: Planner v2 cutover (full)
- Po szkielecie z #2 + obserwacji parallel run, przepinamy ruch.

### Deski zrealizowane spoza sekwencji (Faza K reality)

Te deski są DONE i żyją w runtime — szczegóły w `docs/PROGRESS_LOG.md`:

- **Most #1 BulletinEscalator** (LIVE 2026-05-06) — bulletin alerts → goal escalation
- **Most #2 H1+H2** (2026-05-09) — h1 dead-code revival + h2 stale_goals_aging
- **B0 closure** (2026-05-10) — 5/5 surprise modules (ActionBaseline + SurpriseScorer + EntryType.SURPRISE)
- **NIM switch** glm-5.1 → nemotron-49b (2026-05-10) — server outage response
- **24h autonomy test** (2026-05-13/14) — verdict 4/5, plank-by-plank revert, 0 effector calls
- **5 architectural bugs postmortem** (2026-05-14/15) — 4/5 closed: exam parser, work_context, NLU+konfabulacja, conversation_context wired (verify pending), chat persistence

### Kandydaci do dalszych desek

1. K12 Self-modification (read → write z K10 gate, rewrite ADR-006)
2. Learning pipeline — strukturyzowana ingestia
3. Model routing — dynamic based on task complexity
4. Konfabulacja Layer 1 strong-form prompt patch
5. Planner stuck-loop escape condition (quick fix przed Deska #2 cutover)

**STATUS: IN PROGRESS** (re-target sekwencji + równoległe deski reality)

---

## Faza M: PROCEDURAL MEMORY (Skills as artifact)

Nowa warstwa cognitive: procedural memory wypełniająca lukę między goals (cel) i traces (jak było). Wcześniej Maria akumulowała wiedzę (semantic) i traces (epizody), ale nie umiała **abstrahować umiejętności** z powtarzalnych workflowów. Phase 1+2a zaimplementowane 2026-05-15 (Hermes-inspired, Nous Research MIT Feb 2026).

### Filozofia portu z Hermes Agent
- **BIERZEMY:** format SKILL.md (YAML+sections), L0/L1/L2 progressive disclosure, lifecycle stages, agentskills.io compat
- **ODRZUCAMY:** autonomous skill_manage create (koliduje z ADR-010/011), cloud-first model routing (koliduje z ADR-008), GEPA cloud-heavy optimization
- **ZACHOWUJEMY:** Maria sandbox-first promote() z human gate na każdej status transition (DRAFT → SANDBOX → PRODUCTION → ARCHIVED, every step requires explicit `approved_by=` parameter)

### Spina się z Fazą L punkt 3
Faza L wskazuje 5 luk AGI (NIE UMIE). Punkt 3: "brak tworzenia umiejętności". Faza M jest pierwszą próbą zamknięcia tej luki — strukturalna ekstrakcja umiejętności z decision traces, sandbox testing, promote do production z human gate.

### Fazy

#### Phase 1: Core data plane (DONE 2026-05-15)
- `agent_core/skills/` — skill_model, schema, store, manager
- SKILL.md format z L0/L1/L2 split
- Lifecycle gates: create_draft / patch / promote / demote / archive
- Persistence: `meta_data/skills/<id>/SKILL.md` (ADR-001 single source of truth)
- 61 unit tests PASS

#### Phase 2a: Extractor template-based (DONE 2026-05-15)
- `agent_core/teacher/trace_analyzer.py` — TraceRecord projection, GoalPattern + ActionPattern
- `agent_core/teacher/skill_extractor.py` — SkillCandidate, template builders, dedup
- Real data smoke: **24 DRAFT skills wygenerowanych** z 2940 Maria decision_traces
- Wszystkie DRAFTs czekają na Eryka review — Maria sandbox-first governance trzyma
- 33 unit tests PASS

#### Phase 2b: NIM body enrichment (PLANNED)
- Nemotron-49b prompt dla rich SKILL.md body generation
- Templates jako fallback
- Semantic dedup (klastrować "Przerwij stagnacje" warianty)

#### Phase 2c: Tick wiring (PLANNED)
- SkillExtractor w homeostasis tick (background scan co X godzin)
- Telegram notify: nowy DRAFT skill ready for review
- Audit callback → bulletin entry

#### Phase 3: Planner integration (PLANNED)
- Planner reads L0 catalog na tick (compact)
- L1 on-demand kiedy planner decyduje użyć skill
- Sandbox K2 integration (execute SANDBOX skills w sandbox session)
- ADR-030 entry formal w ARCHITECTURE.md

### Resolved decisions (Eryk gate 2026-05-15, applied commit `3544780`)

5 design questions zamknięte:

1. **N threshold dla DRAFT extraction:** 5 successful w 30d (default trzymamy).
2. **Sandbox success rate dla promote:** 5/7 zero critical failures + explicit Eryk approval. Skills krytyczne/safety-affecting: 3/3 zero failures + manual log review.
3. **Stale archive threshold:** 90d dla PRODUCTION; 30d dla SANDBOX/DRAFT które nigdy nie zostały użyte.
4. **DRAFT creator:** teacher + manual teraz. K12 może proponować później — przez tę samą DRAFT gate.
5. **Język SKILL.md:** EN dla frontmatter/name/tags (interop z agentskills.io); body bilingual dozwolony; `description` musi być EN ≤140 znaków.

**Per-batch 24 DRAFTów review zaaplikowany commitem `3544780`:** 1 canonical (`meta-goal-creative-stagnation-breaker` MERGE z 17 wariantów stagnation/reactivation) + 7 promoted DRAFT→SANDBOX (5 action patterns + 2 goal patterns) + 17 archived (duplikaty + 1 noisy NOOP-optimization). **Żaden skill NIE production** — DRAFT→SANDBOX→PRODUCTION wymaga separate Eryk gate after sandbox evidence (5/7 lub 3/3 success criteria zdefiniowane wyżej). Audit trail: `docs/incoming/ERYK_SKILLS_GATE_REVIEW_2026-05-15.md`.

### Design doc
`docs/SKILLS_DESIGN.md` — architektura, schema, integration plan, ADR-030 proposal (linie 204-210: resolved questions).

**STATUS: IN PROGRESS** (Phase 1+2a done 2026-05-15; Phase 2b/2c/3 sequential)

---

## Faza L: AGI DIRECTION (LONG-HORIZON, LOCAL-ONLY)

Architektura Generalnej Inteligencji (nie Artificial) - nie jeden superumysl, tylko zespol specjalistow pod madrym szefem z ciaglosia narracji. Te pozycje sa rozwijane **lokalnie na mini PC**, **NIE pushowane do GitHuba** dopoki nie przejdza realnych testow.

### 5 luk do zamkniecia (NIE UMIE)
1. **LLM-dependent reasoning** - bez Ollama/NIM Maria to martwy demon. Rozum wypozyczony.
2. **Brak transferu** - uczy sie logiki formalnej, nie zastosuje tego do kodu. Kazda domena oddzielnie.
3. **Brak tworzenia umiejetnosci** - akumuluje wiedze tak, wymysli nowe dzialanie nie.
4. **K6 READ-ONLY** (ADR-006) - bezpieczne ale ograniczajace.
5. **Brak ucielesnienia** - OpenClaw to namiastka, nie cialo.

### 4 dodatki (PUSHERS)
1. **Symboliczny world model** - reasoning bez LLM w petli (deska #3 kandydat)
2. **Meta-learning** - uczy sie jak sie uczyc, nie tylko co
3. **Self-modyfikacja kodu** - K6 read → write z audit + rollback, K10 jako twardy gate (rewrite ADR-006)
4. **Prawdziwy efektor fizyczny** - kamera + konczyna, nie tylko /dev/video0

### Dyscyplina
- Local-only na mini PC dopoki nie zweryfikowane w produkcji
- GitHub = publiczna wizytowka (ADR-029), nie live mirror ryzykownego researchu
- Self-modification bierzemy **ostatnie** (najniebezpieczniejsze)

**STATUS: LONG-HORIZON** (pozycje wchodza do Fazy K w miare dojrzewania)

---

## Faza D: VISION PHASE 2+ (DEFERRED)

Phase 1-4 (sensor, preprocessing, modules, cortex) - DONE w Fazie I.

### Phase 2+ (czeka na sprzet)
Szczegoly: `docs/VISION_SPEC.md`

- [ ] IP camera RTSP (Tapo C200) - zakup zamkniety przez WiFi-only cameras
- [ ] OCR module
- [ ] Face recognition
- [ ] VisionModeManager attention control

### Hardware
- [ ] Kamera Tapo C200 z RTSP

---

## Faza E: SMART HOME (DEFERRED)

Czeka na sprzet IoT (Shelly/Tasmota). Szczegoly: `docs/SMART_HOME_SPEC.md`

- [ ] E1: Device Layer (SmartDevice interface, ShellyDevice, TasmotaDevice)
- [ ] E2: Automation (AutomationEngine, rules, Vision integration)
- [ ] E3: Mobile Body (IP Webcam, Termux, TTS, GPS)
- [ ] E4: Security (VLAN/Guest, audit log, potwierdzenia)

### Hardware
- [ ] Shelly Plug S x3 (~200zl)
- [ ] Android uzywany (~200zl)

---

## Agenci wyspecjalizowani

### Zrealizowane
| Agent | Rola | Model | Status |
|-------|------|-------|--------|
| **Nauczyciel** | Planuje nauke, priorytety P1-P6, spaced repetition | NIM / Ollama | **DONE** |
| **Egzaminator** | Tworzy pytania, ocenia odpowiedzi | Ollama / NIM | **DONE** |
| **Creative** | Wykrywanie napiec, meta-cele, reframe | NIM + rule-based | **DONE** (K13) |
| **Self-Analyst** | Analiza logow, rekomendacje | NIM cascade | **DONE** (K12) |
| **Krytyk** | 7 wymiarow analizy jakosci wiedzy | Rule-based (zero LLM) | **DONE** (Faza G) |
| **ExpertBridge** | Audit-aware expert queries, cascade LLM | Ollama/NIM | **DONE** (Faza G) |

### Planowane
| Agent | Rola | Model | Status |
|-------|------|-------|--------|
| **Code Agent** | Pisze/modyfikuje kod w sandboxie | qwen2.5-coder:7b | PLANNED (Faza L, deska #3 kandydat) |

---

## Milestones

| Milestone | Opis | Status |
|-----------|------|--------|
| M1 | Faza A - stabilny runtime | **DONE** (2026-01-27) |
| M2 | Faza B - full homeostasis | **DONE** (2026-01-28) |
| M3 | Faza C - consciousness + teacher | **DONE** (2026-02-27) |
| M3.5 | Linux migration + deploy na Mini PC | **DONE** (2026-02-22) |
| M3.6 | NIM API + Token Budget + LLM Router | **DONE** (2026-02-23) |
| M4 | Kontrakty K1-K4 | **DONE** (2026-03-01) |
| M5 | Cognitive Core K5-K13 complete | **DONE** (2026-03-25) |
| M6 | Infrastructure (Telegram, Semantic Memory, OpenClaw) | **DONE** (2026-03-27) |
| M7 | Stabilization Roadmap (6 faz, 5 gates) | **DONE** (2026-03-29) |
| M8 | Faza F - multi-source learning | **DONE** (2026-03-29) |
| M9 | Faza G - Krytyk + Learning Upgrade | **DONE** (2026-04-01) |
| M10 | Faza H - V3 Orchestrator (15 modulow) | **DONE** (2026-04-05) |
| M11 | Faza I - Vision + Operator UX | **DONE** (2026-04-10) |
| M12 | Faza J werdykt - API brain validation | **DONE** (2026-05-16, werdykt MIXED) |
| M13 | Faza K - IntentRouter cutover (deska #1) | RE-TARGET (~2026-05-29) |
| M14 | Faza K - Planner v2 cutover (deska #2) | RE-TARGET (~2026-06-12) |
| M15 | Faza K - deska #3 (Symboliczny World Model — decyzja werdyktu J) | RE-TARGET (~2026-06-26) |
| M16 | Faza M - Skills Phase 2b (NIM body enrichment) | PLANNED |
| M17 | Faza M - Skills Phase 3 (planner integration) | PLANNED |
| M18 | Faza D - vision Phase 2+ | DEFERRED (czeka na sprzet) |
| M19 | Faza E - smart home | DEFERRED (czeka na sprzet) |

**Reality milestones spoza pierwotnej sekwencji** (równoległe tory) — szczegóły `docs/PROGRESS_LOG.md`:

| Reality Milestone | Opis | Data |
|-------------------|------|------|
| Most #1 BulletinEscalator LIVE | Bulletin alerts → goal escalation | **DONE** (2026-05-06) |
| Most #2 H1+H2 | Dead-code fix + stale_goals_aging | **DONE** (2026-05-09) |
| B0 closure 5/5 | Surprise modules + NIM switch glm-5.1→nemotron-49b | **DONE** (2026-05-10) |
| 24h autonomy test | First real-world maturity check (verdict 4/5) | **DONE** (2026-05-13/14) |
| Postmortem 4/5 bugs closed | exam parser + work_context + NLU/konfabulacja + chat persistence | **DONE** (2026-05-15) |
| Faza M Phase 1+2a (Skills) | Procedural memory core + extractor (24 DRAFTs) | **DONE** (2026-05-15) |

---

## Ryzyka i zaleznosci

| Ryzyko | Prawdopodobienstwo | Wplyw | Mitygacja |
|--------|-------------------|-------|-----------|
| OOM crash (infinite loop) | Niskie | Wysoki | intelligent_chunk_text fix (2026-03-18), execution budgets (Phase 3) |
| Ollama timeout | Niskie | Sredni | call_with_timeout (120-180s), degradation routing |
| NIM API expiry (Aug 2026) | Srednie | Sredni | Auto-fallback na Ollama, monitoring budzetu |
| glm-5.1 timeout (thinking model) | Srednie | Sredni | NIM_TIMEOUT=120, fallback na Ollama |
| **BeliefStore leak (1.1GB tombstones, 9h freeze)** | Niskie (fixed) | Wysoki | **Startup compaction + systemd MemoryMax=20G, audit cron 4d** |
| **Confidence feedback loop (floor at 0.01)** | Niskie (fixed) | Sredni | **Signal separation (commit e1f753d)** |
| Brak sprzetu IoT/kamera | Pewne | Niski | D/E odroczone (ADR-014), mozg gotowy |
| Guard metric degradation | Niskie | Sredni | Cross-metric validation (Phase 4, ADR-025) |
| Effector cascade failure | Niskie | Wysoki | Anti-cascade breaker, approval queue (Phase 5, ADR-026) |
| **Claude CLI subscription ban** | Niskie (fixed) | Wysoki | **CLAUDE_CLI_AUTONOMOUS=false default, operator-triggered only (d8bbf30)** |
| Second-system syndrome (rewrite) | Niskie (unikniete) | Wysoki | **Statek Teseusza zamiast rewrite - Faza K** |

---

## Decyzje architektoniczne (ADR)

| ADR | Tytul | Faza |
|-----|-------|------|
| ADR-001 | JSONL jako source of truth | A |
| ADR-005 | Brak emoji w kodzie | A |
| ADR-006 | Introspection READ-ONLY | C |
| ADR-008 | NIM do nauki, Ollama do chatu | C |
| ADR-009 | Tick Aggregator zamiast Event Bus | C.5 |
| ADR-010 | Sandbox-first learning | C.5 |
| ADR-011 | Goals as data | C.5 |
| ADR-012 | Evaluation READ-ONLY | C.5 |
| ADR-013 | Planner v1 rule-based (zero LLM) | C.6 |
| ADR-014 | Najpierw mozg, potem zmysly | C.6 |
| ADR-015 | Multi-organ model stack | C.7 |
| ADR-016 | OpenClaw jako efektor | C.7 |
| ADR-017 | Web UI v2 base template | C.7 |
| ADR-018 | Markdown learning fallback | C.7 |
| ADR-019 | OpenClaw lightweight check | C.7 |
| ADR-020 | K12 Self-Analysis | C.6 |
| ADR-021 | Semantic Memory via embeddings | C.7 |
| ADR-022 | Episode-based tracing | C.8 |
| ADR-023 | Unified memory query | C.8 |
| ADR-024 | Execution budgets | C.8 |
| ADR-025 | Cross-metric validation | C.8 |
| ADR-026 | Effector safety envelope | C.8 |
| ADR-027 | Capability router (registry dispatch) | G |
| ADR-028 | Critic = coherence/calibration auditor | G |
| ADR-029 | GitHub = publiczna wizytowka, nie live mirror | - |
| ADR-030 | Skills as artifact (Hermes-inspired procedural memory, sandbox-first promote) | M |

---

*Ten dokument jest zywym dokumentem - aktualizuj go przy zmianach planow.*
