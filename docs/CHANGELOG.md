# M.A.R.I.A. - Changelog
> Format: [YYYY-MM-DD] Kategoria: Opis

---

## [2026-02-23] - Sesja 11: Post-Deploy Hardening + NVIDIA NIM API

### Infrastructure
- **SSH key auth:** Klucz ed25519 z laptopa, PasswordAuthentication wylaczone
- **Reboot test:** Wszystkie serwisy (ollama, maria-ui) wstaja automatycznie
- **WireGuard VPN:** Dostep do Marii z telefonu przez Fritz!Box VPN

### Added - NVIDIA NIM API (`agent_core/llm/`)
- **`nim_client.py`** - Klient NVIDIA NIM API (OpenAI-compatible)
  - Retry z exponential backoff (rate limits)
  - Token usage tracking per call
  - Health check i availability detection
- **`token_budget.py`** - Zarzadzanie budzetem tokenow
  - Limity dzienne (100k) i miesieczne (2M)
  - Persistence w `meta_data/nim_token_usage.json`
  - Status: OK / LOW / DEPLETED
  - Raport po polsku ("Dzis zuzylam X tokenow...")
- **`router.py`** - LLM Router (NIM vs Ollama)
  - `think()` -> Ollama (chat, offline, szybko)
  - `analyze_task()` -> NIM (nauka, mocny model) z fallback na Ollama
  - Automatyczne przelaczanie gdy budzet wyczerpany
- **`agent_core/tests/test_nim_client.py`** - 58 testow (mock-based)

### Changed
- **`.env.example`** - Dodano sekcje NVIDIA NIM (API key, model, limity)
- **`maria_core/sys/config.py`** - Nowe env vars NIM
- **`agent_core/llm/__init__.py`** - Eksporty NIMClient, TokenBudget, LLMRouter

### Configuration
```
NVIDIA_NIM_API_KEY=nvapi-...
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_MODEL=z-ai/glm5
NIM_DAILY_TOKEN_LIMIT=100000
NIM_MONTHLY_TOKEN_LIMIT=2000000
```

### Statistics
- **398 tests passing** (340 previous + 58 new)
- NIM API verified: model z-ai/glm5, latency ~2-5s (po cold start)
- 3 nowe pliki, 3 zmodyfikowane

---

## [2026-02-22] - Sesja 10: Linux Migration Prep (Mini PC)

### Changed
- **`maria_core/sys/config.py`** - Dodano `python-dotenv` loading + `OLLAMA_BASE_URL` z env var
- **`maria_core/sys/maria_heartbeat.py`** (v1.3 -> v1.4):
  - Usuniety hardcoded `C:\Users\eras-\...\ollama.exe`
  - `os.startfile()` (Windows-only) -> `subprocess.Popen()` (cross-platform)
  - Ollama wykrywana przez `shutil.which("ollama")` + env var `OLLAMA_PATH`
  - Health check uzywa `OLLAMA_BASE_URL` z config
- **`maria_core/sys/self_evolver.py`** - hardcoded `localhost:11434` -> `OLLAMA_BASE_URL` z config
- **`maria_ui/config.py`** - CORS auto-wykrywa LAN IP + env var `MARIA_CORS_ORIGINS`
- **`main.py`** - Ostatni emoji (linia 104) usuniety (ADR-005)
- **`run_ui.py`** - `debug=True` -> `debug=DEBUG_MODE`, port/host z env vars

### Added
- **`.env.example`** - Template konfiguracji (OLLAMA_BASE_URL, MARIA_PIN, porty)
- **`scripts/maria.service`** - Systemd template dla REPL
- **`scripts/maria-ui.service`** - Systemd template dla Web UI
- **`scripts/INSTALL_LINUX.md`** - Instrukcja instalacji na Linux
- **`python-dotenv`** w `maria_core/requirements.txt`

### Target Hardware
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu/Debian Linux

### Statistics
- **268 tests passing** (zero regresji)
- 7 plikow zmodyfikowanych, 4 nowe pliki

---

## [2026-02-01] - Sesja 6 & 7: Emoji Cleanup + Web UI Complete

### Added - Web UI (`maria_ui/`)
- **Sprint 1:** Minimalny Flask server z podstawowa struktura
- **Sprint 2:** Integracja z homeostasis (psutil, event_logger)
- **Sprint 3:** WebSocket chat z OllamaBrain
- **Sprint 3.5:** Zabezpieczenia:
  - PIN login (domyslnie: 1234)
  - Rate limiting (2 msg / 60s)
  - Input sanitization (XSS protection)
  - Session management
- **Sprint 4:** Full status dashboard (`/status`):
  - System metrics (RAM, CPU, Disk, Uptime)
  - Homeostasis (mode, health score, alerts)
  - Brain stats (model, history, API calls)
  - Memory stats (semantic graph, knowledge index)
  - Events list (last 10)
