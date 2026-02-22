# M.A.R.I.A. - Plan Testu Stabilności 36h

> **Data utworzenia:** 2026-01-31
> **Cel:** Weryfikacja stabilności całej architektury w długoterminowej pracy

---

## 1. Przygotowanie przed testem

### 1.1 Środowisko

```bash
# Sprawdź wersję Python
python --version  # Oczekiwane: 3.8+

# Sprawdź Ollama
ollama list       # Powinien pokazać llama3.1:8b
ollama ps         # Sprawdź czy model jest załadowany

# Sprawdź RAM przed startem
# Windows: Task Manager → Performance → Memory
# Zapisz: RAM used / RAM total
```

### 1.2 Przygotuj pliki wejściowe

Umieść pliki `.txt` w folderze `input/`:
- Minimum 5-10 plików tekstowych do nauki
- Różna wielkość (1KB - 50KB)
- Różna tematyka

### 1.3 Wyczyść stare dane (opcjonalnie)

```bash
# Backup starych danych
mkdir backup_before_36h
copy memory\*.jsonl backup_before_36h\
copy meta_data\*.jsonl backup_before_36h\

# Opcjonalnie: wyczyść logi homeostazy (świeży start)
del meta_data\homeostasis_events.jsonl
```

### 1.4 Sprawdź testy

```bash
cd "C:\MariaLocal\Moja AI. Maria Ver.4"
python -m pytest agent_core/tests/ -v --tb=short
# Oczekiwane: 216 passed
```

---

## 2. Procedura startu testu

### 2.1 Uruchom REPL

```bash
cd "C:\MariaLocal\Moja AI. Maria Ver.4"
python main.py
```

### 2.2 Sprawdź status początkowy

```
/status
/homeostasis
```

**Zapisz w notatniku:**
- [ ] Godzina startu: `__________`
- [ ] RAM na starcie: `_______ MB / _______ MB`
- [ ] CPU na starcie: `_______ %`
- [ ] Liczba węzłów w grafie: `_______`
- [ ] Liczba epizodów: `_______`

### 2.3 Uruchom homeostasis

```
/homeostasis start
```

Powinno pokazać: `[Homeostasis] ✅ Monitoring started`

### 2.4 Uruchom agenta w tle

```
/start
```

Powinno pokazać: `[System] ✅ Agent uruchomiony w tle.`

---

## 3. Harmonogram sprawdzania

### Punkty kontrolne (checkpoints)

| Godzina | Czas od startu | Co sprawdzić | Akcje |
|---------|----------------|--------------|-------|
| Start | 0h | Status początkowy | Zapisz baseline |
| +1h | 1h | Pierwszy checkpoint | Sprawdź logi |
| +3h | 3h | Wczesne wykrywanie problemów | Sprawdź RAM |
| +6h | 6h | Ćwierć testu | Pełny raport |
| +12h | 12h | Połowa testu | Pełny raport |
| +18h | 18h | 3/4 testu | Sprawdź trendy |
| +24h | 24h | Dobowy checkpoint | Pełny raport |
| +30h | 30h | Przedostatni | Sprawdź trendy |
| +36h | 36h | KONIEC | Pełny raport końcowy |

### 3.1 Procedura szybkiego sprawdzenia (5 min)

```
/homeostasis
/homeostasis events 5
```

**Zapisz:**
- [ ] Tryb: `ACTIVE / REDUCED / SLEEP / SURVIVAL`
- [ ] Health: `_______ %`
- [ ] Czy były zmiany trybu? `TAK / NIE`

### 3.2 Procedura pełnego raportu (15 min)

```
/homeostasis
/homeostasis summary
/homeostasis events 20
/status
/nodes
/episodes
```

**Zapisz w formularzu:**

```
=== CHECKPOINT [godzina: _______] ===
Czas od startu: _______ h

HOMEOSTASIS:
- Tryb: _______
- Health: _______ %
- Mode changes: _______
- Alerts (CRITICAL/ALERT/WARNING): ___/___/___

ZASOBY:
- RAM used: _______ MB
- RAM available: _______ %
- CPU: _______ %

NAUKA:
- Węzły w grafie: _______
- Epizody: _______
- Pomyślne epizody: _______

OBSERWACJE:
_________________________________
_________________________________

PROBLEMY:
_________________________________
```

---

## 4. Co obserwować

### 4.1 Zdrowe oznaki (OK)

✅ Tryb pozostaje `ACTIVE` przez większość czasu
✅ Health score > 70%
✅ RAM stabilny lub wolno rośnie
✅ Liczba węzłów i epizodów rośnie
✅ Przejścia do `REDUCED` przy obciążeniu, powrót do `ACTIVE`
✅ Brak alertów `CRITICAL`

### 4.2 Sygnały ostrzegawcze (UWAGA)

⚠️ Health score spada poniżej 60%
⚠️ RAM rośnie szybko (> 100MB/h)
⚠️ Częste przejścia między trybami (> 10/h)
⚠️ Alerty `ALERT` pojawiają się regularnie
⚠️ Tryb `REDUCED` przez > 30 min bez powrotu

### 4.3 Sygnały krytyczne (INTERWENCJA)

🚨 Tryb `SURVIVAL` - system w trybie awaryjnym
🚨 Health score < 30%
🚨 RAM > 90% użycia
🚨 Alerty `CRITICAL`
🚨 System nie odpowiada na komendy
🚨 Błędy w konsoli

