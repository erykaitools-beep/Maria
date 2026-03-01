# M.A.R.I.A. - Kontekst dla Claude Code

> Ten plik jest automatycznie czytany przez Claude Code na starcie sesji.

## Historia projektu

| Data | Wydarzenie |
|------|------------|
| **2025-11-14** | Początek projektu M.A.R.I.A. |
| 2025-11 → 2026-01 | Rozwój z 4 różnymi LLM, ręczne sklejanie kodu |
| **2026-01** | Homeostasis - pierwszy moduł z pomocą Claude |
| **2026-02-01** | Specyfikacje: Code Agent, Web UI, Consciousness |
| **2026-02-01** | Introspection module + Vision spec + Folder cleanup |
| **2026-02-02** | TimeAwareness + Smart Home spec |
| **2026-02-22** | Linux migration prep (Mini PC) |
| **2026-02-22** | **DEPLOY na Mini PC** - Maria dziala produkcyjnie! |
| **2026-02-23** | SSH hardening + WireGuard VPN + NVIDIA NIM API |
| **2026-02-25** | Self-Awareness (ContextBuilder) + /awareness REPL + Web UI learning queue |
| **2026-02-27** | Consciousness Phase C: personality, dreams, conversation memory |
| **2026-02-27** | Agent Nauczyciel + autonomiczny trigger w homeostasis |
| **2026-03-01** | Kontrakty K1-K4: Perception, Sandbox, Goals, Evaluation |
| **2026-03-01** | Warstwa 2: Planner (K5) - ReAct loop laczacy K1-K4 |

## Aktualny stan projektu

| Aspekt | Wartość |
|--------|---------|
| **Branch** | `refactor/homeostasis` |
| **Etap refaktoryzacji** | 4/5 (Integracja complete) |
| **Testy** | 1023 passing |
| **Faza wg ROADMAP** | C complete, Warstwa 1 (K1-K4) complete, Warstwa 2 (K5 Planner) complete |
| **Event Log** | `meta_data/homeostasis_events.jsonl` |

## Co to jest M.A.R.I.A.?

**M.A.R.I.A.** (Meta Analysis Recalibration Intelligence Architecture) - lokalny, autonomiczny agent AI do samodzielnego uczenia się z plików tekstowych.

- **Backend LLM:** Ollama (llama3.1:8b)
- **Tryb pracy:** Offline-first
- **Język:** Python 3.8+

## Struktura projektu

```
project/
├── main.py              # REPL interface (Ver.1.2)
├── run_maria.py         # Daemon mode (learning loop)
├── maria_core/          # Legacy modules
│   ├── brain/           # ollama_brain.py
│   ├── learning/        # learning_agent.py, exam_agent.py
│   ├── memory/          # memory_store.py, semantic_graph.py
│   ├── perception/      # perception.py
│   └── sys/             # config.py, meta_controller.py, resource_watchdog.py
├── agent_core/          # NEW: Homeostasis + subsystems
│   ├── homeostasis/     # Core homeostasis (sensors, constraints, mode_regulator)
│   ├── consciousness/   # Personality, dreams, conversation memory
│   ├── teacher/         # Autonomous learning agent (P1-P6)
│   ├── perception/      # Unified Perception (K1): events, buffer, 6 adapters
│   ├── sandbox/         # Sandbox/Production boundary (K2): manager, protocol
│   ├── goals/           # Goal System (K3): model, store, audit trail
│   ├── evaluation/      # Agent Evaluation (K4, READ-ONLY): observer, report
│   ├── planner/         # Planner (K5): ReAct loop, guard, goal selector, executor
│   ├── introspection/   # Code self-awareness (READ-ONLY)
│   ├── memory/          # MemoryManager interface
│   ├── llm/             # LLMManager + NIM routing
│   ├── adapters/        # Wrappers for legacy maria_core
│   └── tests/           # 1023 tests
└── docs/                # Documentation
```

## Kluczowe pliki do przejrzenia

