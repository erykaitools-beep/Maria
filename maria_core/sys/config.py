"""
DEAMONMARIA V2 - Configuration Module
Centralna konfiguracja wszystkich parametrów systemu.
"""

from pathlib import Path
import sys
import os

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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

BASE_DIR = Path(__file__).resolve().parents[2]  # Główny folder projektu (nie maria_core/)
INPUT_DIR = BASE_DIR / "input"
PROCESSED_DIR = BASE_DIR / "processed"
MEMORY_DIR = BASE_DIR / "memory"
LOGS_DIR = BASE_DIR / "logs"

# Pliki pamięci (JSONL)
KNOWLEDGE_INDEX = MEMORY_DIR / "knowledge_index.jsonl"
LONGTERM_MEMORY = MEMORY_DIR / "maria_longterm_memory.jsonl"
EXAM_RESULTS = MEMORY_DIR / "exam_results.jsonl"
HELDOUT_BANK = MEMORY_DIR / "heldout_bank.jsonl"

# Pliki logów
LEARNING_LOG = LOGS_DIR / "learning.log"
EXAM_LOG = LOGS_DIR / "exams.log"

# Sandbox (ADR-010: Sandbox-first learning)
SANDBOX_DIR = BASE_DIR / "meta_data" / "sandbox"


