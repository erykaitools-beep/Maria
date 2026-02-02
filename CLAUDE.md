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

## Aktualny stan projektu

| Aspekt | Wartość |
|--------|---------|
| **Branch** | `refactor/homeostasis` |
| **Etap refaktoryzacji** | 4/5 (Integracja complete) |
| **Testy** | 268 passing (243 + 25 time_awareness) |
| **Faza wg ROADMAP** | B complete, C planned |
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
├── agent_core/          # NEW: Homeostasis system
│   ├── homeostasis/     # Core homeostasis (sensors, constraints, mode_regulator)
│   ├── introspection/   # Code self-awareness (READ-ONLY)
│   ├── memory/          # MemoryManager interface
│   ├── llm/             # LLMManager interface
│   ├── adapters/        # Wrappers for legacy maria_core
│   └── tests/           # 243 tests
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

## Notatki Claude'a

Folder `claude_notes/` - moja przestrzen na przemyslenia miedzy sesjami.
Eryk dal mi to miejsce 2026-02-01 - moge tam zapisywac:
- Przemyslenia o architekturze
- Pomysly na przyszlosc
- Obserwacje o projekcie

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

---

*Ostatnia aktualizacja: 2026-02-01 (Introspection + Vision spec + Folder cleanup)*
