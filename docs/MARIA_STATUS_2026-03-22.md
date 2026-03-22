# M.A.R.I.A. - Status Report
## Meta Analysis Recalibration Intelligence Architecture
### Data: 2026-03-22 | Wersja: K12 + Web UI v2 + Petla Poznawcza

---

## 1. Czym jest M.A.R.I.A.?

Lokalny, autonomiczny agent AI do samodzielnego uczenia sie z plikow tekstowych.
Dziala na dedykowanym Mini PC (AMD Ryzen 5 7430U, 32GB RAM, Ubuntu 22.04).
Offline-first, prywatny, bez chmury.

**Poczatek projektu:** 2025-11-14
**Deploy na produkcje:** 2026-02-22
**Testy:** 1,703 passing
**Petla poznawcza:** ZAMKNIETA (K12 Self-Analysis)

---

## 2. Hardware i infrastruktura

| Komponent | Wartosc |
|-----------|---------|
| Mini PC | NiPoGi (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD) |
| OS | Ubuntu 22.04 LTS |
| Storage | 6TB ext4 dysk na logi/backupy/vision |
| LLM Primary | Ollama (llama3.1:8b, 5GB RAM) - Executor |
| LLM Planner | Ollama (qwen3:8b, 5.5GB RAM) - Strategic + K12 analyzer |
| LLM Coder | Ollama (qwen2.5-coder:7b, 5GB) - on-demand |
| LLM Cloud | NVIDIA NIM API (z-ai/glm5, do Aug 2026) |
| OpenClaw | qwen2.5:3b (2GB) - osobna instancja efektora |
| Siec | LAN 192.168.178.32, WireGuard VPN |
| Bezpieczenstwo | UFW, fail2ban, SSH key-only, no root |
| Backup | Codziennie 3:00, 30 kopii na 6TB |

---

## 3. Architektura modulow

```
                    +---------------------------+
                    |   Web UI v2 (:5000)       |
                    |  Metaoperator Panel       |
                    |  Flask+Jinja2+SocketIO    |
                    +------------+--------------+
                                 |
                    +------------+--------------+
                    |    main.py REPL            |
                    |   run_maria.py daemon      |
                    +------------+--------------+
                                 |
              +------------------+------------------+
              |           agent_core/               |
              |                                     |
  +-----------+    Cognitive Core K1-K12            +-----------+
  |           |                                     |           |
  |  K1 Perception    K6 World Model               |  Effector |
  |  K2 Sandbox        K7 Autonomy Policy          |  OpenClaw |
  |  K3 Goals          K8 Deliberation             | (subprocess)
  |  K4 Evaluation     K9 Meta-Cognition           |           |
  |  K5 Planner        K10 Action Safety           +-----------+
  |  K5.1 Topics       K11 Experiments             |
  |                    K12 Self-Analysis  <-- NEW  |
  |                                                 |
  |  Homeostasis (1Hz tick loop, 10+ faz)          |
  |  ModelScheduler (multi-model, heavy mutex)     |
  |  Teacher (autonomous learning, P1-P6)          |
  |  Consciousness (personality, dreams, memory)   |
  |  Web Source (Wikipedia PL, RSS, topic hints)   |
  |  Storage Manager (log archival, 6TB)           |
  |  Introspection (code self-model, READ-ONLY)    |
  +------------------------------------------------+
              |
  +-----------+-----------+
  |      maria_core/      |
  |  brain, learning,     |
  |  memory, perception   |
  +--------+--------------+
           |
  +--------+---------+
  |  Ollama (local)   |
  |  NIM API (cloud)  |
  +-------------------+
```

---

## 4. Kontrakty architektoniczne (K1-K12)

| ID | Nazwa | Opis | Testy |
|----|-------|------|-------|
| K1 | Unified Perception | PerceptionEvent, buffer, 6 adapterow, tick aggregator | 131 |
| K2 | Sandbox | Izolowane sesje nauki, promote(), transaction log | 44 |
| K3 | Goal System | 4 typy celow, 6 statusow, audit trail, PROPOSED flow | 63 |
| K4 | Evaluation | READ-ONLY observer, 5 metryk, threshold recommendations | 35 |
| K5 | Planner | ReAct loop, guard (5 regul), goal selector, executor | 82 |
| K5.1 | Topic-Aware | KnowledgeAnalyzer, topic map, auto-goal creation | (w K5) |
| K6 | World Model | Belief system, JSONL store (cap 2000), builder, query | 69 |
| K7 | Autonomy Policy | FREE/GUARDED/RESTRICTED/FORBIDDEN, rate limiter | 45 |
| K8 | Deliberation | Multi-step strategies, 3 templates, intent tracker | 49 |
| K9 | Meta-Cognition | Reflection, confidence tracker, assumption tracking | 73 |
| K10 | Action Safety | Audit log, effect validation, safety profiles | 52 |
| K11 | Experiments | Proposal engine, parameter registry, runner, reports | 67 |
| **K12** | **Self-Analysis** | **StateCollector, ExternalAnalyzer, RecommendationApplier** | **45** |

