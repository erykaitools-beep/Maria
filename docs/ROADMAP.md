# M.A.R.I.A. - Development Roadmap
> Version: 0.1 | Last updated: 2026-01-26

## Overview

Rozwoj M.A.R.I.A. podzielony jest na trzy glowne fazy:

| Faza | Nazwa | Cel | Status |
|------|-------|-----|--------|
| A | Stabilizacja | Naprawic bledy, uzyskac stabilny runtime | **IN PROGRESS** |
| B | Full Homeostasis | Pelna autonomia z petlami regulacji | PLANNED |
| C | Optymalizacja/Skalowanie | Wydajnosc, nowe funkcje | PLANNED |

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
- [ ] `main.py`: przeniesc `if __name__` na koniec pliku
- [ ] `perception.py`: poprawic wciecia klasy Perception
- [ ] `learning_agent.py`: usunac wklejony debug code

#### A2: Spojnosc sciezek (P1)
- [ ] Ujednolicic sciezki indeksow (tylko config.py jako source of truth)
- [ ] Usunac hardcoded paths z perception.py
- [ ] Sprawdzic memory_store.py MEMORY_INDEX_PATH

#### A3: Jakosc i bezpieczenstwo (P2)
- [ ] Naprawic StripEmojiFilter (nie usuwac polskich znakow)
- [ ] Dodac timeout do file locking (opcjonalnie)

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
- [ ] Dodac cap na episodic_memory (max N epizodow, FIFO)
- [ ] Zaimplementowac archiwizacje starych epizodow
- [ ] Dodac pruning do semantic_graph (automatyczny)

#### B2: Consolidation Scheduler
- [ ] Harmonogram konsolidacji (co N operacji / co M minut)
- [ ] Automatyczny merge podobnych wezlow
- [ ] Kompresja/rotacja logow JSONL

#### B3: Mode Regulator Enhancement
- [ ] Jasne przejscia miedzy trybami (state machine diagram)
- [ ] Auto-recovery z RECOVERY do LEARNING
- [ ] Timeout w trybie RECOVERY

#### B4: Energy Budget
- [ ] Monitoring zuzycia tokenow per sesja
- [ ] Throttling przy wysokim zuzyciu
- [ ] Raportowanie statystyk

#### B5: Reporting & Alerting
- [ ] Regularne raporty stanu (co N minut)
- [ ] Alerty przy anomaliach
- [ ] Dashboard/summary endpoint

### Definition of Done: Faza B
- [ ] System dziala 8+ godzin bez interwencji
- [ ] Automatyczny recovery po problemach
- [ ] Pamiec (RAM) stabilna przez caly czas
- [ ] Logi nie rosna nieograniczenie
- [ ] Graf konsoliduje sie automatycznie

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
- [ ] TBD (zalezy od priorytetow po Fazie B)

### Estymacja
6-10 sesji pracy

---

## Milestones

| Milestone | Opis | Target |
|-----------|------|--------|
| M1 | Faza A complete - stabilny runtime | Sesja 2-3 |
| M2 | Faza B1-B2 complete - memory management | Sesja 5-6 |
| M3 | Faza B complete - full homeostasis | Sesja 8-10 |
| M4 | Faza C complete - production ready | TBD |

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
