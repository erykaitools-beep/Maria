# M.A.R.I.A. - Stabilization Plan (Faza A)
> Version: 0.2 | Last updated: 2026-01-26

## Status: IN PROGRESS (5/8 naprawionych)

## Podsumowanie

| Priorytet | Liczba | Naprawione | Pozostalo |
|-----------|--------|------------|-----------|
| P0 (Critical) | 3 | 3 | 0 |
| P1 (High) | 3 | 2 | 1 |
| P2 (Medium) | 2 | 0 | 2 |
| **TOTAL** | **8** | **5** | **3** |

---

## P0: RUNTIME KILLERS (blokuja uruchomienie)

### BUG-001: main.py - przedwczesne wywolanie main()
- **Lokalizacja:** `main.py:16-17`
- **Symptom:** `if __name__ == "__main__": main()` jest W SRODKU pliku + import kolizyjny z orchestrator.main
- **Przyczyna:** Bledne umieszczenie entry point + konflikt nazw
- **Fix:** Usunieto przedwczesne wywolanie i import `main` z orchestratora
- **Status:** [x] DONE (2026-01-26)
- **Test:** `python -c "from main import main"` - PASS
- **Ryzyko:** WYSOKIE - skrypt nie dziala w ogole

---

### BUG-002: perception.py - metody poza klasa
- **Lokalizacja:** `perception.py:297-332`
- **Symptom:** Klasa `Perception` ma `@staticmethod` BEZ WCIECIA - sa poza ciałem klasy
- **Przyczyna:** Bledne wciecia (brak 4 spacji przed @staticmethod)
- **Fix:** Dodano poprawne wciecia do wszystkich metod klasy Perception
- **Status:** [x] DONE (2026-01-26)
- **Test:** `from maria_core.perception.perception import Perception; print(hasattr(Perception, 'scan_for_new_files'))` - PASS (True)
- **Ryzyko:** WYSOKIE - klasa Perception nie dziala

---

### BUG-003: learning_agent.py - wklejony debug code
- **Lokalizacja:** `learning_agent.py:236-266`
- **Symptom:** Funkcja `learn_chunk()` zawiera wklejony kod ktory nie jest czescia funkcji
- **Przyczyna:** Przypadkowe wklejenie podczas edycji
- **Fix:** Usunieto wklejony debug code z docstringa funkcji
- **Status:** [x] DONE (2026-01-26)
- **Test:** `from maria_core.learning.learning_agent import learn_chunk` - PASS
- **Ryzyko:** WYSOKIE - modul nie importuje sie poprawnie

---

## P1: HIGH PRIORITY (bledne dane / crash w runtime)

### BUG-004: Niespojne sciezki indeksu
- **Lokalizacja:** `perception.py:308,313,330` vs `config.py:29`
- **Symptom:** perception.py uzywa hardcoded `"data/knowledge_index.jsonl"`, config.py definiuje `MEMORY_DIR / "knowledge_index.jsonl"`
- **Przyczyna:** Brak spojnosci miedzy modulami
- **Fix:** Zaimportowano `KNOWLEDGE_INDEX` z config.py i zamieniono wszystkie hardcoded paths
- **Status:** [x] DONE (2026-01-26)
- **Test:** Perception uzywa teraz `KNOWLEDGE_INDEX` z config
- **Ryzyko:** SREDNIE - dwa rozne pliki indeksu

---

### BUG-005: memory_store.py - globalna instancja z bledna sciezka
- **Lokalizacja:** `memory_store.py:245-252`
- **Symptom:** `MEMORY_INDEX_PATH = MEMORY_DIR / "memory_index.json"` (z .json nie .jsonl!)
- **Przyczyna:** Literowka lub stary kod
- **Fix:**
  1. Usunac globalna instancje `memory_store` jesli nie jest uzywana
  2. LUB poprawic rozszerzenie na .jsonl i ujednolicic ze sciezkami w config
- **Status:** [ ] TODO
- **Test:** Zweryfikowac czy memory_store global jest w ogole uzywany (grep)
- **Ryzyko:** SREDNIE - potencjalna niespojnosc danych

---

### BUG-006: StripEmojiFilter usuwa polskie znaki
- **Lokalizacja:** `orchestrator.py:13-31`
- **Symptom:** Pattern `[^\x00-\x7F]+` usuwa WSZYSTKIE znaki non-ASCII, wlacznie z polskimi (a,e,o,s,z...)
- **Przyczyna:** Zbyt agresywny regex
- **Fix:** Zmieniono pattern na regex usuwajacy tylko emoji (Unicode emoji ranges)
- **Status:** [x] DONE (2026-01-26)
- **Test:** Polskie znaki w logach sa zachowane
- **Ryzyko:** SREDNIE - logi sa nieczytelne dla polskiego uzytkownika

---

## P2: MEDIUM PRIORITY (tech debt / degradacja)

### BUG-007: Brak timeout w Windows file locking
- **Lokalizacja:** `memory_store.py:27-33`
- **Symptom:** `msvcrt.locking()` moze zablokowac watek na zawsze przy konflikcie
- **Przyczyna:** Brak retry/timeout w implementacji
- **Fix:** Dodac retry loop z timeout (np. 5 prob co 0.1s)
- **Status:** [ ] TODO
- **Test:** Manualne - otworzyc plik w innym procesie, sprawdzic czy nie zawiesza
- **Ryzyko:** NISKIE - rzadko wystepuje

---

### BUG-008: Duplikacja logiki JSON extraction
- **Lokalizacja:** `learning_agent.py:129-171` vs `ollama_brain.py:103-132`
- **Symptom:** Dwie osobne implementacje extract_json, potencjalnie rozne zachowanie
- **Przyczyna:** Kod rozwijany niezaleznie
- **Fix:** Wydzielic wspolna funkcje do utils lub ollama_brain i uzyc w obu miejscach
- **Status:** [ ] TODO
- **Test:** Oba moduly uzywaja tej samej funkcji
- **Ryzyko:** NISKIE - dziala, ale tech debt

---

## Kolejnosc wykonania (zaktualizowana)

1. ~~**BUG-001** (main.py)~~ - DONE
2. ~~**BUG-002** (perception.py)~~ - DONE
3. ~~**BUG-003** (learning_agent.py)~~ - DONE
4. ~~**BUG-006** (StripEmojiFilter)~~ - DONE
5. ~~**BUG-004** (sciezki perception)~~ - DONE
6. **BUG-005** (memory_store global) - TODO
7. **BUG-007** (file locking) - TODO
8. **BUG-008** (JSON extraction) - TODO

---

## Kryterium akceptacji Fazy A

- [x] Wszystkie krytyczne importy dzialaja
- [ ] `python main.py` uruchamia sie i wyswietla REPL (wymaga Ollama)
- [ ] `python run_maria.py` wykonuje pelny cykl uczenia bez crashy (wymaga Ollama)
- [x] Logi zachowuja polskie znaki (StripEmojiFilter naprawiony)
- [x] Perception uzywa sciezek z config.py (BUG-004 naprawiony)
- [ ] Wszystkie BUG-00X oznaczone jako DONE (5/8)

---

*Aktualizuj ten dokument po kazdej naprawie - zaznacz [x] przy DONE*
