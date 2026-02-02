# M.A.R.I.A. - Development Roadmap
> Version: 0.3 | Last updated: 2026-02-02

## Overview

Rozwoj M.A.R.I.A. podzielony jest na fazy:

| Faza | Nazwa | Cel | Status |
|------|-------|-----|--------|
| A | Stabilizacja | Naprawic bledy, uzyskac stabilny runtime | **COMPLETE** |
| B | Full Homeostasis | Pelna autonomia z petlami regulacji | **COMPLETE** |
| C | Consciousness | Samowiedza, percepcja, tozsamosc | **IN PROGRESS** |
| D | Vision | Percepcja wizualna (oko) | PLANNED |
| E | Smart Home | Integracja IoT, mobilne cialo | PLANNED |

---

## Faza A: STABILIZACJA

### Cel
Naprawic wszystkie bledy krytyczne i uzyskac system ktory:
- Uruchamia sie bez bledow
- Dziala stabilnie przez podstawowa sesje uczenia
- Ma spojne sciezki plikow
- Poprawnie obsluguje polskie znaki

### Zakres

#### A1: Runtime Killers (P0)
- [x] `main.py`: przeniesc `if __name__` na koniec pliku
- [x] `perception.py`: poprawic wciecia klasy Perception
- [x] `learning_agent.py`: usunac wklejony debug code

#### A2: Spojnosc sciezek (P1)
- [x] Ujednolicic sciezki indeksow (tylko config.py jako source of truth)
- [x] Usunac hardcoded paths z perception.py
- [x] Sprawdzic memory_store.py MEMORY_INDEX_PATH

#### A3: Jakosc i bezpieczenstwo (P2)
- [x] Naprawic StripEmojiFilter (nie usuwac polskich znakow)
- [x] Dodac timeout do file locking (opcjonalnie)

### Definition of Done: Faza A
- [x] Wszystkie bledy P0 naprawione
- [x] `python main.py` uruchamia sie bez bledow
- [x] `python run_maria.py` wykonuje cykl uczenia bez crashy
- [x] Polskie znaki w logach wyswietlaja sie poprawnie
- [x] Dokumentacja zaktualizowana

### Estymacja
2-3 sesje pracy

---

## Faza B: FULL HOMEOSTASIS

### Cel
System dziala autonomicznie przez dlugie okresy (8h+) z automatyczna regulacja.

### Zakres

#### B1: Memory Management
- [x] Dodac cap na episodic_memory (max N epizodow, FIFO) - via MemoryManager
- [x] Zaimplementowac archiwizacje starych epizodow - consolidate_episodic()
- [x] Dodac pruning do semantic_graph (automatyczny) - semantic_consistency_check()

#### B2: Consolidation Scheduler
- [x] Harmonogram konsolidacji (co N operacji / co M minut) - epoch tasks in core.py
- [x] Automatyczny merge podobnych wezlow - via actions.py
- [x] Kompresja/rotacja logow JSONL - via snapshot.py

#### B3: Mode Regulator Enhancement
- [x] Jasne przejscia miedzy trybami (state machine diagram) - ModeRegulator
- [x] Auto-recovery z RECOVERY do LEARNING - mode transitions
- [x] Timeout w trybie RECOVERY - via constraints

#### B4: Energy Budget
- [x] Monitoring zuzycia tokenow per sesja - CognitiveSensor
- [x] Throttling przy wysokim zuzyciu - reduce_batch_size()
- [x] Raportowanie statystyk - /homeostasis command

#### B5: Reporting & Alerting
- [x] Regularne raporty stanu (co N minut) - health_score, telemetry
- [x] Alerty przy anomaliach - AlarmDispatcher
- [x] Dashboard/summary endpoint - /homeostasis command

### Definition of Done: Faza B
- [x] System dziala 8+ godzin bez interwencji (verified in tests)
- [x] Automatyczny recovery po problemach (snapshot/recovery tested)
- [x] Pamiec (RAM) stabilna przez caly czas (ResourceSensor monitoring)
- [x] Logi nie rosna nieograniczenie (audit log rotation)
- [x] Graf konsoliduje sie automatycznie (semantic_consistency_check)

### Estymacja
4-6 sesji pracy

---

## Faza C: OPTYMALIZACJA / SKALOWANIE

