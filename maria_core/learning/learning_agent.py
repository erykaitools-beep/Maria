"""
DEAMONMARIA V2 - Learning Agent Module
Inteligentne uczenie się z plików tekstowych przez Ollama.
Chunking adaptacyjny, overlapping, wywołania do modelu.
"""

import re
import requests
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging
import gc
import time
from maria_core.sys.config import (
    INPUT_DIR,
    OLLAMA_MODEL,
    OLLAMA_HOST,
    OLLAMA_TIMEOUT,
    OLLAMA_TEMPERATURE,
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    TARGET_CHUNK_SIZE,
    CHUNK_OVERLAP,
    CHUNK_SEPARATORS,
    STATUS_NEW,
    STATUS_LEARNING,
    STATUS_LEARNED,
    STATUS_EXAM_FAILED,
    MAX_RETRIES_OLLAMA,
    get_timestamp,
)
from maria_core.memory_engine.memory_store import (
    load_index,
    save_index,
    append_memory,
    get_memories_for_file
)

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


def call_ollama(prompt: str, model: str = OLLAMA_MODEL, temperature: float = OLLAMA_TEMPERATURE) -> Optional[str]:
    """
    Wywołuje Ollama API z obsługą błędów i retry.

    Args:
        prompt: Prompt dla modelu
        model: Nazwa modelu
        temperature: Temperatura generowania

    Returns:
        Odpowiedź modelu (string) lub None w razie błędu
    """
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
        }
    }

    for attempt in range(MAX_RETRIES_OLLAMA):
        try:
            response = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            return result.get('response', '').strip()
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama timeout (próba {attempt + 1}/{MAX_RETRIES_OLLAMA})")
            if attempt == MAX_RETRIES_OLLAMA - 1:
                logger.error("Ollama nie odpowiada po wszystkich próbach")
                return None
        except Exception as e:
            logger.error(f"Błąd wywołania Ollama: {e}")
            return None

    return None


def extract_json_from_response(response: str) -> Optional[Dict[str, Any]]:
    """
    Wyciąga JSON z odpowiedzi modelu (obsługuje markdown ```json```).
    Zwraca dict albo None.
    """
    # 0. Bezpiecznik na None / pusty tekst
    if response is None:
        logger.error("[JSON] Otrzymano None zamiast tekstu odpowiedzi.")
        return None

    response = response.strip()
    if not response:
        logger.error("[JSON] Pusta odpowiedź z modelu – brak treści do parsowania.")
        return None

    original_response = response  # kopia do logów

    # 1. Obsługa bloków ```json ... ```
    if response.startswith('```'):
        match = re.search(r'```(?:json)?\s*(.+?)\s*```', response, re.DOTALL | re.IGNORECASE)
        if match:
            response = match.group(1).strip()

    # 2. Pierwsza próba: cały tekst jako JSON
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        logger.warning(f"[JSON] Nie udało się sparsować pełnej odpowiedzi jako JSON: {e}")

    # 3. Druga próba: fragment między pierwszym '{' a ostatnim '}'
    start = response.find("{")
    end = response.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = response[start:end+1].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            logger.warning(f"[JSON] Nie udało się sparsować wycinka {{...}}: {e}")

    # 4. Ostatecznie: oddaj None + log do debugowania
    logger.error("[JSON] Błąd parsowania JSON – nie udało się wyciągnąć poprawnego JSON z odpowiedzi.")
    logger.debug(f"[JSON] Surowa odpowiedź (pierwsze 1000 znaków): {original_response[:1000]}...")
    return None



def intelligent_chunk_text(text: str) -> List[Tuple[str, int, int]]:
    """
    Inteligentny podział tekstu na chunki z overlapem.

    Priorytetyzuje naturalne granice (paragrafy, zdania) zamiast sztywnego podziału.

    Args:
        text: Tekst do podzielenia

    Returns:
        Lista krotek: (chunk_text, start_pos, end_pos)
    """
    if len(text) <= MAX_CHUNK_SIZE:
        return [(text, 0, len(text))]

    chunks = []
    start = 0

    while start < len(text):
        # Określ koniec chunka
        end = min(start + TARGET_CHUNK_SIZE, len(text))

        # Jeśli to nie koniec tekstu, znajdź najlepszy punkt podziału
        if end < len(text):
            best_split = end

            # Szukaj separatorów w kolejności priorytetu
            for separator in CHUNK_SEPARATORS:
                # Szukaj w oknie [end-200, end+200]
                search_start = max(end - 200, start)
                search_end = min(end + 200, len(text))
                search_text = text[search_start:search_end]

                # Znajdź ostatnie wystąpienie separatora
                sep_pos = search_text.rfind(separator)
                if sep_pos != -1:
                    actual_pos = search_start + sep_pos + len(separator)
                    # Sprawdź czy nie za mały/duży chunk
                    chunk_size = actual_pos - start
                    if MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE * 1.5:
                        best_split = actual_pos
                        break

            end = best_split

        # Wytnij chunk
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append((chunk_text, start, end))

        # Następny chunk z overlapem
        start = end - CHUNK_OVERLAP

        # Zabezpieczenie przed nieskończoną pętlą
        if start >= end:
            start = end

    logger.debug(f"Podzielono tekst na {len(chunks)} chunków")
    return chunks


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
    ollama_model: str = OLLAMA_MODEL
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
    learned_data = learn_chunk(chunk_to_learn, use_simple=use_simple)
    
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
