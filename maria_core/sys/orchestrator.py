"""
DEAMONMARIA V2 - Orchestrator Example
Przykładowy skrypt pokazujący jak zintegrować wszystkie moduły.
To NIE zastępuje maria_daemon.py - to tylko przykład użycia.
"""

import logging
import time
import re
from pathlib import Path
# ====== FILTR LOGÓW: USUŃ TYLKO EMOJI (zachowaj polskie znaki) ======
# BUG-006 FIX: Poprzedni pattern [^\x00-\x7F]+ usuwał WSZYSTKIE znaki non-ASCII,
# w tym polskie litery (ą,ę,ó,ś,ż...). Nowy pattern usuwa tylko emoji.

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed characters
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "]+",
    flags=re.UNICODE
)

class StripEmojiFilter(logging.Filter):
    """Filtr, który czyści logi z emoji (ale zachowuje polskie znaki!).
       Dzięki temu Windows (cp1252) nie wywala UnicodeEncodeError.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            clean = EMOJI_PATTERN.sub("", msg)
            # podmieniamy tylko, jeśli coś zmieniło:
            if clean != msg:
                record.msg = clean
                record.args = ()
        except Exception:
            # w razie czego – lepiej zalogować coś niż nic
            record.msg = "LOG ERROR (strip_emoji)"
            record.args = ()
        return True

# Importuj wszystkie moduły
from maria_core.sys.config import (
    INPUT_DIR,
    KNOWLEDGE_INDEX,
    LONGTERM_MEMORY,
    EXAM_RESULTS,
    LEARNING_LOG,
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
)
from maria_core.perception.perception import scan_input_directory, get_next_file_to_learn
from maria_core.learning.priority_scheduler import update_priorities, reprocess_hard_topics
from maria_core.learning.learning_agent import learn_next_chunk
from maria_core.learning.exam_agent import run_exam_if_ready
from maria_core.memory_engine.memory_store import load_index

# Setup logging
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.FileHandler(LEARNING_LOG),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Dodajemy filtr usuwający emoji do wszystkich handlerów
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    handler.addFilter(StripEmojiFilter())

logger = logging.getLogger(__name__)


def maria_learning_cycle(
    max_iterations: int = 50,
    learn_steps_per_exam: int = 5,
    use_ollama_priority: bool = False
):
    """
    Główny cykl uczenia MARIA.

    Args:
        max_iterations: Maksymalna liczba iteracji (zabezpieczenie)
        learn_steps_per_exam: Co ile kroków nauki uruchomić egzamin
        use_ollama_priority: Czy użyć Ollama do priorytetyzacji (wolniejsze)
    """
    logger.info("="*60)
    logger.info("[START] DEAMONMARIA V2 - START LEARNING CYCLE")
    logger.info("="*60)

    iteration = 0
    learn_counter = 0

    while iteration < max_iterations:
        iteration += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"[ITER] ITERACJA {iteration}/{max_iterations}")
        logger.info(f"{'='*60}")

        # ===== KROK 1: SKANOWANIE =====
        logger.info("\n[1/5] [SCAN] Skanowanie katalogow...")
        stats = scan_input_directory(INPUT_DIR, KNOWLEDGE_INDEX)

        if stats['new'] > 0 or stats['changed'] > 0:
            logger.info(f"Znaleziono: {stats['new']} nowych, {stats['changed']} zmienionych")

        # ===== KROK 2: PRIORYTETYZACJA =====
        logger.info("\n[2/5] [PRIORITY] Aktualizacja priorytetow...")
        updated = update_priorities(KNOWLEDGE_INDEX, INPUT_DIR, use_ollama=use_ollama_priority)

        # ===== KROK 3: NAUKA =====
        logger.info("\n[3/5] [BRAIN] Uczenie sie...")
        learned_something = learn_next_chunk(INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY)

        if learned_something:
            learn_counter += 1
            logger.info(f"[OK] Nauczono chunk (licznik: {learn_counter})")
        else:
            logger.info("[INFO] Brak chunkow do nauki")

        # ===== KROK 4: EGZAMINY =====
        # Uruchamiaj egzamin co N krokow nauki lub jesli nie ma juz czego uczyc
        if learn_counter >= learn_steps_per_exam or not learned_something:
            logger.info("\n[4/5] [EXAM] Sprawdzam egzaminy...")
            exam_result = run_exam_if_ready(KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS)
            exam_done = exam_result.get("executed", False) if isinstance(exam_result, dict) else bool(exam_result)

            if exam_done:
                learn_counter = 0  # resetuj licznik
                logger.info("[OK] Przeprowadzono egzamin")
            else:
                logger.info("[INFO] Brak plikow gotowych na egzamin")
        else:
            logger.info("\n[4/5] [EXAM] Pomijam egzaminy (za malo nauki)")

        # ===== KROK 5: HARD TOPICS =====
        logger.info("\n[5/5] [RETRY] Sprawdzam hard topics...")
        restored = reprocess_hard_topics(KNOWLEDGE_INDEX, files_since_hard=5)

        # ===== SPRAWDZ CZY JEST JESZCZE PRACA =====
        index = load_index(KNOWLEDGE_INDEX)

        new_count = sum(1 for r in index if r['status'] == 'new')
        learning_count = sum(1 for r in index if r['status'] == 'learning')
        learned_count = sum(1 for r in index if r['status'] == 'learned')
        completed_count = sum(1 for r in index if r['status'] == 'completed')
        hard_count = sum(1 for r in index if r['status'] == 'hard_topic')

        logger.info(f"\n[STATUS] STATUS OGOLNY:")
        logger.info(f"   New: {new_count}")
        logger.info(f"   Learning: {learning_count}")
        logger.info(f"   Learned: {learned_count}")
        logger.info(f"   Completed: {completed_count}")
        logger.info(f"   Hard Topics: {hard_count}")

        # Jesli nie ma nic do roboty, zakoncz
        if new_count == 0 and learning_count == 0 and learned_count == 0:
            if hard_count > 0:
                logger.info("\n[WARN] Wszystkie pliki to hard topics - koncze cykl")
            else:
                logger.info("\n[OK] Wszystkie pliki ukonczone!")
            break

        # Krotka pauza miedzy iteracjami (opcjonalne)
        # time.sleep(1)

    logger.info("\n" + "="*60)
    logger.info("[END] DEAMONMARIA V2 - KONIEC CYKLU")
    logger.info("="*60)


def run_single_step(step: str):
    """
    Uruchamia pojedynczy krok (do debugowania).

    Args:
        step: 'scan' | 'priority' | 'learn' | 'exam' | 'hard_topics'
    """
    if step == 'scan':
        scan_input_directory(INPUT_DIR, KNOWLEDGE_INDEX)
    elif step == 'priority':
        update_priorities(KNOWLEDGE_INDEX, INPUT_DIR, use_ollama=True)
    elif step == 'learn':
        learn_next_chunk(INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY)
    elif step == 'exam':
        run_exam_if_ready(KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS)
    elif step == 'hard_topics':
        reprocess_hard_topics(KNOWLEDGE_INDEX)
    else:
        logger.error(f"Nieznany krok: {step}")


def main():
    """Główny punkt wejścia dla run_maria.py"""
    maria_learning_cycle(
        max_iterations=0,
        learn_steps_per_exam=3,
        use_ollama_priority=False  # False = szybsze, True = dokładniejsze
    )


if __name__ == "__main__":
    # Jeśli odpalasz plik bezpośrednio: python maria_core/orchestrator.py
    main()
    # albo możesz tu zostawić alternatywnie:
    # run_single_step('scan')
    # run_single_step('learn')
    # itd.

