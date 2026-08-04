# DEAMONMARIA V2

**Autonomous system that learns from local text files via Ollama.**

> **[HISTORICAL — legacy layer]** `maria_core/` is the original learning pipeline
> that predates the current `agent_core/` architecture. This document describes
> that early design and is kept for historical reference only. It does **not**
> match the current code: `orchestrator.py` and `maria_daemon.py` no longer exist
> (so the `python orchestrator.py` and `maria_think_loop()` examples below will
> not run), the modules have since moved into subpackages (`sys/`,
> `memory_engine/`, `perception/`, `learning/`), and several defaults quoted here
> differ from `maria_core/sys/config.py`. To actually run Maria, start from
> [QUICKSTART.md](../QUICKSTART.md).

---

## REQUIREMENTS

### 1. Python 3.8+
```bash
python --version  # check version
```

### 2. Ollama
Install Ollama from: https://ollama.ai/

Pull the `llama3.1:8b` model:
```bash
ollama pull llama3.1:8b
```

Check that it works:
```bash
ollama list
ollama run llama3.1:8b "Hello!"
```

### 3. Python dependencies
```bash
pip install -r requirements.txt
```

---

## QUICK START

### 1. Project structure
```
maria_core/
├── config.py              # Configuration
├── memory_store.py        # Memory (JSONL)
├── perception.py          # Directory scanning
├── priority_scheduler.py  # Prioritization
├── learning_agent.py      # Learning via Ollama
├── exam_agent.py          # Exams
├── orchestrator.py        # Example integration
│
├── input/                 # PUT .txt FILES HERE
│   ├── pakiet_01/
│   │   ├── A1.txt
│   │   └── A2.txt
│   └── pakiet_02/
│       └── B1.txt
│
├── memory/                # Long-term memory (auto)
├── processed/             # Processed files (auto)
└── logs/                  # Logs (auto)
```

### 2. Add learning material
```bash
mkdir -p input/pamiec_techniki
# Drop .txt files into input/pamiec_techniki/
```

### 3. Run the system
```bash
python orchestrator.py
```

---

## CONFIGURATION

### `config.py` - main settings:

```python
# Ollama model
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TEMPERATURE = 0.3

# Chunking
TARGET_CHUNK_SIZE = 1500  # characters
CHUNK_OVERLAP = 200

# Exams
EXAM_PASS_THRESHOLD = 0.6  # 60%
EXAM_MAX_ATTEMPTS = 2

# Keywords (priority bonuses)
PRIORITY_BONUS_KEYWORDS = {
    "core": 15,
    "podstawy": 12,
    # ... add your own
}
```

---

## HOW DOES IT WORK?

### Learning cycle:

```
1. SCAN
   ↓ Find .txt files in input/

2. PRIORITIZE
   ↓ Score importance (size, structure, keywords)

3. LEARN
   ↓ Split into chunks, learn via Ollama
   ↓ Write to long-term memory

4. EXAM
   ↓ Generate questions → answer → grade

5. RESULT
   ├─ score >= 60% → COMPLETED
   ├─ score < 60% (1x) → EXAM_FAILED (relearn)
   └─ score < 60% (2x) → HARD_TOPIC (skip, return later)
```

### File statuses:
- `new` - new, not started
- `learning` - learning in progress (chunks)
- `learned` - learned, waiting for the exam
- `exam_failed` - exam not passed, relearn
- `hard_topic` - hard topic, skipped (return after 5 other files)
- `completed` - exam passed

---

## MEMORY FILES (JSONL)

### `memory/knowledge_index.jsonl`
Index of all files:
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
Long-term memory (chunks):
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
Exam results:
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

## INTEGRATION WITH `maria_daemon.py`

**Do not touch your own `maria_daemon.py`!**

In the main `maria_think_loop()` loop, add:

```python
from perception import scan_input_directory
from priority_scheduler import update_priorities
from maria.core.learning.learning_agent import learn_next_chunk
from exam_agent import run_exam_if_ready
from config import INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS

def maria_think_loop():
    while True:
        # 1. Scan for new files
        scan_input_directory(INPUT_DIR, KNOWLEDGE_INDEX)

        # 2. Refresh priorities (optional)
        # update_priorities(KNOWLEDGE_INDEX, use_ollama=False)

        # 3. Learn a single chunk
        learned = learn_next_chunk(INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY)

        # 4. Every 3 chunks - exam
        if iteration % 3 == 0:
            run_exam_if_ready(KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS)

        # 5. YOUR EXISTING CODE
        # ... your maria_daemon.py logic

        time.sleep(5)
```

---

## DEBUGGING

### Single steps:
```python
from orchestrator import run_single_step

run_single_step('scan')      # scan only
run_single_step('learn')     # learning only
run_single_step('exam')      # exam only
run_single_step('priority')  # prioritization only
```

### Logs:
```bash
tail -f logs/learning.log
tail -f logs/exams.log
```

---

## EXAMPLE USAGE

```python
from orchestrator import maria_learning_cycle

# Full mode: max 50 iterations, exam every 3 chunks
maria_learning_cycle(
    max_iterations=50,
    learn_steps_per_exam=3,
    use_ollama_priority=False  # False=fast, True=accurate
)
```

---

## SAFETY

- **Thread-safe**: file locking in `memory_store.py`
- **Atomic writes**: temp file → replace
- **Retry logic**: 3 attempts for the Ollama API
- **Timeout**: 120s per Ollama call
- **Validation**: JSON parsing with error handling

---

## OPTIMIZATION

### Faster chunking:
```python
# config.py
TARGET_CHUNK_SIZE = 1000  # smaller chunks
```

### Fewer exam questions:
```python
# config.py
EXAM_QUESTIONS_PER_CHUNK = 1.0  # instead of 1.5
```

### Priorities via Ollama (slower, but more accurate):
```python
update_priorities(KNOWLEDGE_INDEX, use_ollama=True)
```

---

## FAQ

**Q: The system loops on a single file?**
A: Detected automatically in `exam_agent.py` - after 3 similar scores → HARD_TOPIC

**Q: How do hard topics come back?**
A: Automatically after 5 other files have been learned (change in `config.py: HARD_TOPIC_RETRY_AFTER`)

**Q: Ollama timeout?**
A: Increase `OLLAMA_TIMEOUT` in `config.py` (120s by default)

**Q: A file changed?**
A: The system detects changes through a SHA256 hash and resets the status to `new`

---

## TODO (optional extensions)

- [ ] Dependency graph (file B requires knowledge from A)
- [ ] Semantic search over memory (embeddings)
- [ ] Export to Anki (flashcards)
- [ ] Web dashboard (Flask)
- [ ] Multi-model support (different Ollama models)

---

## LICENSE

Same as the rest of the project: AGPL-3.0. See [LICENSE](../LICENSE).

---

## AUTHOR

DEAMONMARIA V2