- **Sprint 5:** Proaktywne powiadomienia:
  - Toast notifications (prawy gorny rog)
  - Auto-alerty przy zmianie trybu homeostasis
  - Auto-alerty przy CRITICAL/ALERT severity
  - Powiadomienia w chacie jako system messages
  - Background monitor thread (5s interval)

### New Files
```
maria_ui/
├── __init__.py
├── app.py              # 755 lines - Flask + SocketIO + notifications
├── config.py           # Centralized configuration
├── requirements.txt    # flask, flask-socketio, psutil, simple-websocket
└── templates/
    ├── login.html      # PIN authentication page
    ├── index.html      # Chat interface v0.5
    └── status.html     # Full dashboard
run_ui.py               # Entry point for Web UI
```

### Fixed
- **Emoji cleanup:** Usunieto 94 wystapienia emoji z 13 plikow Python
  - Zamieniono na tekst ASCII: [OK], [WARN], [ERROR], [INFO], etc.
  - Naprawiono problemy z PowerShell encoding
- **Chat history persistence:** Wiadomosci nie znikaja przy nawigacji miedzy stronami

### API Endpoints
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | Yes | Chat interface |
| `/login` | GET/POST | No | PIN login |
| `/logout` | GET | No | Clear session |
| `/status` | GET | Yes | Status dashboard |
| `/api/status` | GET | Yes | Basic status JSON |
| `/api/status/full` | GET | Yes | Full metrics JSON |
| `/api/chat/history` | GET | Yes | UI chat history |
| `/api/notify/test` | POST | Yes | Send test notification |
| `/api/notify/send` | POST | Yes | Send custom notification |
| `/api/health` | GET | No | Health check |

### WebSocket Events
| Event | Direction | Description |
|-------|-----------|-------------|
| `connect` | Client->Server | Initiate connection |
| `connected` | Server->Client | Connection confirmed |
| `chat_message` | Client->Server | User sends message |
| `chat_response` | Server->Client | Maria's response |
| `chat_status` | Server->Client | Thinking indicator |
| `clear_history` | Client->Server | Clear conversation |
| `history_cleared` | Server->Client | Confirmation |
| `proactive_notification` | Server->Client | Auto-alerts |

### Configuration (`maria_ui/config.py`)
```python
UI_PIN = "1234"                    # Login PIN
RATE_LIMIT_MESSAGES = 2            # Max messages per window
RATE_LIMIT_WINDOW_SEC = 60         # Window duration
MAX_MESSAGE_LENGTH = 2000          # Max chars per message
MAX_HISTORY_MESSAGES = 20          # Brain history limit
DEBUG_MODE = False                 # Production mode
```

---

## [2026-01-31] - Sesja 5: Event Logger (Lab Reports)

### Added
- `agent_core/homeostasis/event_logger.py` - Persistent event logging system
  - Logs mode transitions with full trigger context (constraint, value, threshold)
  - Logs alerts with severity and values
  - Logs state snapshots periodically
  - Duration tracking for each mode
  - Thread-safe buffered writes to JSONL
- `/homeostasis events N` - Show last N events from log
- `/homeostasis summary` - Show session summary (uptime, mode changes, alerts)
- `agent_core/tests/test_event_logger.py` - 16 tests for event logger

### Changed
- `HomeostasisCore` now integrates with EventLogger
- `AlarmDispatcher` now logs alerts to JSONL
- Event log file: `meta_data/homeostasis_events.jsonl`

### Statistics
- **216 tests passing** (200 previous + 16 new)

### Event Log Format (Lab Report style)
```jsonl
{"ts": 1706700000, "event_type": "mode_change", "from_mode": "active", "to_mode": "reduced", "trigger": {"constraint": "ram_low", "value": 18.5, "threshold": 20}, "metrics": {...}, "duration_in_prev_mode_sec": 3600}
{"ts": 1706700060, "event_type": "alert", "severity": "WARNING", "message": "RAM below 30%", "value": 28.5, "threshold": 30}
```

---

## [2026-01-28] - Sesja 4: Etap 3 + Etap 4 Complete

### Added
- `agent_core/tests/test_integration_legacy.py` - 26 integration tests with real legacy modules
- `/homeostasis` REPL command (status/start/stop)
- Mode gating in main.py for learning cycle protection
- Version 1.2 of main.py with full homeostasis integration

### Fixed
- `ResourceWatchdogAdapter`: Fixed `ram_percent` → `memory_pressure` (ResourceMetrics property)
- Integration tests API mismatches:
  - `get_latency_ms()` → `get_last_latency_ms()`
  - `is_loaded()` → `is_minimized()`
  - `_tick()` → `_execute_tick()`
  - `_state` → `state`
  - `current_hour` → `hour_of_day`

