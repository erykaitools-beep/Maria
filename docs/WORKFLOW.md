# M.A.R.I.A. - Workflow & Collaboration Guidelines
> Version: 0.1 | Last updated: 2026-01-26

## 1. Tryb pracy sesyjnej

### 1.1 Zasady ogolne
- **Dokumentacja przed kodem** - kazda wazna zmiana architektoniczna wymaga wpisu w docs/ ZANIM dotykamy kodu
- **Minimalny diff** - kazda zmiana ma jasny, waski zakres i cel
- **Audit trail** - wszystko zostawia slad w repo (SESSION_LOG, CHANGELOG, DECISIONS)
- **Nie zgaduj** - jesli cos niepewne, zapisz jako pytanie/zalozenie w DECISIONS.md

### 1.2 Struktura sesji
```
1. [START] Przeczytaj docs/SESSION_LOG.md -> sekcja "NEXT ACTIONS"
2. [PRACA] Wykonuj zadania, aktualizuj TODO
3. [CHECKPOINT] Po kazdej wiekszej zmianie:
   - Wpis do SESSION_LOG.md
   - Wpis do CHANGELOG.md
   - Jesli decyzja: wpis do DECISIONS.md
4. [KONIEC] Zaktualizuj SESSION_LOG: DONE / NEXT / RISKS / QUESTIONS
```

## 2. Checkpointy

### 2.1 Kiedy robic checkpoint?
- Po naprawie krytycznego bledu
- Po refaktorze jednego modulu
- Po dodaniu nowej funkcjonalnosci
- Co 2-3 mniejsze zmiany

### 2.2 Co zawiera checkpoint?
```markdown
### [YYYY-MM-DD HH:MM] Nazwa zmiany
**Pliki:** lista zmienionych plikow
**Co:** krotki opis zmiany
**Dlaczego:** uzasadnienie
**Wynik:** PASS/FAIL + ewentualne uwagi
**Test:** komenda weryfikujaca (jesli dotyczy)
```

## 3. Zasady commitow (gdy repo jest git)

### 3.1 Format commit message
```
[KATEGORIA] Krotki opis (max 72 znaki)

- Szczegol 1
- Szczegol 2

Refs: #issue lub docs/DECISIONS.md#ADR-XXX
```

### 3.2 Kategorie
- `[FIX]` - naprawa bledu
- `[REFACTOR]` - refaktoryzacja bez zmiany funkcjonalnosci
- `[FEAT]` - nowa funkcjonalnosc
- `[DOCS]` - zmiany w dokumentacji
- `[TEST]` - testy
- `[CHORE]` - porządki, konfiguracja

## 4. Raportowanie problemow

### 4.1 Wykryty bug
Dodaj do STABILIZATION_PLAN.md:
```markdown
### BUG-XXX: Nazwa bledu
- **Lokalizacja:** plik:linia
- **Symptom:** co sie dzieje
- **Przyczyna:** (jesli znana)
- **Fix:** proponowane rozwiazanie
- **Status:** [ ] TODO / [x] DONE
- **Test:** komenda weryfikujaca
```

### 4.2 Decyzja architektoniczna
Dodaj do DECISIONS.md jako ADR (Architecture Decision Record).

### 4.3 Pytanie do wlasciciela
Dodaj do DECISIONS.md w sekcji "Open Questions".

## 5. Priorytety pracy

```
P0 (CRITICAL) - Blokuje uruchomienie systemu
P1 (HIGH)     - Powoduje crash/bledne dane w runtime
P2 (MEDIUM)   - Degraduje jakosc/wydajnosc
P3 (LOW)      - Tech debt, cleanup, nice-to-have
```

## 6. Definition of Done (dla zadan)

Zadanie jest DONE gdy:
- [ ] Kod dziala (brak syntax errors)
- [ ] Przechodzi podstawowy test (manual lub automated)
- [ ] Wpis w SESSION_LOG.md
- [ ] Wpis w CHANGELOG.md
- [ ] Jesli decyzja: wpis w DECISIONS.md
- [ ] STABILIZATION_PLAN.md zaktualizowany (jesli dotyczy)

---
*Ten dokument jest zywym dokumentem - aktualizuj go gdy zmieniaja sie zasady.*
