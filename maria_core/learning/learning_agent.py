"""
DEAMONMARIA V2 - Learning Agent Module
Uczenie sie z plikow tekstowych: wybor pliku, chunking, nauka przez LLM.

Utilities (call_ollama, JSON parsing) przeniesione do llm_utils.py.
Chunking przeniesiony do chunking.py.
"""

from pathlib import Path
from typing import Dict, Any, Optional
import logging
import gc
import time
from maria_core.sys.config import (
    INPUT_DIR,
    OLLAMA_MODEL,
    STATUS_NEW,
    STATUS_LEARNING,
    STATUS_LEARNED,
    STATUS_EXAM_FAILED,
    get_timestamp,
)
from maria_core.memory_engine.memory_store import (
    load_index,
    save_index,
    append_memory,
    get_memories_for_file,
)
from maria_core.learning.llm_utils import (
    call_ollama,
    extract_json_from_response,
    _parse_markdown_to_learning_dict,
)
from maria_core.learning.chunking import intelligent_chunk_text

logger = logging.getLogger(__name__)


# ========== PROMPTY ==========

PROMPT_LEARN_NORMAL = """Jesteś M.A.R.I.A. – lokalną, autonomiczną inteligencją działającą w systemie offline/online.
Analizujesz fragment tekstu, który jest częścią większego dokumentu uczącego Cię nowych pojęć.

Twoje zadanie:
1. Szczegółowo streść fragment w maksymalnie 10–12 zdaniach.
2. Wypisz listę 5–12 kluczowych punktów (bullet-points).
3. Wyodrębnij 5–15 najważniejszych pojęć/tagów opisujących temat.
4. Wypisz 3 przykładowe pytania sprawdzające wiedzę z tego fragmentu.

Fragment:
--------------------
{chunk}
--------------------

Odpowiedz w czystym JSON (bez markdown):
{{
  "summary": "...",
  "key_points": ["...", "..."],
  "tags": ["...", "..."],
  "questions": ["...", "..."]
}}"""

PROMPT_LEARN_SIMPLE = """Jesteś M.A.R.I.A. – lokalną, autonomiczną inteligencją.
Poprzedni egzamin z tego materiału został niezdany.
Wyjaśnij tekst tak, jakbyś tłumaczyła go dziecku w wieku 12 lat.

Twoje zadanie:
1. Wyjaśnij ten fragment JAK NAJPROŚCIEJ (maks 6–7 zdań).
2. Wypisz tylko 3 najważniejsze idee.
3. Wypisz 5 tagów (pojęć kluczowych).

Fragment:
--------------------
{chunk}
--------------------

Odpowiedz w JSON (bez markdown):
{{
  "summary_simple": "...",
  "core_ideas": ["...", "...", "..."],
  "tags": ["...", "..."]
}}"""


def learn_chunk(chunk_text: str, use_simple: bool = False, llm_fn=None) -> Optional[Dict[str, Any]]:
    """
    Uczy się pojedynczego chunka przez Ollama (lub podany LLM).

    Args:
        chunk_text: Tekst do nauczenia
        use_simple: Czy użyć uproszczonego prompta (po failed exam)
        llm_fn: Opcjonalna funkcja LLM (signature: fn(prompt) -> str).
                 Domyślnie call_ollama.

    Returns:
        Słownik z summary, key_points, tags lub None
    """
    prompt_template = PROMPT_LEARN_SIMPLE if use_simple else PROMPT_LEARN_NORMAL
    prompt = prompt_template.format(chunk=chunk_text)

    logger.debug(f"Uczę się chunka ({len(chunk_text)} znaków), simple={use_simple}")

    _call = llm_fn if llm_fn is not None else call_ollama
    response = _call(prompt)
    if not response:
        return None

    parsed = extract_json_from_response(response)
    if not parsed:
        return None

    # Walidacja struktury
    if use_simple:
        required = ['summary_simple', 'core_ideas', 'tags']
    else:
        required = ['summary', 'key_points', 'tags']

    if not all(k in parsed for k in required):
        logger.error(f"Brak wymaganych pól w odpowiedzi: {list(parsed.keys())}")
        return None

    return parsed


def learn_next_chunk(
    base_dir: Path,
    index_path: Path,
    memory_path: Path,
    ollama_model: str = OLLAMA_MODEL,
    llm_fn=None,
) -> bool:
    """
    Uczy się następnego chunka z pliku o najwyższym priorytecie.

    Args:
        base_dir: Katalog bazowy (INPUT_DIR)
        index_path: Ścieżka do indeksu
        memory_path: Ścieżka do pamięci długoterminowej
        ollama_model: Nazwa modelu Ollama

    Returns:
        True jeśli coś przetworzono, False jeśli brak pracy
    """
    logger.info("[BRAIN] Rozpoczynam nauke nastepnego chunka...")

    # Wczytaj indeks
    index = load_index(index_path)

    # Znajdź plik do nauki
    candidates = [r for r in index if r['status'] in [STATUS_NEW, STATUS_LEARNING, STATUS_EXAM_FAILED]]
    if not candidates:
        logger.info("[OK] Brak plikow do nauki")
        return False

    # Sortuj po priorytecie
    candidates.sort(key=lambda x: x.get('priority', 0), reverse=True)
    target = candidates[0]

    file_id = target['id']
    filepath = base_dir / file_id

    logger.info(f"[LEARN] Ucze sie z: {file_id} (priorytet: {target.get('priority', 0):.1f})")

    # Wczytaj plik
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Nie mogę odczytać {filepath}: {e}")
        return False

    # Podziel na chunki
    chunks = intelligent_chunk_text(content)
    target['total_chunks'] = len(chunks)

    # Sprawdź które chunki już przerobiono
    existing_memories = get_memories_for_file(file_id, memory_path)
    learned_chunk_ids = {m.get('chunk_id') for m in existing_memories}

    # Znajdź pierwszy nieprzerobiony chunk
    chunk_to_learn = None
    chunk_idx = None
    for idx, (chunk_text, start, end) in enumerate(chunks):
        chunk_id = f"{file_id}#chunk_{idx}"
        if chunk_id not in learned_chunk_ids:
            chunk_to_learn = chunk_text
            chunk_idx = idx
            break

    if chunk_to_learn is None:
        logger.info(f"[OK] Plik {file_id} calkowicie nauczony ({len(chunks)} chunkow)")
        target['status'] = STATUS_LEARNED
        target['chunks_learned'] = len(chunks)
        save_index(index, index_path)
        return True

    # Określ czy użyć prostego prompta
    use_simple = (target['status'] == STATUS_EXAM_FAILED)

    # Ucz się chunka
    learned_data = learn_chunk(chunk_to_learn, use_simple=use_simple, llm_fn=llm_fn)
    
    gc.collect()
    time.sleep(0.1)

    if not learned_data:
        logger.error(f"Nie udało się nauczyć chunka {chunk_idx}")
        return False

    # Zapisz do pamięci
    memory_record = {
        "source_file": file_id,
        "folder": target['folder'],
        "chunk_id": f"{file_id}#chunk_{chunk_idx}",
        "chunk_index": chunk_idx,
        "timestamp": get_timestamp(),
        "learned_simple": use_simple,
        **learned_data
    }

    append_memory(memory_record, memory_path)

    # Aktualizuj indeks
    target['chunks_learned'] = len(learned_chunk_ids) + 1
    target['status'] = STATUS_LEARNING
    target['updated_at'] = get_timestamp()

    save_index(index, index_path)

    logger.info(f"[OK] Nauczono chunk {chunk_idx + 1}/{len(chunks)} z {file_id}")

    return True