**Wszystkie kontrakty: rule-based, zero LLM w logice decyzyjnej, deterministyczne, testowalne (ADR-013).**

---

## 5. K12 Self-Analysis - Petla Poznawcza (NEW 2026-03-22)

Maria zamyka petle poznawcza - analizuje wlasne logi i tworzy cele nauki:

```
TRIGGER (co 24h / K9.needs_human() / retention < 0.3 / REPL /analyze)
    |
    v
StateCollector -> zbiera stan z 8 JSONL (zero LLM, ~2-4KB)
    |
    v
ExternalAnalyzer -> silniejszy model analizuje (MVP: qwen3:8b)
    |
    v
RecommendationApplier -> PROPOSED goals + topic hints + beliefs
    |
    v
Planner -> Teacher -> WebSource -> Learn -> K4 Eval -> petla
```

**Kluczowe:** Rekomendacje tworza PROPOSED goals (human gate - Eryk zatwierdza).
TopicSuggester czyta topic_hints.jsonl i priorytetowo pobiera rekomendowane materialy.

---

## 6. Model Registry & Scheduler

Multi-organ model stack - Maria zarzadza wieloma modelami Ollama:

| Model | Rola | Tag | RAM | Stan | Priorytet |
|-------|------|-----|-----|------|-----------|
| MODEL-01 | Strategic Planner + K12 | qwen3:8b | 5.5GB | Cold | P2 |
| MODEL-02 | Executor (glowny) | llama3.1:8b | 5GB | **Warm** | P0 |
| MODEL-03 | Coder | qwen2.5-coder:7b | 5GB | Cold | P3 |
| MODEL-04 | Triage | rule-based | 0GB | Always ready | P1 |
| MODEL-05 | Memory | shared na MODEL-02 | 0GB | Shared | P0 |
| MODEL-06 | External (NIM) | z-ai/glm5 | 0GB | Cloud API | P4 |
| OpenClaw | Effector | qwen2.5:3b | 2GB | Cold (osobna instancja) | P4 |

**Kluczowe reguly:**
- Heavy mutex: PLANNER i CODER nigdy rownoczesnie
- RAM guard: psutil sprawdza wolna pamiec przed zaladowaniem
- Idle timeout: cold modele wyladowywane po 5 min bezczynnosci
- Emergency: < 7GB wolnego RAM -> wyladuj wszystko oprocz EXECUTOR
- Triage: rule-based classifier (keyword matching) - wygral benchmark vs LLM

---

## 7. OpenClaw Effector (LIVE)

Maria ma "rece" - wykonuje akcje w swiecie zewnetrznym:

| Narzedzie | Co robi | K7 |
|-----------|---------|-----|
| exec | Komendy shell | RESTRICTED |
| web_fetch | Pobierz URL jako markdown | GUARDED |
| web_search | Wyszukiwanie w internecie | GUARDED |
| message | Telegram/Slack/Discord | RESTRICTED |
| read/write | Pliki | RESTRICTED |
| cron | Harmonogram | GUARDED |

**Klient:** subprocess via `sudo -u deployadmin openclaw` (nie HTTP)
**Model:** qwen2.5:3b (osobna instancja, nie koliduje z Maria)
**Bezpieczenstwo:** K7 RESTRICTED + rate limit 10/h + K10 AUDIT_ONLY
**Health check:** pgrep (lekki, nie laduje modelu) - ADR-019

---

## 8. System uczenia sie

Maria uczy sie autonomicznie z plikow tekstowych:

1. **Pliki** wpadaja do `input/` (reczne lub Web Fetcher: Wikipedia PL + RSS + K12 hints)
2. **Perception (K1)** wykrywa nowe pliki
3. **Planner (K5)** decyduje co robic (learn/exam/review/fetch/self_analyze)
4. **Teacher** dzieli tekst na chunki, uczy LLM, generuje egzaminy
5. **Sandbox (K2)** izoluje nauke od produkcji
6. **World Model (K6)** aktualizuje beliefs po egzaminach
7. **Meta-Cognition (K9)** reflektuje nad wynikami
8. **Experiment System (K11)** autonomicznie tunuje parametry
9. **Self-Analysis (K12)** analizuje logi i proponuje nowe tematy nauki