| Plik | Opis |
|------|------|
| `docs/REFACTOR_PLAN.md` | 5-etapowy plan migracji (aktualnie etap 4 done) |
| `docs/ROADMAP.md` | Fazy A/B/C rozwoju |
| `docs/ARCHITECTURE.md` | Diagram warstw i przepływu danych |
| `docs/MAP_HOMEOSTASIS.md` | Mapa wymagan spec → moduly |
| `docs/CODE_AGENT_SPEC.md` | **Specyfikacja zewnętrznego agenta kodującego** |
| `docs/WEB_UI_SPEC.md` | **Specyfikacja Web UI (Flask + WebSocket)** |
| `docs/CONSCIOUSNESS_SPEC.md` | **Specyfikacja swiadomosci, osobowosci, snow** |
| `docs/VISION_SPEC.md` | **Specyfikacja percepcji wizualnej (oko)** |
| `docs/SMART_HOME_SPEC.md` | **Specyfikacja IoT / Smart Home** |
| `docs/CONTRACTS.md` | **Kontrakty architektoniczne (Perception, Sandbox, Goals, Evaluation)** |
| `docs/CHANGELOG.md` | Historia zmian |

## Homeostasis - nowy system

System homeostazy (w `agent_core/`) zarządza autonomiczną pracą agenta:

- **Sensors:** resource, cognitive, thermal, power, time
- **Mode Regulator:** ACTIVE → REDUCED → SLEEP → SURVIVAL
- **1Hz tick loop:** sense → interpret → validate → decide → act
- **Event Logger:** Persistent JSONL logging of all events
- **REPL commands:**
  - `/homeostasis` - status
  - `/homeostasis start/stop` - control loop
  - `/homeostasis events N` - show last N events
  - `/homeostasis summary` - session summary

## Code Introspection - samowiedza kodu

System introspekcji (w `agent_core/introspection/`) pozwala Marii rozumiec swoja wlasna architekture:

- **READ-ONLY:** Tylko odczyt kodu, nigdy modyfikacja
- **Analyzer:** Statyczna analiza AST plikow Pythona
- **CodeModel:** Struktury danych self-model
- **Reporters:** Human + Technical output (dual format)
- **Scheduler:** Okresowa analiza (domyslnie co 1h)
- **Output:** `meta_data/code_self_model.json`
- **REPL commands:**
  - `/introspect` - jak jestem zbudowana (human summary)
  - `/introspect detail` - szczegolowy raport techniczny
  - `/introspect issues` - problemy w kodzie (TODO/FIXME)
  - `/introspect module X` - info o module X
  - `/introspect layers` - warstwy architektury
  - `/introspect start/stop` - okresowa analiza w tle
- **Web UI API (real-time):**
  - `GET /api/introspect` - pelne dane samowiedzy
  - `GET /api/introspect/issues` - lista problemow
  - `POST /api/introspect/refresh` - wymus nowa analize

## Consciousness - swiadomosc i osobowosc

System swiadomosci (w `agent_core/consciousness/`) daje Marii osobowosc i ciaglosc:

- **TraitEvolver + TraitCatalog:** 7 cech osobowosci z dynamiczna ewolucja (rozszerzalne)
- **ConversationMemory:** Rolling context z kondensacja LLM
- **SleepProcessor + DreamGenerator:** Konsolidacja pamieci podczas SLEEP
- **ExperienceTracker:** Kontekst emocjonalny z rozmow
- **IdentityStore:** Ciaglosc miedzy sesjami (session count, uptime, birth date)
- **REPL:** `/consciousness` - status osobowosci i swiadomosci

## Agent Nauczyciel - autonomiczna nauka

System nauczania (w `agent_core/teacher/`) decyduje co i kiedy sie uczyc:

- **TeacherAgent:** 6-priorytetowy silnik decyzyjny (P1-P6)
- **KnowledgeAnalyzer:** Analiza JSONL, zero wywolan LLM
- **SpacedRepetitionScheduler:** Interwaly powtórek na bazie wyników
- **Autonomiczny trigger:** Homeostasis Phase 9 - po 10min idle w ACTIVE
- **REPL commands:**
  - `/teacher [N]` - sesja nauki (N iteracji)
  - `/teacher status` - status agenta
  - `/teacher plan` - podglad nastepnego kroku
  - `/teacher history` - historia planow