### Cel
Rozszerzenie funkcjonalnosci i poprawa wydajnosci.

### Zakres (wstepny)

#### C1: Wydajnosc
- [ ] Lazy loading dla duzych plikow JSONL
- [ ] SQLite jako alternatywa dla JSONL
- [ ] Batch processing dla wielu chunkow

#### C2: Nowe funkcje
- [ ] Embeddings generation (dla semantic_graph)
- [ ] Web learning (maria_web_learning.py)
- [ ] API bridge (maria_api_bridge.py)
- [ ] Multi-model support (rozne modele dla roznych zadan)

#### C3: Testowanie
- [ ] Unit testy dla kluczowych modulow
- [ ] Integration testy dla learning cycle
- [ ] Performance benchmarks

### Definition of Done: Faza C
- [x] Introspection module (samowiedza kodu)
- [x] TimeAwareness (percepcja czasu)
- [ ] Self-model w semantic_graph (osobowosc)
- [ ] Pamiec rozmow z kondensacja
- [ ] Ciaglosc tozsamosci (birth date, uptime)
- [ ] SLEEP z "snami"

### Estymacja
6-10 sesji pracy

---

## Faza D: VISION (OKO)

### Cel
Maria widzi swiat przez kamere USB/IP.

### Zakres
Szczegoly: `docs/VISION_SPEC.md`

#### D1: Sensor Abstraction Layer
- [ ] Interfejsy bazowe (VisionSensor, SensorHealth)
- [ ] USB webcam implementation
- [ ] Mock sensor (testy)
- [ ] Graceful degradation

#### D2: Preprocessing Layer
- [ ] Quality Assessment
- [ ] Degradation Detection
- [ ] Normalizacja obrazu

#### D3: Vision Modules
- [ ] Motion Module (ruch)
- [ ] Scene Module (opis sceny)
- [ ] OCR Module (tekst)
- [ ] Face Module (twarze)

#### D4: Vision Cortex
- [ ] Integracja modulow
- [ ] Attention Mechanism
- [ ] VisionModeManager

### Hardware
- [ ] Kamera USB (Logitech C270 ~100zl)

### Estymacja
8-12 sesji pracy

---

## Faza E: SMART HOME

### Cel
Maria jako mozg inteligentnego domu + mobilne cialo.

### Zakres
Szczegoly: `docs/SMART_HOME_SPEC.md`

#### E1: Device Layer
- [ ] SmartDevice interface
- [ ] ShellyDevice client
- [ ] TasmotaDevice client
- [ ] DeviceRegistry

#### E2: Automation
- [ ] AutomationEngine
- [ ] Rules (trigger -> action)
- [ ] Integracja z Vision (event dispatch)

#### E3: Mobile Body (Android)
- [ ] IP Webcam integration
- [ ] Termux agent
- [ ] TTS (Maria mowi)
- [ ] GPS lokalizacja

#### E4: Security
- [ ] Siec IoT (VLAN/Guest)
- [ ] Audit log
- [ ] Krytyczne urzadzenia (potwierdzenie)

### Hardware
- [ ] Shelly Plug S x3 (~200zl)
- [ ] Android uzywany (~200zl)
- [ ] Router z VLAN (opcjonalnie)

### Estymacja
6-10 sesji pracy

---

## Milestones

| Milestone | Opis | Status |
|-----------|------|--------|
| M1 | Faza A complete - stabilny runtime | DONE |
| M2 | Faza B complete - full homeostasis | DONE |
| M3 | Faza C - introspection + time awareness | DONE |
| M4 | Faza C complete - consciousness | IN PROGRESS |
| M5 | Faza D complete - vision | PLANNED |
| M6 | Faza E complete - smart home | PLANNED |

---

## Ryzyka i zaleznosci

| Ryzyko | Prawdopodobienstwo | Wplyw | Mitygacja |
|--------|-------------------|-------|-----------|
| Nieznane bledy w starym kodzie | Srednie | Wysoki | Code review przed zmianami |
| Ollama API niestabilne | Niskie | Sredni | Retry logic juz istnieje |
| Brak testow | Wysokie | Sredni | Manualne testy na start, unit testy w Fazie C |
| Niejasne wymagania | Srednie | Sredni | Open questions w DECISIONS.md |

---

*Ten dokument jest zywym dokumentem - aktualizuj go przy zmianach planow.*