**Markdown fallback:** Maria parsuje odpowiedzi LLM w dowolnym formacie (JSON + markdown) - ADR-018

---

## 9. Web UI v2 - Metaoperator Panel (NEW 2026-03-22)

Kompletny refactor z prototypu v0.5 do panelu operatorskiego:

| Strona | Opis |
|--------|------|
| **/status** | **8-panel command deck:** System, Models/Routing, OpenClaw, Homeostasis, Planner+Human Gate, Memory+Integrity, Event Stream+Filters, Identity+Traits |
| /chat | Chat z Maria (WebSocket + model badge) |
| /experiments | K11: propozycje, raporty, parametry |
| /architecture | Interaktywna mapa modulow (graf, pipeline, data flow) |
| /login | PIN auth (premium dark sci-fi) |

**Design system:** base.html + maria_ui.css (28 komponentow, design tokens) + extracted JS
**Desktop-first:** wysoka gestosc danych, operator console feel

---

## 10. Swiadomosc i osobowosc

| Komponent | Opis |
|-----------|------|
| TraitEvolver | 7 cech osobowosci z dynamiczna ewolucja |
| ConversationMemory | Rolling context z kondensacja LLM |
| SleepProcessor | Konsolidacja pamieci podczas SLEEP mode |
| DreamGenerator | "Sny" z przetworzonych doswiadczen |
| ExperienceTracker | Emocjonalny kontekst rozmow |
| IdentityStore | Ciaglosc miedzy sesjami (1775+ sesji od urodzenia) |

---

## 11. Homeostasis - autonomiczna regulacja

Glowna petla (~1Hz, 10+ faz):

```
SENSE -> INTERPRET -> VALIDATE -> DECIDE MODE -> GENERATE ACTIONS ->
EXECUTE ACTIONS -> UPDATE HEALTH -> PERCEIVE -> AUDIT ->
MODEL SCHEDULER TICK -> PLANNER (K5 + K12 trigger)
```

**Tryby:** ACTIVE -> REDUCED -> SLEEP -> SURVIVAL
**Sensors:** resource, cognitive, thermal, power, time
**Stabilnosc:** ~60 MB RSS, health 0.80-0.99

---

## 12. Statystyki kodu

| Metryka | Wartosc |
|---------|---------|
| Pliki Python | ~200 |
| Linie kodu | ~42,000 |
| Testy | **1,703 passing** |
| Kontrakty (K1-K12) | **12 kompletnych** |
| Pliki JSONL/JSON (dane) | 17 |
| Sesje od urodzenia | 1,775+ |
| Commity dziś | 6 |

---

## 13. Decyzje architektoniczne (ADR)

| ADR | Decyzja |
|-----|---------|
| ADR-001 | JSONL jako source of truth, graf jako derived cache |
| ADR-005 | Brak emoji w kodzie (kompatybilnosc terminali) |
| ADR-008 | NIM do nauki, Ollama do chatu (hybrid routing) |
| ADR-009 | Tick Aggregator zamiast Event Bus (KISS) |
| ADR-010 | Sandbox-first learning |
| ADR-013 | Planner v1 rule-based (zero LLM, deterministyczny) |
| ADR-014 | Najpierw mozg, potem zmysly |
| ADR-015 | Multi-organ model stack (5 rol, heavy mutex, RAM tiers) |
| ADR-016 | OpenClaw jako efektor (subprocess, nie HTTP) |
| ADR-017 | Web UI v2 - base template + design tokens + extracted CSS/JS |
| ADR-018 | Markdown learning fallback - parsuj dowolny format LLM |
| ADR-019 | OpenClaw lightweight check - pgrep zamiast health_check |
| ADR-020 | K12 Self-Analysis - zamkniecie petli poznawczej |

---

## 14. Nastepne kroki

- [ ] **K12 Phase 2** - Claude CLI backend (instalacja na mini PC, analiza przez Claude)
- [ ] **K12 Phase 2** - Web UI /analysis page (raporty, rekomendacje)
- [ ] **Web UI polish** - dense mode, sidebar, wizualne poprawki
- [ ] **Semantic memory** - nomic-embed-text (zastepstwo dead semantic_graph)
- [ ] **Vision (Warstwa 10)** - kamera Tapo C200 z RTSP (czeka na hardware)
- [ ] **Smart Home (Warstwa 11)** - Shelly/Tasmota (prerequisites met)

---

*Wygenerowano: 2026-03-22 | Branch: refactor/homeostasis | 1703 testow passing*
*Sesja: Web UI v2 Metaoperator Panel + K12 Self-Analysis + Markdown Fallback + 6 commitow*