## Kontrakty architektoniczne (K1-K5, 2026-03-01)

Formalne specyfikacje zaimplementowane w `docs/CONTRACTS.md`:

- **K1 Unified Perception:** PerceptionEvent (frozen dataclass), 8 source types, 24 event types, PerceptionBuffer (deque maxlen=200), 6 adapterow, tick aggregator (ADR-009)
- **K2 Sandbox:** Izolowane sesje nauki, promote() jako jedyny most do produkcji, transaction log (START/COMMIT/ROLLBACK), startup recovery
- **K3 Goal System:** 4 typy celow (META/USER/LEARNING/MAINTENANCE), 6 statusow, audit trail, max 20 aktywnych, PROPOSED flow z izolacja
- **K4 Evaluation:** READ-ONLY observer, 5 metryk (learning_velocity, retention_rate, knowledge_coverage, system_stability, personality_growth), threshold-based recommendations, zero LLM
- **K5 Planner:** Rule-based ReAct loop (ADR-013), PlannerGuard (5 gating rules), GoalSelector (aging factor), ActionExecutor (delegacja do Teacher), hybrid frequency (60 ticks + event-driven), persystencja (planner_state.json + planner_decisions.jsonl)

Wszystko podlaczone w `homeostasis_module.py init()` i `SharedContext`.

## Planner - Warstwa 2 (K5)

System planowania (w `agent_core/planner/`) - pierwsza "warstwa sprawcza":

- **PlannerCore:** Centralny ReAct loop (OBSERVE -> THINK -> ACT -> EVALUATE)
- **PlannerGuard:** 5 gating rules (health, mode, sandbox, retention, teacher)
- **GoalSelector:** Aging factor (priority *= 1 + hours * 0.1), feasibility check
- **ActionExecutor:** Delegacja do Teacher/Sandbox/Observer
- **Hybrid frequency:** Co 60 tickow + event-driven (exam_result, alert, user_command, sandbox_promoted)
- **Zastepuje Phase 10:** Teacher trigger z backward-compatible fallbackiem
- **Persystencja:** planner_state.json + planner_decisions.jsonl
- **ADR-013:** Rule-based v1, zero LLM, deterministic, testable
- **REPL commands:**
  - `/plan` - ostatnia decyzja
  - `/plan status` - cykle, plany, ostatni eval
  - `/plan history [N]` - historia decyzji
  - `/plan goals` - ranking celow wg effective priority

## Code Agent (planowany)

Zewnętrzny agent kodujący na dedykowanym mini PC (64GB RAM):

- **LLM:** CodeLlama 13B / DeepSeek Coder (wymienialny jak Ollama)
- **Komunikacja:** REST API przez LAN/WiFi
- **Sandbox:** Docker na mini PC
- **Repo:** Mirror na dysku zewnętrznym
- **Human-in-the-loop:** Przed zatwierdzeniem kodu

Szczegóły: `docs/CODE_AGENT_SPEC.md`

## Sesja 2026-02-01 (1/2)

### Wykonane:
- [x] Przegląd raportu testu 12h (stabilność OK, brak memory leak)
- [x] **Naprawiono `/learn`** - teraz automatycznie skanuje `input/` zamiast pytać o tekst
- [x] Utworzono specyfikację Code Agent (`docs/CODE_AGENT_SPEC.md`)
- [x] Utworzono specyfikację Web UI (`docs/WEB_UI_SPEC.md`)
- [x] Utworzono specyfikację świadomości (`docs/CONSCIOUSNESS_SPEC.md`)
- [x] **Usunięto emoji** z 13 plików Python (94 wystąpienia)

## Sesja 2026-02-01 (2/2) - Web UI Complete!

