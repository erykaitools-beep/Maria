# maria_core/meta/meta_config.py
from pathlib import Path
from enum import Enum

# ==== ŚCIEŻKI BAZOWE ====
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # projekt root
META_DIR = BASE_DIR / "meta_data"
META_DIR.mkdir(parents=True, exist_ok=True)

# ==== PLIKI META-STANU ====
META_STATE_FILE      = META_DIR / "meta_controller.json"
REWARDS_LOG          = META_DIR / "rewards_log.jsonl"
DECISIONS_LOG        = META_DIR / "decisions_log.jsonl"
TRAUMA_LOG           = META_DIR / "trauma_events.jsonl"
EMERGENCY_STOP_FILE  = META_DIR / "EMERGENCY_STOP"   # jak istnieje → natychmiastowa śmierć

# ==== TRYBY ISTNIENIA SYSTEMU ====
class Mode(str, Enum):
    LEARNING = "learning"
    TESTING  = "testing"
    RECOVERY = "recovery"
    SLEEP    = "sleep"       # "zmęczenie" / przerwa
    DEMO     = "demo"

# ==== GŁÓWNE CELE SYSTEMOWE ====
class Goal(str, Enum):
    EXPAND_VOCABULARY = "expand_technical_vocabulary"
    STABILIZE         = "stabilize_system"
    DEBUG             = "debug_crashes"
    OPTIMIZE          = "optimize_memory"
    PREPARE_DEMO      = "prepare_demo_mode"
    RECOVERY          = "emergency_recovery"

# ==== NAGRODY I KARY ====
REWARD_EXAM_PASSED      = 1.0
REWARD_MASTERY_95       = 2.0   # >95% na egzaminie
REWARD_CHUNK_LEARNED    = 0.5
REWARD_NEW_CONCEPT      = 0.3
REWARD_STABILITY_HOUR   = 0.2

PENALTY_EXAM_FAILED     = 1.0
PENALTY_LOOP_DETECTED   = 2.0
PENALTY_CRASH           = 5.0
PENALTY_MEMORY_ERROR    = 3.0
PENALTY_OLLAMA_TIMEOUT  = 1.5

# ==== PROGI I PARAMETRY DECYZYJNE ====
PENALTY_THRESHOLD_RECOVERY     = 6.0   # kiedy wchodzi w tryb RECOVERY
REWARD_THRESHOLD_EXIT_RECOVERY = 4.0   # kiedy może wyjść z RECOVERY
MOTIVATION_THRESHOLD_SLEEP     = -5.0  # kiedy iść spać (brak zadań / za dużo kar)

MIN_CONFIDENCE_TRUSTED   = 0.7
CRASH_STREAK_FOR_TRAUMA  = 3
