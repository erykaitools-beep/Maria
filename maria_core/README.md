# 🧠 DEAMONMARIA V2

**Autonomiczny system uczący się z lokalnych plików tekstowych przez Ollama.**

---

## 📋 WYMAGANIA

### 1. Python 3.8+
```bash
python --version  # sprawdź wersję
```

### 2. Ollama
Zainstaluj Ollama z: https://ollama.ai/

Pobierz model `llama3.1:8b`:
```bash
ollama pull llama3.1:8b
```

Sprawdź czy działa:
```bash
ollama list
ollama run llama3.1:8b "Hello!"
```

### 3. Zależności Python
```bash
pip install -r requirements.txt
```

---

## 🚀 SZYBKI START

### 1. Struktura projektu
```
maria_core/
├── config.py              # ✅ Konfiguracja
├── memory_store.py        # ✅ Pamięć (JSONL)
├── perception.py          # ✅ Skanowanie folderów
├── priority_scheduler.py  # ✅ Priorytetyzacja
├── learning_agent.py      # ✅ Uczenie przez Ollama
├── exam_agent.py          # ✅ Egzaminy
├── orchestrator.py        # ✅ Przykładowa integracja
│
├── input/                 # 👈 WRZUĆ TU PLIKI .txt
│   ├── pakiet_01/
│   │   ├── A1.txt
│   │   └── A2.txt
│   └── pakiet_02/
│       └── B1.txt
│
├── memory/                # Pamięć długoterminowa (auto)
├── processed/             # Przetworzone pliki (auto)
└── logs/                  # Logi (auto)
```

### 2. Dodaj materiały do nauki
```bash
mkdir -p input/pamiec_techniki
# Wrzuć pliki .txt do input/pamiec_techniki/
```

### 3. Uruchom system
```bash
python orchestrator.py
```

---

## ⚙️ KONFIGURACJA

### `config.py` - główne ustawienia:

```python
# Model Ollama
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TEMPERATURE = 0.3

# Chunking
TARGET_CHUNK_SIZE = 1500  # znaków
CHUNK_OVERLAP = 200

# Egzaminy
EXAM_PASS_THRESHOLD = 0.6  # 60%
EXAM_MAX_ATTEMPTS = 2

# Słowa kluczowe (bonusy do priorytetu)
PRIORITY_BONUS_KEYWORDS = {
    "core": 15,
    "podstawy": 12,
    # ... dodaj własne
}
```

---

## 🔄 JAK TO DZIAŁA?

### Cykl uczenia:

```
1. 🔍 SKANOWANIE
   ↓ Znajdź pliki .txt w input/

2. 🎯 PRIORYTETYZACJA
   ↓ Oceń ważność (rozmiar, struktura, słowa kluczowe)

3. 🧠 NAUKA
   ↓ Podziel na chunki, ucz się przez Ollama
   ↓ Zapisz do pamięci długoterminowej

4. 📝 EGZAMIN
   ↓ Wygeneruj pytania → odpowiedz → oceń

5. ✅ WYNIK
   ├─ score >= 60% → COMPLETED ✅
   ├─ score < 60% (1x) → EXAM_FAILED (ponowna nauka)
   └─ score < 60% (2x) → HARD_TOPIC ⚠️ (pomiń, wróć później)
```

### Statusy plików:
- `new` - nowy, nierozpoczęty
- `learning` - w trakcie nauki (chunki)
- `learned` - nauczony, czeka na egzamin
- `exam_failed` - egzamin niezaliczony, ponowna nauka
- `hard_topic` - trudny temat, pominięty (powrót po 5 innych)
- `completed` - egzamin zaliczony ✅

---

## 📊 PLIKI PAMIĘCI (JSONL)

### `memory/knowledge_index.jsonl`
Indeks wszystkich plików:
```json
{
  "id": "pakiet_01/A1.txt",
  "status": "learning",
  "priority": 75.3,
  "exam_attempts": 0,
  "chunks_learned": 3,
  "total_chunks": 5
}
```

### `memory/maria_longterm_memory.jsonl`
Pamięć długoterminowa (chunki):
```json
{
  "source_file": "pakiet_01/A1.txt",
  "chunk_id": "pakiet_01/A1.txt#chunk_0",
  "summary": "...",
  "key_points": ["...", "..."],
  "tags": ["...", "..."]
}
```