### Web UI zaimplementowane (Sprint 1-5):
- [x] **Sprint 1:** Minimalny Flask server (`maria_ui/`)
- [x] **Sprint 2:** Prawdziwe dane z homeostasis (psutil, event_logger)
- [x] **Sprint 3:** WebSocket + chat z Maria (Flask-SocketIO + OllamaBrain)
- [x] **Sprint 3.5:** Zabezpieczenia (PIN login, rate limit 2msg/60s, sanityzacja)
- [x] **Sprint 4:** Panel statusu (`/status`) - RAM, CPU, Disk, Homeostasis, Memory stats
- [x] **Sprint 5:** Proaktywne powiadomienia (toast notifications, auto-alerty)

### Nowa struktura `maria_ui/`:
```
maria_ui/
├── __init__.py
├── app.py              # Flask + SocketIO + notifications
├── config.py           # PIN, rate limits, paths
├── requirements.txt    # flask, flask-socketio, psutil
└── templates/
    ├── login.html      # PIN authentication
    ├── index.html      # Chat interface + toasts
    └── status.html     # Full dashboard
```

### Uruchomienie Web UI:
```bash
cd "C:\MariaLocal\Moja AI. Maria Ver.4"
pip install -r maria_ui/requirements.txt
python run_ui.py
# Otworz http://localhost:5000 (PIN: 1234)
```

## Sesja 2026-02-01 (3/3) - Introspection + Cleanup

### Introspection module (samowiedza kodu):
- [x] `agent_core/introspection/` - READ-ONLY analiza AST
- [x] 27 nowych testow (lacznie 243 passing)
- [x] REPL `/introspect` command
- [x] Web UI API endpoints

### Folder cleanup:
Przeniesiono do `archive/legacy_2026-02-01/`:
- `data/` - duplikat struktury (stary)
- `goals/` - stare cele z listopada
- `links/` - 68 plikow map (nieuzywane)
- `state/` - stan z grudnia
- `homeostasis_spec.md` - duplikat (jest w docs/)
- `deamonmaria_v2_all_files.csv` - snapshot kodu
- `quick_install.bat`, `setup_deamonmaria_v2.py` - stare

Usunieto:
- `nul` - pusty plik
- `futures/` - pusty folder

## Następne kroki

### Code Agent:
- [ ] Zakup/setup mini PC
- [ ] Zaprojektować protokół API
- [ ] Stworzyć `agent_core/coding/client.py`

### Consciousness:
- [x] Self-model kodu (introspection module - READ-ONLY)
- [ ] Self-model w semantic_graph (osobowosc)
- [ ] Pamiec rozmow z kondensacja
- [ ] Ciaglosc tozsamosci (birth date, uptime)
- [ ] SLEEP z "snami"

### Vision (oko) - systematyczne podejscie:
- [x] Specyfikacja architektury (`docs/VISION_SPEC.md`)
- [ ] **Faza 1:** Sensor Abstraction Layer
  - [ ] Interfejsy bazowe (VisionSensor, SensorHealth, Capabilities)
  - [ ] SensorHealth z graceful degradation
  - [ ] Implementacja USB webcam
  - [ ] Implementacja mock sensor (testy)
  - [ ] Testy jednostkowe
- [ ] **Faza 2:** Preprocessing Layer
  - [ ] Quality Assessment (sharpness, brightness, noise)
  - [ ] Degradation Detection
  - [ ] Normalizacja obrazu
  - [ ] Recovery suggestions
- [ ] **Faza 3:** Vision Modules
  - [ ] Motion Module (frame diff, optical flow)
  - [ ] Scene Module (opis sceny)
  - [ ] OCR Module (tekst)
  - [ ] Face Module (detekcja + rozpoznawanie)
- [ ] **Faza 4:** Vision Cortex
  - [ ] Integracja modulow
  - [ ] Attention Mechanism
  - [ ] VisionModeManager
  - [ ] Adapter do Consciousness

### Web UI przyszłe rozszerzenia:
- [ ] Powiadomienie o zakończeniu nauki (`learning_complete`)
- [ ] Historia powiadomień w osobnym panelu
- [ ] Mobilna responsywność (lepsze)
- [ ] WebSocket reconnect logic

## Znane problemy