def ensure_directories():
    """Tworzy katalogi jeśli nie istnieją."""
    for directory in [INPUT_DIR, PROCESSED_DIR, MEMORY_DIR, LOGS_DIR, SANDBOX_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


ensure_directories()


# ========== OLLAMA ==========

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TEMPERATURE = 0.3
OLLAMA_TIMEOUT = 240  # sekundy
OLLAMA_MAX_RETRIES = 3
# Pin the model loaded between learning cycles so back-to-back exam/learn
# sessions don't pay a cold-start reload. Without this, Ollama's 5-min default
# keep_alive unloaded llama3.1 between cycles (which are often >5 min apart) ->
# each exam cold-started on CPU and hit the 240s x3 timeout (12 min) -> exam
# pipeline failures + the CPU saturation that fed the 2026-06-02 freeze.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

# HTTP read-timeout (seconds) for the ollama.Client used by OllamaBrain
# (chat / _ask_once). Root-cause backstop for the 2026-06-02 tick-loop freeze:
# the module-level ollama.chat() carries NO socket timeout, so a stalled
# inference hung forever. That orphaned the router's bounded call
# (call_with_timeout unblocks the caller but cannot cancel the HTTP request),
# starved the 2-worker timeout pool, and froze the whole tick loop for 10.5h.
# A real httpx timeout tears the socket down so the zombie call dies and frees
# its pool slot. Sized ABOVE the per-role execution-budget timeouts
# (executor 120s / planner 180s) so graceful degrade fires first, and BELOW the
# 300s homeostasis watchdog so this degrades before a hard restart. Mirrors the
# legacy learning path's requests timeout (OLLAMA_TIMEOUT=240) for one Ollama
# server with one cold-start latency class.
OLLAMA_HTTP_TIMEOUT = int(os.environ.get("OLLAMA_HTTP_TIMEOUT", "240"))

# Chat-specific read-timeout (seconds) for the UI chat brain. OLLAMA_HTTP_TIMEOUT
# (240s) is sized for the learning/exam path where a cold model legitimately needs
# ~240s; for interactive chat that is far too long -- the operator stares at a dead
# chat for 4 minutes before any feedback (observed live 2026-06-08 ~17:55). A warm
# llama3.1:8b answers a chat turn in seconds on CPU, so a 75s ceiling deliberately
# trades the rare cold-start (which would just be retried) for FAST feedback: on a
# stall the UI surfaces a graceful "busy thinking" message instead of silence.
# Separate env (CHAT_TIMEOUT) so chat can fail fast without shortening the shared
# learning timeout. Falls back to OLLAMA_HTTP_TIMEOUT semantics if set very high.
CHAT_HTTP_TIMEOUT = int(os.environ.get("CHAT_TIMEOUT", "75"))

# Backward compatibility for older modułów
OLLAMA_HOST = OLLAMA_BASE_URL
MAX_RETRIES_OLLAMA = OLLAMA_MAX_RETRIES


# ========== NVIDIA NIM ==========

NVIDIA_NIM_API_KEY = os.environ.get("NVIDIA_NIM_API_KEY", "")
NVIDIA_NIM_BASE_URL = os.environ.get(
    "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"
)
# Single source of truth for the NIM model fallback default. The LIVE model is
# selected via .env NVIDIA_NIM_MODEL (read by teacher_module + self_model_facade
# at construction); this constant is the consistent fallback when that env var is
# unset. model_registry / external_analyzer / self_model_facade / nim_client all
# import it, so a model switch is a one-line change here instead of N scattered
# strings drifting onto dead models. 2026-06-08: dracarys-llama-3.1-70b
# (nemotron-super-49b-v1.5 degraded server-side, 70b-nemotron decommissioned 404).
DEFAULT_NIM_MODEL = "abacusai/dracarys-llama-3.1-70b-instruct"
NVIDIA_NIM_MODEL = os.environ.get("NVIDIA_NIM_MODEL", DEFAULT_NIM_MODEL)
NIM_DAILY_TOKEN_LIMIT = int(os.environ.get("NIM_DAILY_TOKEN_LIMIT", "100000"))
NIM_MONTHLY_TOKEN_LIMIT = int(os.environ.get("NIM_MONTHLY_TOKEN_LIMIT", "2000000"))



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
# Cap obnizony 12 -> 6 (2026-06-05): regularny (LLM-graded) egzamin robi 2 calle
# na CPU bez GPU -- student answer (llama3.1) + grade (qwen3, gadatliwy). Przy 12
# pytaniach kazdy z nich regularnie przebijal OLLAMA_TIMEOUT=240s, co dawalo
# chroniczny 0% exam-success / action_failure_storm (codziennie 06-01..06-05).
# 6 pytan = ~polowa tokenow answer+grade => oba mieszcza sie pod 240s. Dotyczy
# TYLKO regularnego generate path (calculate_num_questions); held-out uzywa banku.
EXAM_MAX_QUESTIONS = 6             # maksimum pytań (CPU-bound timeout, patrz wyzej)

# Twardy budzet (call_with_timeout) na odpowiedz studenta -- jedyny krok egzaminu
# wciaz na lokalnym CPU po przeniesieniu generate+grade na NIM (2026-06-06).
# call_ollama sam retry'uje MAX_RETRIES x HTTP-timeout -- zawieszony llama dawal
# 841s "zombie" karmiacy action_failure_storm. call_with_timeout(EXAM_ANSWER_
# TIMEOUT_SEC) ucina to jednym deadlinem (gorna granica nad HTTP-timeoutem ponizej).
EXAM_ANSWER_TIMEOUT_SEC = 300       # sekundy (twardy budzet na student answer)

# HTTP read-timeout pojedynczego calla student-answer. Wyzszy niz OLLAMA_TIMEOUT
# (240s) jako margines: na CPU bez GPU prompt-eval jest WOLNY (~17 tok/s zmierzone
# 2026-06-06), wiec concise answer (cap 6000 + zwiezle) trwa ~207s -- pod 240, ale
# 290 chroni przed wariancja/contentionem demona (legalna odpowiedz w JEDNEJ
# probie zamiast retry->storm). Wciaz < EXAM_ANSWER_TIMEOUT_SEC (300) = budzet calosci.
EXAM_ANSWER_HTTP_TIMEOUT_SEC = 290  # sekundy (HTTP read-timeout student answer)

# Cap na rozmiar kontekstu egzaminu (open-book). Egzamin wrzuca CALY material
# pliku do promptu studenta; duze pliki (40% ma >10k znakow, max 117k =
# expert_logika_formalna, 100 chunkow) dawaly prompt 5k+ tokenow, ktorego
# prompt-eval na CPU (bez GPU, ~17 tok/s) przebijal kazdy sensowny timeout --
# DRUGI root storma. Pomiar 2026-06-06: answer = prompt-eval(INPUT) + eval(OUTPUT),
# OBA drogie (cap 8000+verbose: 178s+180s=381s). Fix dwustronny: cap INPUT tu +
# concise OUTPUT (answer_exam concise=True w _execute_exam) -> answer ~207s.
# Cap rownomiernie probkuje chunki (reprezentatywne pokrycie calego pliku, nie
# sam poczatek), spojnie dla generate+answer.
EXAM_CONTEXT_MAX_CHARS = 6000       # znaki (cap kontekstu open-book egzaminu)


# ========== STATUSY ==========

STATUS_NEW = "new"
STATUS_LEARNING = "learning"
STATUS_LEARNED = "learned"
STATUS_EXAM_FAILED = "exam_failed"
STATUS_HARD_TOPIC = "hard_topic"
STATUS_COMPLETED = "completed"
# P5 (#4): a file whose content body is identical to one already indexed under
# another id. Inert -- never selected for learning (not in the learnable set),
# so identical content fetched under a different name is not re-learned.
STATUS_DUPLICATE = "duplicate"


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
