# M.A.R.I.A. - Changelog
> Format: [YYYY-MM-DD] Kategoria: Opis

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
