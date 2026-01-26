"""
DEAMONMARIA V2 - Configuration Module
Centralna konfiguracja wszystkich parametrów systemu.
"""

from pathlib import Path
import sys
import os

# Windows console UTF-8 fix
if sys.platform == 'win32':
    # Force UTF-8 output on Windows
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    # Set environment variable for subprocess
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# ========== ŚCIEŻKI ==========

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
PROCESSED_DIR = BASE_DIR / "processed"
MEMORY_DIR = BASE_DIR / "memory"
LOGS_DIR = BASE_DIR / "logs"

# Pliki pamięci (JSONL)
KNOWLEDGE_INDEX = MEMORY_DIR / "knowledge_index.jsonl"
LONGTERM_MEMORY = MEMORY_DIR / "maria_longterm_memory.jsonl"
EXAM_RESULTS = MEMORY_DIR / "exam_results.jsonl"

# Pliki logów
LEARNING_LOG = LOGS_DIR / "learning.log"
EXAM_LOG = LOGS_DIR / "exams.log"


def ensure_directories():
    """Tworzy katalogi jeśli nie istnieją."""
    for directory in [INPUT_DIR, PROCESSED_DIR, MEMORY_DIR, LOGS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


ensure_directories()


# ========== OLLAMA ==========

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TEMPERATURE = 0.3
OLLAMA_TIMEOUT = 240  # sekundy
OLLAMA_MAX_RETRIES = 3

# Backward compatibility for older modułów
OLLAMA_HOST = OLLAMA_BASE_URL
MAX_RETRIES_OLLAMA = OLLAMA_MAX_RETRIES



# ========== CHUNKING (REDUCED FOR WINDOWS) ==========

TARGET_CHUNK_SIZE = 1200  # znaków (ZMNIEJSZONE z 1500 dla Windows MemoryError)
MIN_CHUNK_SIZE = 600      # minimum dla chunka
MAX_CHUNK_SIZE = 2000     # maksimum dla chunka (ZMNIEJSZONE z 2500)
CHUNK_OVERLAP = 150       # ile znaków nakłada się między chunkami


# ========== EGZAMINY ==========

EXAM_PASS_THRESHOLD = 0.6           # 60% do zaliczenia
EXAM_MAX_ATTEMPTS = 2               # po 2 nieudanych -> hard_topic
EXAM_QUESTIONS_PER_CHUNK = 1.5      # ile pytań na chunk (float OK)
EXAM_MIN_QUESTIONS = 4              # minimum pytań
EXAM_MAX_QUESTIONS = 12             # maksimum pytań


# ========== STATUSY ==========

STATUS_NEW = "new"
STATUS_LEARNING = "learning"
STATUS_LEARNED = "learned"
STATUS_EXAM_FAILED = "exam_failed"
STATUS_HARD_TOPIC = "hard_topic"
STATUS_COMPLETED = "completed"


# ========== PRIORYTETY ==========

# Bonusy priorytetowe za słowa kluczowe w nazwie pliku
PRIORITY_BONUS_KEYWORDS = {
    "core": 15,
    "podstawy": 12,
    "foundation": 12,
    "intro": 10,
    "beginning": 10,
    "essential": 10,
    "important": 8,
    "critical": 8,
    "key": 6,
    "advanced": -5,  # ujemny = niższy priorytet
    "optional": -8,
}

# Priorytety hard topics
HARD_TOPIC_PRIORITY_PENALTY = 30   # o ile obniżyć priorytet
HARD_TOPIC_RETRY_AFTER = 5         # po ilu completed plików wrócić


# ========== LOGGING ==========

LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ========== HELPERS ==========

def get_timestamp():
    """Zwraca timestamp w formacie ISO 8601."""
    from datetime import datetime
    return datetime.utcnow().isoformat() + "Z"


# ========== CHUNKING SEPARATORY ==========

# Separatory używane w intelligent chunking (kolejność ważna!)
CHUNK_SEPARATORS = [
    "\n\n\n",  # sekcje
    "\n\n",    # paragrafy
    "\n",       # linie
    ". ",        # zdania
    " ",         # słowa
]
