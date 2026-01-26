# M.A.R.I.A. - Architecture Decision Records (ADR)
> Version: 0.2 | Last updated: 2026-01-26

## Format ADR

```
### ADR-XXX: Tytul decyzji
**Data:** YYYY-MM-DD
**Status:** PROPOSED | ACCEPTED | DEPRECATED | SUPERSEDED

**Kontekst:** Opis sytuacji i problemu

**Decyzja:** Co postanowilismy

**Alternatywy:**
1. Alternatywa A - dlaczego odrzucona
2. Alternatywa B - dlaczego odrzucona

**Konsekwencje:**
- Pozytywne: ...
- Negatywne: ...

**Refs:** linki do powiazanych dokumentow/issues
```

---

## Zaakceptowane decyzje

### ADR-001: JSONL jako format pamieci
**Data:** ~2024 (zastalosci)
**Status:** ACCEPTED

**Kontekst:** System potrzebuje trwalego przechowywania danych (indeks wiedzy, pamiec, wyniki egzaminow).

**Decyzja:** Uzycie formatu JSONL (JSON Lines) - jeden obiekt JSON per linia.

**Alternatywy:**
1. SQLite - odrzucone: dodatkowa zaleznosc, bardziej skomplikowane
2. Pojedynczy JSON - odrzucone: problemy z appendem, caly plik w pamieci

**Konsekwencje:**
- Pozytywne: prosty append, czytelny format, latwy debug
- Negatywne: wolne wyszukiwanie (skanowanie calego pliku), brak indeksow

---

### ADR-002: Ollama jako backend LLM
**Data:** ~2024 (zastalosci)
**Status:** ACCEPTED

**Kontekst:** System potrzebuje lokalnego LLM do analizy tekstu, generowania pytan, oceny.

**Decyzja:** Uzycie Ollama z modelem llama3.1:8b.

**Alternatywy:**
1. OpenAI API - odrzucone: wymaga internetu, koszty, prywatnosc
2. Inne lokalne (llama.cpp bezposrednio) - odrzucone: Ollama prostsze API

**Konsekwencje:**
- Pozytywne: offline-first, darmowe, kontrola nad danymi
- Negatywne: wymaga GPU lub dobrego CPU, wolniejsze niz cloud

---

### ADR-003: Adaptive chunking z overlapping
**Data:** ~2024 (zastalosci)
**Status:** ACCEPTED

**Kontekst:** Teksty do nauki moga byc dlugie. LLM ma ograniczony context window.

**Decyzja:** Podzial tekstu na chunki ~1200 znakow z 150-znakowym overlapem. Szukanie naturalnych granic (paragrafy, zdania).

**Konsekwencje:**
- Pozytywne: zachowanie kontekstu na granicach, lepsze summary
- Negatywne: duplikacja fragmentow, wieksze zuzycie tokenow

---

## Oczekujace decyzje (PROPOSED)

### ADR-004: Synchronizacja JSONL i SemanticGraph
**Data:** 2026-01-26
**Status:** ACCEPTED

**Kontekst:** System ma dwa systemy pamieci:
1. JSONL files (memory_store.py) - surowe dane
2. SemanticGraph (semantic_graph.py) - graf wiedzy

Obecnie nie sa zsynchronizowane.

**Opcje:**
A) JSONL jako source of truth, graf tylko in-memory cache
B) Graf jako source of truth, JSONL jako backup/log
C) Oba rownoprawne, synchronizacja dwukierunkowa

**Decyzja:** Opcja A - JSONL jest source of truth, graf jest pochodnym indeksem/cache.

**Uzasadnienie (od wlasciciela):** Graf semantyczny ma byc in-memory cache budowany z JSONL przy starcie. JSONL zawsze zawiera pelne dane, graf jest tylko ich reprezentacja do szybkiego wyszukiwania.