### `memory/exam_results.jsonl`
Wyniki egzaminów:
```json
{
  "file": "pakiet_01/A1.txt",
  "attempt": 1,
  "score": 0.75,
  "questions": [...],
  "answers": [...]
}
```

---

## 🔧 INTEGRACJA Z `maria_daemon.py`

**Nie ruszaj swojego `maria_daemon.py`!**

W głównej pętli `maria_think_loop()` dodaj:

```python
from perception import scan_input_directory
from priority_scheduler import update_priorities
from maria.core.learning.learning_agent import learn_next_chunk
from exam_agent import run_exam_if_ready
from config import INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS

def maria_think_loop():
    while True:
        # 1. Skanuj nowe pliki
        scan_input_directory(INPUT_DIR, KNOWLEDGE_INDEX)

        # 2. Zaktualizuj priorytety (opcjonalne)
        # update_priorities(KNOWLEDGE_INDEX, use_ollama=False)

        # 3. Ucz się jednego chunka
        learned = learn_next_chunk(INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY)

        # 4. Co 3 chunki - egzamin
        if iteration % 3 == 0:
            run_exam_if_ready(KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS)

        # 5. TWÓJ ISTNIEJĄCY KOD
        # ... twoja logika maria_daemon.py

        time.sleep(5)
```

---

## 🐛 DEBUGOWANIE

### Pojedyncze kroki:
```python
from orchestrator import run_single_step

run_single_step('scan')      # tylko skanowanie
run_single_step('learn')     # tylko nauka
run_single_step('exam')      # tylko egzamin
run_single_step('priority')  # tylko priorytetyzacja
```

### Logi:
```bash
tail -f logs/learning.log
tail -f logs/exams.log
```

---

## 🎯 PRZYKŁADOWE UŻYCIE

```python
from orchestrator import maria_learning_cycle

# Tryb pełny: max 50 iteracji, egzamin co 3 chunki
maria_learning_cycle(
    max_iterations=50,
    learn_steps_per_exam=3,
    use_ollama_priority=False  # False=szybkie, True=dokładne
)
```

---

## 🛡️ BEZPIECZEŃSTWO

- **Thread-safe**: File locking w `memory_store.py`
- **Atomiczne zapisy**: Temp file → replace
- **Retry logic**: 3 próby dla Ollama API
- **Timeout**: 120s na wywołanie Ollama
- **Validation**: JSON parsing z error handling

---

## 📈 OPTYMALIZACJA

### Szybszy chunking:
```python
# config.py
TARGET_CHUNK_SIZE = 1000  # mniejsze chunki
```

### Mniej pytań na egzamin:
```python
# config.py
EXAM_QUESTIONS_PER_CHUNK = 1.0  # zamiast 1.5
```

### Priorytety przez Ollama (wolniejsze, ale dokładniejsze):
```python
update_priorities(KNOWLEDGE_INDEX, use_ollama=True)
```

---

## ❓ FAQ

**Q: System się zapętla na jednym pliku?**
A: Automatyczne wykrywanie w `exam_agent.py` - po 3 podobnych wynikach → HARD_TOPIC

**Q: Jak wrócić do hard topics?**
A: Automatycznie po nauczeniu 5 innych plików (zmień w `config.py: HARD_TOPIC_RETRY_AFTER`)

**Q: Ollama timeout?**
A: Zwiększ `OLLAMA_TIMEOUT` w `config.py` (domyślnie 120s)

**Q: Plik się zmienił?**
A: System wykrywa zmiany przez SHA256 hash i resetuje status na `new`

---

## 📝 TODO (opcjonalne rozszerzenia)

- [ ] Dependency graph (plik B wymaga wiedzy z A)
- [ ] Semantic search w pamięci (embeddings)
- [ ] Export do Anki (flashcards)
- [ ] Web dashboard (Flask)
- [ ] Multi-model support (różne modele Ollama)

---

## 📄 LICENCJA

 🚀

---

## 👨‍💻 AUTOR

DEAMONMARIA V2 