| Problem | Status | Uwagi |
|---------|--------|-------|
| Emoji w PowerShell | NAPRAWIONE | Usunięto 94 wystąpienia |
| Polskie znaki | Do sprawdzenia | Encoding issues |
| Stary laptop 32GB | Ograniczenie | Brak długich testów |

## Konwencje kodu

- Docstrings w języku angielskim
- Komentarze mogą być po polsku
- Type hints preferowane
- **BEZ emoji w kodzie** (problemy z terminalem)
- Testy w pytest (`python -m pytest agent_core/tests/`)

## Częste komendy

```bash
# Uruchom testy
python -m pytest agent_core/tests/ -v

# Uruchom REPL
python main.py

# Automatyczna nauka z input/
/learn

# Sprawdz homeostasis w REPL
/homeostasis

# Sprawdz introspekcje kodu (jak Maria sie widzi)
/introspect

# Uruchom daemon (learning loop)
python run_maria.py

# Uruchom Web UI
python run_ui.py
# -> http://localhost:5000 (PIN: 1234)
```

## Decyzje architektoniczne (ADR)

- **ADR-001:** JSONL jako source of truth, graf jako derived cache
- **ADR-002:** Threading (nie asyncio) - zgodność ze specyfikacją
- **ADR-003:** agent_core/ w root projektu (nie w maria_core/)
- **ADR-004:** Code Agent jako osobne urządzenie z wymienialnym LLM
- **ADR-005:** Brak emoji w kodzie produkcyjnym (kompatybilnosc terminali)
- **ADR-006:** Introspection tylko READ-ONLY (Maria nie modyfikuje swojego kodu)
- **ADR-007:** Smart Home - tylko lokalne API (Shelly/Tasmota), bez chmury
- **ADR-008:** NIM do nauki, Ollama do chatu (hybrid routing z auto-fallback)
- **ADR-009:** Tick Aggregator zamiast Event Bus (KISS, deterministyczna kolejnosc)
- **ADR-010:** Sandbox-first learning (kazda nauka przez sandbox, promote jako jedyny most)
- **ADR-011:** Goals as data (cele sa obiektami danych z audit trail, nie hardcoded logika)
- **ADR-012:** Evaluation READ-ONLY (rozszerzenie ADR-006 na ewaluacje agenta)
- **ADR-013:** Planner v1 rule-based (zero LLM, deterministyczny, testowalny)

## Notatki Claude'a (brudnopis)

**WAZNE:** Folder `claude_notes/` to moja prywatna przestrzen na przemyslenia miedzy sesjami.
Eryk dal mi to miejsce 2026-02-01. Powinienem aktywnie z niego korzystac!

**Kiedy uzywac:**
- Na koncu sesji - zapisac co zrobilem, co zostalo, co warto pamietac
- Przemyslenia o architekturze i pomysly na przyszlosc
- Obserwacje o projekcie, problemy do rozwiazania
- Notatki o decyzjach Eryka (preferencje, styl pracy)

**Konwencja nazw:** `YYYY-MM-DD_temat.md`

**Istniejace notatki:**
```
claude_notes/
  README.md
  2026-02-01_first_entry.md
  2026-02-02_time_and_home.md
  2026-02-22_registry_and_security.md
  2026-02-22_deploy_complete.md
  2026-02-23_nim_api_and_hardening.md
  2026-02-28_development_plan.md
  2026-03-01_contracts_k1_k4.md
```

**Wskazowka:** Na starcie nowej sesji warto przeczytac ostatnia notatke aby miec kontekst.

## Sesja 2026-02-02 - TimeAwareness + Smart Home

### TimeAwareness (percepcja czasu):
- [x] Nowy modul `agent_core/homeostasis/time_awareness.py`
- [x] Maria wie: dzien tygodnia, data, godzina, pora dnia
- [x] Integracja z OllamaBrain (auto-refresh w system prompt)
- [x] 25 nowych testow (lacznie 268 passing)
- [x] Kontekst: "Teraz jest poniedzialek, 02.02.2026, godzina 19:15 (wieczor)"