### Integration Tests Results
| Test Class | Tests | Status |
|------------|-------|--------|
| TestMemoryStoreAdapterLegacy | 5 | PASSED |
| TestSemanticGraphAdapterLegacy | 6 | PASSED |
| TestResourceWatchdogAdapterLegacy | 3 | PASSED |
| TestBrainMemoryAdapterLegacy | 5 | PASSED |
| TestFullIntegration | 5 | PASSED |
| TestPerformance | 2 | PASSED |

### Statistics
- **200 tests passing** (174 unit + 26 integration)
- All 4 adapters verified with real legacy modules
- HomeostasisCore tick latency < 200ms

### Commits
- `3d85d04` - Etap 3: Integration tests with real legacy modules
- `4ec6e28` - Etap 4: Homeostasis integration in main.py with REPL commands

---

## [2026-01-27] - Sesja 3: Etap 1 + Etap 2 Complete

### Added
- `agent_core/` directory structure (Etap 1)
- All homeostasis modules with full implementations
- 174 unit tests covering all modules
- 4 adapters wrapping legacy maria_core modules

### Commits
- `5186afb` - Etap 1: agent_core/ skeleton structure with full implementations
- `9c24a55` - Etap 2: Create adapters wrapping legacy maria_core

---

## [2026-01-26] - Sesja 2: Mapowanie Homeostazy + Resolved Questions

### Added
- `docs/MAP_HOMEOSTASIS.md` - pelna mapa wymagan spec → moduly docelowe (~83 wymagania)
- `docs/REFACTOR_PLAN.md` - 5-etapowy plan migracji do architektury agent_core/

### Updated
- `docs/DECISIONS.md` - zaktualizowano do v0.2:
  - ADR-004 zmieniony na ACCEPTED (JSONL = source of truth)
  - Q-001 do Q-005 resolved z odpowiedziami od wlasciciela
  - Wszystkie open questions zamkniete

### Decisions Recorded
- Q-001: archive/ oznaczony jako deprecated, nie uzywany
- Q-002: main.py i run_maria.py dzialaja ALTERNATYWNIE (nie rownolegle)
- Q-003: max_iterations=0 to celowe (infinite loop), zmienic na None dla czytelnosci
- Q-004: maria_web_learning.py i maria_api_bridge.py to future features, nie implementowac teraz
- Q-005 → ADR-004: JSONL = source of truth, graf = derived cache

### Statistics from MAP_HOMEOSTASIS.md
- ~65 wymagan oznaczonych jako `missing`
- ~8 wymagan `partial`
- ~10 wymagan `adapter` (wrap existing code)
- Szacowany naklad: 10-12 sesji roboczych

---

## [2026-01-26] - Sesja 1: Inicjalizacja dokumentacji + Stabilizacja P0

### Added
- `docs/WORKFLOW.md` - zasady pracy zespolowej i sesyjnej
- `docs/ARCHITECTURE.md` - opis aktualnej i docelowej architektury
- `docs/ROADMAP.md` - fazy rozwoju (A: Stabilizacja, B: Homeostasis, C: Optymalizacja)
- `docs/STABILIZATION_PLAN.md` - szczegolowa checklista bugow do naprawy
- `docs/DECISIONS.md` - ADR + open questions
- `docs/CHANGELOG.md` - ten plik
- `docs/SESSION_LOG.md` - dziennik pracy

### Discovered
- 8 bugow zidentyfikowanych (3x P0, 3x P1, 2x P2)
- 5 open questions do wyjasnienia z wlascicielem

### Fixed (5 bugow naprawionych)
- **BUG-001** `main.py`: Usunieto przedwczesne `if __name__` i konfliktowy import
- **BUG-002** `perception.py`: Poprawiono wciecia klasy Perception (metody sa teraz w klasie)
- **BUG-003** `learning_agent.py`: Usunieto przypadkowo wklejony debug code z learn_chunk()
- **BUG-004** `perception.py`: Zamieniono hardcoded sciezki na KNOWLEDGE_INDEX z config
- **BUG-006** `orchestrator.py`: StripEmojiFilter teraz usuwa tylko emoji, zachowuje polskie znaki

### Verified
- Wszystkie krytyczne importy dzialaja poprawnie
- Zainstalowano brakujace zaleznosci (requests, psutil, ollama)

---

## [Pre-2026] - Historia przed dokumentacja

> Uwaga: Ponizsze to rekonstrukcja na podstawie analizy kodu. Daty przybliozone.

### ~2024-11-30
- Utworzenie projektu DEAMONMARIA V2
- Podstawowa struktura: perception, learning, exam, memory
- Konfiguracja Ollama

### ~2024-12-07
- Dodanie semantic_graph.py
- Rozbudowa meta_controller.py
- Dodanie resource_watchdog.py

### ~2024-12-08
- main.py - rozszerzony REPL z wieloma komendami
- brain_memory_integration.py

---

*Aktualizuj ten plik przy kazdej znaczacej zmianie.*
