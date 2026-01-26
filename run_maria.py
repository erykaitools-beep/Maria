# run_maria.py
# Start architektury M.A.R.I.A. z:
# - META (maria_core/meta/meta_controller.py)
# - WATCHDOG RAM (maria_core/resource_watchdog.py)
# - orchestrator.maria_learning_cycle jako serce nauki

import os
import sys
import logging
from pathlib import Path

# === ŚCIEŻKI / PAKIET ===
BASE_DIR = Path(__file__).resolve().parent  # ...\Moja AI. Maria Ver.1

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.chdir(BASE_DIR)

# === IMPORTY Z RDZENIA ===
from maria_core.sys.orchestrator import maria_learning_cycle
from maria_core.sys.resource_watchdog import start_watchdog
from maria_core.meta.meta_controller import meta  # singleton META


# === LOGOWANIE PODSTAWOWE ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("RUN_MARIA")


def main():
    logger.info("[RUN_MARIA] Start architektury M.A.R.I.A. (META + WATCHDOG + ORCHESTRATOR)")

    # 1) Watchdog RAM – twardy bezpiecznik
    start_watchdog(limit_percent=90, check_interval_sec=3)

    # 2) META – status i decyzja, czy wolno się uczyć
    try:
        status = meta.get_status_summary()
        logger.info(status)
    except Exception as e:
        logger.warning(f"[RUN_MARIA] Nie udało się pobrać statusu META: {e}")

    try:
        if hasattr(meta, "is_learning_allowed") and not meta.is_learning_allowed():
            logger.warning("[RUN_MARIA] META: is_learning_allowed() = False → kończę proces bez nauki.")
            meta.log_decision("skip_learning_cycle", "meta blocked learning in current mode")
            return
    except Exception as e:
        logger.warning(f"[RUN_MARIA] Błąd w meta.is_learning_allowed(): {e}")

    # 3) Jedna bezpieczna sesja nauki
    logger.info("[RUN_MARIA] Uruchamiam maria_learning_cycle (konserwatywne parametry).")
    maria_learning_cycle(
        max_iterations=5,          # krótka, bezpieczna sesja
        learn_steps_per_exam=5,    # rzadziej egzaminy
        use_ollama_priority=False, # mniej obciążenia
    )

    # 4) Log decyzji do META (opcjonalna nagroda / informacja)
    try:
        meta.log_decision("learning_cycle_completed", "run_maria.py zakończył cykl bez crasha")
    except Exception as e:
        logger.warning(f"[RUN_MARIA] Nie udało się zalogować decyzji w META: {e}")

    logger.info("[RUN_MARIA] Koniec cyklu M.A.R.I.A.")


if __name__ == "__main__":
    main()