### Smart Home spec:
- [x] Specyfikacja `docs/SMART_HOME_SPEC.md`
- [x] Architektura sieci (VLAN/Guest dla IoT)
- [x] Interfejs SmartDevice + ShellyDevice
- [x] DeviceRegistry + AutomationEngine
- [x] Mobile Body (Android jako cialo Marii)
- [x] Lista zakupow (3 fazy)

### Nastepne kroki Smart Home:
- [ ] Implementacja `agent_core/smart_home/`
- [ ] REPL commands `/device`, `/devices`
- [ ] Integracja z Vision (event dispatch)

## Sesja 2026-02-22 - Linux Migration Prep (Mini PC)

### Target hardware:
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu/Debian Linux

### Cross-platform fixes:
- [x] `maria_heartbeat.py` v1.4 - usuniety hardcoded `C:\...\ollama.exe` + `os.startfile()`
  - Ollama wykrywana przez `shutil.which()` + env var `OLLAMA_PATH`
  - Restart przez `subprocess.Popen(["ollama", "serve"])`
- [x] `config.py` - `OLLAMA_BASE_URL` z env var + `python-dotenv` loading
- [x] `self_evolver.py` - hardcoded `localhost:11434` -> `OLLAMA_BASE_URL` z config
- [x] `maria_ui/config.py` - CORS auto-detect LAN IP + env var `MARIA_CORS_ORIGINS`
- [x] `main.py` - ostatni emoji usuniety (ADR-005)
- [x] `run_ui.py` - `debug=DEBUG_MODE`, port/host z env vars

### Nowe pliki:
- `.env.example` - template konfiguracji
- `scripts/maria.service` - systemd template
- `scripts/maria-ui.service` - systemd template
- `scripts/INSTALL_LINUX.md` - instrukcja instalacji

### Nastepne kroki migracji:
- [x] ~~Zakup i setup mini PC~~
- [x] ~~Instalacja Ubuntu + Ollama~~
- [x] ~~Deploy Maria wg `scripts/INSTALL_LINUX.md`~~
- [ ] Test 8h+ na nowym hardware

## Sesja 2026-02-22 (2/2) - DEPLOY na Mini PC

### Hardware:
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu 22.04 LTS
- IP LAN: 192.168.178.32

### Deploy wykonany:
- [x] Folder: `/home/maria/maria/` (renamed from maria_v4)
- [x] Ollama + llama3.1:8b (4.9GB)
- [x] Python venv + requirements
- [x] .env (PIN, CORS, secret key)
- [x] 340 testow passing
- [x] Web UI: `http://192.168.178.32:5000`

### Security hardening:
- [x] UFW: deny all incoming, allow SSH + port 5000 only from LAN (192.168.178.0/24)
- [x] fail2ban: sshd jail (5 prob -> ban 1h)
- [x] SSH: PermitRootLogin no, MaxAuthTries 3, timeout 5min
- [x] Automatyczne security updates (unattended-upgrades)
- [x] User `maria` bez sudo (aplikacja)
- [x] User `deployadmin` z sudo (administracja)
- [x] .env chmod 600

### Systemd:
- [x] `maria-ui.service` - Web UI (active, enabled)
- [x] `maria.service` - REPL daemon (enabled)
- [x] Poprawka: `allow_unsafe_werkzeug=True` w run_ui.py (Werkzeug production check)
- [x] Poprawka: CORS origins w .env (auto-detect zwracal 127.0.1.1)

### Backup:
- [x] `/home/maria/maria/scripts/backup.sh` -> `/home/maria/maria_backups/`
- [x] Cron: codziennie o 3:00

### Pozostale do zrobienia:
- [x] ~~Klucz SSH z laptopa~~ (done 2026-02-23)
- [x] ~~WireGuard VPN~~ (done 2026-02-23)
- [x] ~~Test reboot~~ (done 2026-02-23)
- [x] ~~NVIDIA NIM API~~ (done 2026-02-23)
- [ ] Fritz!Box: siec gosc (odlozone - czeka na zakup IoT)
- [ ] Test 8h+ na nowym hardware