---

## 5. Scenariusze testowe (opcjonalne)

### 5.1 Test obciążenia pamięci (godzina 6)

1. Otwórz kilka dużych aplikacji (przeglądarka z wieloma zakładkami)
2. Obserwuj czy homeostasis przechodzi do `REDUCED`
3. Zamknij aplikacje
4. Obserwuj czy wraca do `ACTIVE`

**Oczekiwany wynik:** Automatyczne przejście ACTIVE → REDUCED → ACTIVE

### 5.2 Test uczenia (godzina 12)

```
/learn 0.7
```

1. Uruchom cykl uczenia
2. Obserwuj czy homeostasis reaguje na obciążenie
3. Sprawdź czy nowe węzły pojawiają się w grafie

### 5.3 Test interakcji (godzina 18)

1. Wpisz kilka pytań do Marii
2. Sprawdź czy odpowiada sensownie
3. Sprawdź czy epizody są zapisywane

### 5.4 Test idle (godzina 24-30)

1. Zostaw system bez interakcji na 2+ godziny
2. Sprawdź czy przechodzi do `SLEEP`
3. Wpisz cokolwiek - sprawdź czy budzi się

---

## 6. Zbieranie logów

### 6.1 Pliki do zachowania po teście

```
meta_data/homeostasis_events.jsonl    # ← NAJWAŻNIEJSZY
memory/knowledge_index.jsonl
memory/maria_longterm_memory.jsonl
memory/exam_results.jsonl
logs/learning.log
semantic_graph.json
```

### 6.2 Eksport danych na koniec

```
/save
/export-learned
/report
/homeostasis summary
/homeostasis events 100
```

---

## 7. Zakończenie testu

### 7.1 Procedura zatrzymania

```
/stop                    # Zatrzymaj agenta
/homeostasis stop        # Zatrzymaj homeostasis
/save                    # Zapisz graf
/exit                    # Wyjdź z REPL
```

### 7.2 Raport końcowy

**Wypełnij formularz końcowy:**

```
=== RAPORT KOŃCOWY TESTU 36H ===

CZAS:
- Start: _______ (data, godzina)
- Koniec: _______ (data, godzina)
- Rzeczywisty czas: _______ h

HOMEOSTASIS:
- Całkowita liczba mode changes: _______
- Tryby odwiedzone: _______
- Najdłuższy czas w ACTIVE: _______ h
- Czas w REDUCED: _______ h
- Czas w SLEEP: _______ h
- Czy był SURVIVAL: TAK/NIE

ALERTY:
- CRITICAL: _______
- ALERT: _______
- WARNING: _______

ZASOBY:
- RAM start: _______ MB
- RAM koniec: _______ MB
- RAM delta: _______ MB
- Peak RAM: _______ MB

NAUKA:
- Węzły start: _______
- Węzły koniec: _______
- Węzły delta: +_______
- Epizody start: _______
- Epizody koniec: _______

PROBLEMY NAPOTKANE:
1. _________________________________
2. _________________________________
3. _________________________________

WNIOSKI:
_________________________________
_________________________________
_________________________________

OCENA STABILNOŚCI: ___/10
```

---

## 8. Troubleshooting

### Problem: System nie odpowiada

```bash
# W nowym terminalu
tasklist | findstr python
# Jeśli wisi, zabij proces
taskkill /F /IM python.exe
```

### Problem: Ollama nie odpowiada

```bash
ollama ps
# Jeśli nic nie pokazuje:
ollama run llama3.1:8b
```

### Problem: RAM > 90%

1. Sprawdź `/homeostasis` - powinien być w `REDUCED` lub `SURVIVAL`
2. Jeśli nie reaguje automatycznie:
   ```
   /stop           # Zatrzymaj agenta
   ```
3. Poczekaj na zwolnienie RAM
4. Uruchom ponownie `/start`

### Problem: Błędy w konsoli

1. Zapisz pełny tekst błędu
2. Sprawdź `/homeostasis events 10`
3. Kontynuuj test jeśli system działa
4. Zanotuj godzinę i okoliczności

---

## 9. Komendy - ściągawka

| Komenda | Co robi |
|---------|---------|
| `/help` | Pomoc |
| `/status` | Status Marii |
| `/homeostasis` | Status homeostazy |
| `/homeostasis start` | Uruchom monitoring |
| `/homeostasis stop` | Zatrzymaj monitoring |
| `/homeostasis events N` | Ostatnie N zdarzeń |
| `/homeostasis summary` | Podsumowanie sesji |
| `/start` | Uruchom agenta w tle |
| `/stop` | Zatrzymaj agenta |
| `/nodes` | Węzły w grafie |
| `/episodes` | Ostatnie epizody |
| `/save` | Zapisz graf |
| `/learn` | Uruchom uczenie |
| `/report` | Raport z nauki |
| `/exit` | Wyjdź |

---

## 10. Checklist przed startem

- [ ] Python działa
- [ ] Ollama działa i ma model llama3.1:8b
- [ ] Testy przechodzą (216 passed)
- [ ] Pliki w `input/` są gotowe
- [ ] Mam gdzie zapisywać notatki (ten plik lub osobny)
- [ ] Komputer będzie włączony przez 36h
- [ ] Mam ustawione przypomnienia na checkpointy
- [ ] Zrobiłem backup starych danych

---

*Powodzenia w teście! 🚀*
