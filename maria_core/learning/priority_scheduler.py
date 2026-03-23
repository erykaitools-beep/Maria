"""
DEAMONMARIA V2 - Priority Scheduler Module
Dopracowanie priorytetów na podstawie analizy treści przez Ollama.
Opcjonalne wywołanie modelu dla lepszej oceny ważności materiału.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from maria_core.sys.config import (
    INPUT_DIR,
    OLLAMA_MODEL,
    STATUS_NEW,
    STATUS_HARD_TOPIC,
    get_timestamp,
)
from maria_core.memory_engine.memory_store import load_index, save_index
from maria_core.learning.llm_utils import call_ollama, extract_json_from_response

logger = logging.getLogger(__name__)


PROMPT_ASSESS_IMPORTANCE = """Jesteś M.A.R.I.A. – lokalną inteligencją oceniającą ważność materiałów do nauki.

Przeczytaj początek dokumentu i oceń jego ważność dla osoby uczącej się efektywnego zarządzania pamięcią i skutecznego uczenia się.

Kryteria oceny:
- Czy to materiał fundamentalny/podstawowy? (core concepts)
- Czy zawiera praktyczne techniki i metody?
- Czy jest to teoria czy praktyka?
- Czy wymaga wcześniejszej wiedzy?

Fragment dokumentu:
--------------------
{preview}
--------------------

Odpowiedz w JSON (bez markdown):
{{
  "importance": 7,
  "reasoning": "krótkie wyjaśnienie w 1-2 zdaniach",
  "requires_prior": false,
  "is_foundational": true
}}

importance: skala 1-10 (1=mało ważne, 10=kluczowe)
requires_prior: czy wymaga wcześniejszej wiedzy
is_foundational: czy to materiał podstawowy"""


def assess_file_importance(filepath: Path, preview_chars: int = 1500) -> Optional[Dict[str, Any]]:
    """
    Ocenia ważność pliku przez Ollama na podstawie preview.

    Args:
        filepath: Ścieżka do pliku
        preview_chars: Ile znaków z początku pliku przeanalizować

    Returns:
        Słownik z oceną lub None
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            preview = f.read(preview_chars)
    except Exception as e:
        logger.error(f"Nie mogę odczytać {filepath}: {e}")
        return None

    prompt = PROMPT_ASSESS_IMPORTANCE.format(preview=preview)

    logger.debug(f"Oceniam ważność: {filepath.name}")

    response = call_ollama(prompt, temperature=0.3)
    if not response:
        return None

    parsed = extract_json_from_response(response)
    if not parsed or 'importance' not in parsed:
        logger.error("Brak pola 'importance' w odpowiedzi")
        return None

    return parsed


def recalculate_priority_with_ollama(record: Dict[str, Any], filepath: Path) -> float:
    """
    Przelicza priorytet z uwzględnieniem oceny Ollama.

    Args:
        record: Rekord z indeksu
        filepath: Ścieżka do pliku

    Returns:
        Nowy priorytet (0-100)
    """
    current_priority = record.get('priority', 50.0)

    # Oceń przez Ollama
    assessment = assess_file_importance(filepath)
    if not assessment:
        logger.warning(f"Nie udało się ocenić {record['id']}, zostawiam obecny priorytet")
        return current_priority

    importance = assessment.get('importance', 5)  # 1-10
    is_foundational = assessment.get('is_foundational', False)
    requires_prior = assessment.get('requires_prior', False)

    # Nowy priorytet
    new_priority = current_priority

    # Bonus za importance (max +30)
    importance_bonus = (importance - 5) * 6  # -24 do +30
    new_priority += importance_bonus

    # Bonus za foundational (+15)
    if is_foundational:
        new_priority += 15

    # Kara za requires_prior (-10)
    if requires_prior:
        new_priority -= 10

    # Ogranicz do 0-100
    new_priority = max(0, min(100, new_priority))

    logger.info(f"{record['id']}: importance={importance}/10, foundational={is_foundational}, prior={requires_prior} → priority={new_priority:.1f}")

    return new_priority


def update_priorities(index_path: Path, base_dir: Path = INPUT_DIR, use_ollama: bool = False) -> int:
    """
    Aktualizuje priorytety dla plików ze statusem NEW.

    Args:
        index_path: Ścieżka do indeksu
        base_dir: Katalog bazowy (INPUT_DIR)
        use_ollama: Czy użyć Ollama do dodatkowej oceny (wolniejsze, ale dokładniejsze)

    Returns:
        Liczba zaktualizowanych rekordów
    """
    logger.info("[PRIORITY] Aktualizuje priorytety...")

    index = load_index(index_path)

    updated = 0
    for record in index:
        # Aktualizuj tylko NEW (nie ruszaj learned/hard_topic itp.)
        if record['status'] != STATUS_NEW:
            continue

        if use_ollama:
            filepath = base_dir / record['id']
            if filepath.exists():
                new_priority = recalculate_priority_with_ollama(record, filepath)
                record['priority'] = new_priority
                record['priority_method'] = 'ollama'
                updated += 1
        else:
            # Priorytet został już obliczony w perception.py
            record['priority_method'] = 'heuristic'

    if updated > 0:
        save_index(index, index_path)
        logger.info(f"[OK] Zaktualizowano priorytety dla {updated} plikow")
    else:
        logger.info("[OK] Brak plikow do aktualizacji priorytetow")

    return updated


def reprocess_hard_topics(index_path: Path, files_since_hard: int = 5) -> int:
    """
    Przywraca trudne tematy do nauki po nauczeniu się innych plików.

    Args:
        index_path: Ścieżka do indeksu
        files_since_hard: Po ilu nauczonych plikach przywrócić hard topic

    Returns:
        Liczba przywróconych plików
    """
    logger.info("[RETRY] Sprawdzam czy mozna przywrocic hard topics...")

    index = load_index(index_path)

    # Policz ukończone pliki
    completed = [r for r in index if r['status'] == 'completed']
    hard_topics = [r for r in index if r['status'] == STATUS_HARD_TOPIC]

    if not hard_topics:
        logger.info("[OK] Brak hard topics do przywrocenia")
        return 0

    # Jeśli mamy wystarczająco dużo ukończonych, przywróć pierwszy hard topic
    if len(completed) >= files_since_hard:
        target = hard_topics[0]
        target['status'] = STATUS_NEW
        target['exam_attempts'] = 0
        target['last_scores'] = []
        target['priority'] += 10  # lekki bonus
        target['updated_at'] = get_timestamp()

        save_index(index, index_path)

        logger.info(f"[RETRY] Przywrocono hard topic: {target['id']}")
        return 1

    return 0