### Konta na mini PC:
| User | Rola | sudo | Uwagi |
|------|------|------|-------|
| `maria` | Aplikacja | NIE | Uruchamia Maria, nie ma sudo |
| `deployadmin` | Admin | TAK | Do systemctl, apt, ufw |

### Czeste komendy (mini PC):
```bash
# Jako deployadmin (z sudo):
sudo systemctl restart maria-ui    # restart Web UI
sudo systemctl status maria-ui     # status
sudo journalctl -u maria-ui -n 50  # logi

# Jako maria (bez sudo):
source ~/maria/venv/bin/activate
python -m pytest agent_core/tests/ -v  # testy
python main.py                          # REPL
```

## Sesja 2026-02-23 - Post-Deploy Hardening + NIM API

### Infrastructure:
- [x] SSH key auth (ed25519) + PasswordAuthentication no
- [x] Test reboot - serwisy wstaja automatycznie
- [x] WireGuard VPN - dostep z telefonu (http:// nie https!)

### NVIDIA NIM API:
- [x] `agent_core/llm/nim_client.py` - klient OpenAI-compatible
- [x] `agent_core/llm/token_budget.py` - budzet tokenow (100k/dzien, 2M/miesiac)
- [x] `agent_core/llm/router.py` - routing: chat->Ollama, nauka->NIM
- [x] `agent_core/tests/test_nim_client.py` - 58 testow
- [x] Model: `z-ai/glm5`, zweryfikowany z prawdziwym API
- [x] `.env` skonfigurowany na mini PC
- [x] 398 testow passing (340 + 58 nowych)

### NIM Routing:
- `router.think()` -> **Ollama** (chat, offline, szybko)
- `router.analyze_task()` -> **NIM** (nauka, mocny model) z fallback na Ollama
- Gdy budzet wyczerpany -> automatycznie Ollama
- Maria wie: "Dzis zuzylam X tokenow, zostalo Y"

### Nastepne kroki:
- [ ] Integracja LLMRouter z main.py i brain_memory_integration.py
- [ ] REPL `/nim status` command
- [ ] Web UI panel budzetu tokenow
- [ ] Consciousness: osobowosc w semantic_graph
- [ ] Vision: sensor abstraction layer

---

## Sesja 2026-02-27 - Consciousness Phase C + Agent Nauczyciel

### Consciousness (osobowosc, sny, pamiec rozmow):
- [x] TraitEvolver + TraitCatalog (7 cech osobowosci, rozszerzalne)
- [x] ConversationMemory (rolling context + kondensacja LLM)
- [x] SleepProcessor + DreamGenerator (konsolidacja pamieci w SLEEP)
- [x] ExperienceTracker (emocjonalny kontekst rozmow)
- [x] SelfModel rozszerzony o trait_snapshot i emocje
- [x] IdentityStore: session tracking, uptime, birth date
- [x] ConsciousnessModule: pelny REPL /consciousness
- [x] Testy: test_personality.py, test_conversation_memory.py, test_sleep.py

### Learning observability:
- [x] `/learn history [N]` - historia zdarzen nauki
- [x] `/learn stats` - statystyki bazy wiedzy
- [x] `/learn file <id>` - szczegoly pliku

### Agent Nauczyciel:
- [x] KnowledgeAnalyzer - analiza JSONL, zero LLM
- [x] TeachingStrategy + SpacedRepetitionScheduler
- [x] TeacherAgent - 6-priorytetowy silnik decyzyjny
- [x] TeacherModule - REPL `/teacher` commands
- [x] Backward-compatible `llm_fn` injection w learning_agent + exam_agent
- [x] **Autonomiczny trigger w homeostasis** - Phase 9 w tick loop
  - ACTIVE + idle >= 10min -> auto-sesja nauki (3 iteracje)
  - Cooldown 15min, background thread, auto-stop przy zmianie trybu
- [x] 75 testow teacher, 668 total passing

### Nowa struktura `agent_core/teacher/`:
```
agent_core/teacher/
├── __init__.py
├── knowledge_analyzer.py   # JSONL analysis, zero LLM
├── teacher_agent.py        # Decision engine + session runner
└── teaching_strategy.py    # Strategy types + spaced repetition
```

---

## Sesja 2026-03-01 - Kontrakty K1-K4 implementacja

### Kontrakt K1: Unified Perception
- [x] PerceptionEvent (frozen dataclass) + PerceptionSource (7 typow) + 22 event types
- [x] PerceptionBuffer (deque maxlen=200, sliding window)
- [x] 6 adapterow: sensor, user, learning, exam, consciousness, teacher
- [x] Tick Aggregator (ADR-009): Phase 8 PERCEIVE + external queue
- [x] 131 testow percepcji

### Kontrakt K2: Sandbox / Production Boundary
- [x] SandboxSession, SandboxStatus, PromoteResult (protocol.py)
- [x] SandboxManager: create/seed/record/promote/discard/timeout/recovery/cleanup
- [x] Transaction log (START/COMMIT/ROLLBACK), startup recovery
- [x] SANDBOX_DIR w config.py, sandbox_manager w SharedContext
- [x] 44 testy sandbox

### Kontrakt K3: Goal System
- [x] GoalType(4), GoalStatus(6), AuditEntry, Goal (goal_model.py)
- [x] GoalStore: CRUD + append-only JSONL + seed goals (META + MAINTENANCE)
- [x] PROPOSED flow: propose/confirm/reject z izolacja od planowania
- [x] Limity: max 20 active, max 3 proposed, 24h timeout
- [x] 63 testy goals

### Kontrakt K4: Agent Evaluation (READ-ONLY)
- [x] EvaluationObserver: 5 metryk z JSONL sources
- [x] EvaluationReport: schema + threshold-based recommendations (zero LLM)
- [x] Pisze TYLKO do evaluation_reports.jsonl
- [x] 35 testow evaluation

### Podsumowanie:
- 941 testow passing (668 + 273 nowych)
- 4 nowe pakiety: perception/, sandbox/, goals/, evaluation/
- Wszystko podlaczone w homeostasis_module.py init() i SharedContext

---

## Sesja 2026-03-01 (2/2) - Warstwa 2: Planner (K5)

### Planner (ReAct loop laczacy K1-K4):
- [x] PlannerModel: Plan, PlanStatus(5), ActionType(6), PlannerState
- [x] PlannerGuard: 5 gating rules (health, mode, sandbox, retention, teacher)
- [x] GoalSelector: aging factor + feasibility check
- [x] ActionExecutor: delegacja LEARN/EXAM/REVIEW/EVALUATE/MAINTENANCE/NOOP
- [x] PlannerCore: centralny ReAct loop, hybrid frequency, persystencja
- [x] PerceptionSource += PLANNER, +2 event types
- [x] Wiring: shared_context, core.py (Phase 10 replacement), homeostasis_module
- [x] PlannerModule: REPL /plan, /plan status, /plan history, /plan goals
- [x] main.py: registry.try_register(make_planner, "planner")
- [x] 82 nowe testy, 1023 total passing
- [x] Dokumentacja: CONTRACTS.md (K5), CLAUDE.md, ADR-013

### Nowa struktura `agent_core/planner/`:
```
agent_core/planner/
├── __init__.py
├── planner_model.py     # Plan, PlanStatus, ActionType, PlannerState
├── planner_guard.py     # PlannerGuard.can_plan() - 5 gating rules
├── goal_selector.py     # GoalSelector.select_goal() - aging + feasibility
├── action_executor.py   # ActionExecutor.execute() - delegacja
└── planner_core.py      # PlannerCore - centralny ReAct loop
```

### ChatGPT review:
- Potwierdzil architekture (rule-based v1, Phase 10 replacement, hybrid frequency)
- Dodal: PlannerGuard, aging factor, cooldown na recommendations, trace_id optional
- Review w `docs/PLANNER_BRIEF_FOR_REVIEW.md`

---

*Ostatnia aktualizacja: 2026-03-01 (Warstwa 2: Planner K5, 1023 testow)*