**Konsekwencje:**
- Pozytywne: Jasna hierarchia danych, prostsze recovery (odbuduj graf z JSONL)
- Negatywne: Czas startu moze byc dluzszy przy duzych danych (budowanie grafu)

**Refs:** Q-005, homeostasis_spec.md (Episodic + Semantic = recovery)

---

### ADR-005: Cap na episodic_memory
**Data:** 2026-01-26
**Status:** PROPOSED

**Kontekst:** `episodic_memory` (lista w brain_memory_integration.py) rosnie bez ograniczen. Przy dlugich sesjach moze zuzywac duzo RAM.

**Opcje:**
A) FIFO z maxlen (np. 1000 epizodow)
B) Time-based pruning (usun starsze niz N godzin)
C) Importance-based pruning (usun epizody z success=False)

**Decyzja:** TBD

---

## Resolved Questions (odpowiedzi od wlasciciela)

### Q-001: Czy folder archive/ jest uzywany?
**Data:** 2026-01-26
**Status:** RESOLVED

**Kontekst:** Folder `archive/` zawiera stary kod (brain/, tools/, perception.py). Nie jest importowany przez zadne aktywne moduly.

**Odpowiedz:** Folder `archive/` NIE jest uzywany. Nalezy go oznaczyc jako deprecated i nie brac pod uwage przy refaktoryzacji.

**Akcja:** Dodac `archive/` do `.gitignore` lub usunac w Etapie 5 refaktoryzacji.

---

### Q-002: Intencja dwoch entry pointow (main.py vs run_maria.py)
**Data:** 2026-01-26
**Status:** RESOLVED

**Kontekst:**
- `main.py` - interaktywny REPL z wieloma komendami
- `run_maria.py` - daemon uruchamiajacy learning cycle

**Odpowiedz:** Opcja A - ALTERNATYWNIE. Uzytkownik wybiera jeden z entry pointow:
- `main.py` dla interaktywnej pracy
- `run_maria.py` dla batch learning

NIE maja dzialac rownolegle.

**Akcja:** Dodac walidacje w obu plikach - sprawdzac czy drugi proces juz dziala (PID file lub port check).

---

### Q-003: orchestrator.py main() z max_iterations=0
**Data:** 2026-01-26
**Status:** RESOLVED

**Kontekst:** W `orchestrator.py:191-195`:
```python
def main():
    maria_learning_cycle(max_iterations=0, ...)  # Zero iteracji?
```

**Odpowiedz:** `max_iterations=0` oznacza NIESKONCZONA PETLE (infinite loop). To jest intencjonalne zachowanie.

**Akcja:** Zmienic parametr na `None` lub `-1` dla lepszej czytelnosci. Dodac komentarz wyjasniajacy.

---

### Q-004: Czy maria_web_learning.py i maria_api_bridge.py maja byc zaimplementowane?
**Data:** 2026-01-26
**Status:** RESOLVED

**Kontekst:** main.py probuje importowac te moduly, ale nie istnieja w repo.

**Odpowiedz:** NIE implementowac teraz. To sa planowane funkcje na przyszlosc (roadmap), ale nie sa czescia obecnego scope.

**Akcja:** Pozostawic importy jako opcjonalne (try/except) z komentarzem "TODO: future feature". Dodac do ROADMAP.md jako Faza C lub D.

---

### Q-005: Docelowa integracja graf <-> JSONL
**Data:** 2026-01-26
**Status:** RESOLVED → ADR-004

**Kontekst:** Graf semantyczny i JSONL storage to dwa odrebne systemy.

**Odpowiedz:** Opcja A - JSONL jest source of truth, graf jest pochodnym indeksem/cache budowanym z JSONL przy starcie.

**Akcja:** Zaimplementowac w `agent_core/memory/semantic_store.py` metode `rebuild_from_jsonl()`.

---

## Open Questions (pytania do wlasciciela)

*Brak aktualnie otwartych pytan.*

---

*Dodawaj nowe pytania i decyzje w miare postepow prac.*
