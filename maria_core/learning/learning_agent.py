"""
DEAMONMARIA V2 - Learning Agent Module
Uczenie sie z plikow tekstowych: wybor pliku, chunking, nauka przez LLM.

Utilities (call_ollama, JSON parsing) przeniesione do llm_utils.py.
Chunking przeniesiony do chunking.py.
"""

from dataclasses import dataclass
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
    STATUS_HARD_TOPIC,
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


@dataclass(frozen=True)
class LearnResult:
    """Outcome of one learn attempt.

    Exists to separate "nothing to do" from "worked" and from "broke". The old
    bare bool collapsed the first two: a file whose chunks were all in memory
    returned True, so a no-op logged as a success. That inflated learn action
    success by 22% on 2026-07-16 (101 actions vs 83 chunks) and, once such files
    reached the head of the priority queue, kept the planner reporting 100%
    success at zero learning velocity.

    Truthy iff a chunk was actually learned, so existing ``if success:`` callers
    keep working; ``skipped`` is what tells a caller this consumed no work.
    A skip must never be reported as a failure -- the self-repair failure-storm
    detector counts ``success is False and not skipped``, so mislabelling an
    idle tick would manufacture a fake incident.
    """

    learned: bool
    skipped: bool = False
    reason: str = ""
    # Which file this call ACTUALLY touched. When a caller names a file that is
    # not learnable, selection falls back to priority and works on a different
    # one -- so the requested id is not the processed id. The exam path carried
    # the same bug until 2026-08-12, where crediting a score to strategy.target
    # benched a healthy file and left the broken one eligible.
    file_id: str = ""

    def __bool__(self) -> bool:
        return self.learned


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
    target_file_id: str = None,
    use_simple: Optional[bool] = None,
) -> "LearnResult":
    """
    Uczy sie nastepnego chunka z pliku.

    Args:
        base_dir: Katalog bazowy (INPUT_DIR)
        index_path: Sciezka do indeksu
        memory_path: Sciezka do pamieci dlugoterminowej
        ollama_model: Nazwa modelu Ollama
        llm_fn: Optional LLM function
        target_file_id: Optional file ID to learn from (overrides priority selection).
            A named file may be HARD_TOPIC: those are excluded from the priority
            pool on purpose, but naming one explicitly is how the teacher asks for
            a simpler retry, and refusing it silently sent that request to some
            other file entirely.
        use_simple: Force the simple (post-failed-exam) prompt on or off.
            None means "derive from status", which is what the autonomous loop
            wants. The teacher passes True for retry_hard_topic -- that intent
            used to be accepted by the wrapper and dropped on the floor.

    Returns:
        LearnResult. Truthy iff a chunk was really learned; `file_id` names the
        file actually processed, which is NOT always target_file_id.
    """
    logger.info("[BRAIN] Rozpoczynam nauke nastepnego chunka...")

    # Wczytaj indeks
    index = load_index(index_path)

    # Znajdz plik do nauki
    candidates = [r for r in index if r['status'] in [STATUS_NEW, STATUS_LEARNING, STATUS_EXAM_FAILED]]
    if not candidates:
        logger.info("[OK] Brak plikow do nauki")
        return LearnResult(learned=False, skipped=True, reason="no_candidates")

    # Jesli podano konkretny plik, uzyj go
    target = None
    if target_file_id:
        for r in candidates:
            if r['id'] == target_file_id:
                target = r
                break
        if target is None:
            # HARD_TOPIC is kept out of the priority pool deliberately -- it must
            # not be picked up by the autonomous loop. But naming one explicitly
            # is exactly how the teacher asks for a simpler retry
            # (strategy reason == "retry_hard_topic"), and refusing it here sent
            # that request silently to whatever sat on top of the ranking.
            for r in index:
                if r['id'] == target_file_id and r['status'] == STATUS_HARD_TOPIC:
                    target = r
                    logger.info(f"[LEARN] Wskazany hard_topic {target_file_id} -- powtorka na zyczenie")
                    break
        if target is None:
            logger.warning(f"[LEARN] Requested file {target_file_id} not learnable, falling back to priority")

    # Fallback: sortuj po priorytecie
    if target is None:
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
        return LearnResult(learned=False, reason="source_unreadable", file_id=file_id)

    # Podziel na chunki
    chunks = intelligent_chunk_text(content)
    target['total_chunks'] = len(chunks)

    # Określ czy użyć prostego prompta.
    # Liczone PRZED wyborem chunka, bo decyduje o tym, co znaczy "przerobiony".
    # Explicit override wins; None means derive from status, which is what the
    # autonomous loop wants. The teacher's retry_hard_topic intent arrives here.
    if use_simple is None:
        use_simple = (target['status'] == STATUS_EXAM_FAILED)

    # Sprawdź które chunki już przerobiono
    existing_memories = get_memories_for_file(file_id, memory_path)
    all_learned_ids = {m.get('chunk_id') for m in existing_memories}

    if use_simple:
        # Przebieg ratunkowy po oblanym egzaminie ma przerobić materiał OD NOWA
        # prostszym promptem (PROMPT_LEARN_SIMPLE). Liczenie tu rekordów ze
        # zwykłego przebiegu sprawiało, że każdy chunk wyglądał na gotowy, więc
        # prostszy prompt NIGDY nie startował: 4 rekordy learned_simple na 9952
        # w całej historii projektu. Plik wracał na drugie podejście egzaminu
        # niezmieniony, a akcja learn meldowała sukces nie ucząc się niczego
        # (K12 widział to jako "velocity flat at 0.0 while learn reports 100").
        pending_against = {
            m.get('chunk_id') for m in existing_memories if m.get('learned_simple')
        }
    else:
        pending_against = all_learned_ids

    # Znajdź pierwszy nieprzerobiony chunk
    chunk_to_learn = None
    chunk_idx = None
    for idx, (chunk_text, start, end) in enumerate(chunks):
        chunk_id = f"{file_id}#chunk_{idx}"
        if chunk_id not in pending_against:
            chunk_to_learn = chunk_text
            chunk_idx = idx
            break

    if chunk_to_learn is None:
        # Nie ma czego uczyć. To NIE jest sukces nauki -- oznaczanie tego jako
        # sukces zawyżało skuteczność akcji learn o 22% już 2026-07-16
        # (101 akcji vs 83 chunki, patrz knowledge_analyzer.count_chunks_learned)
        # i utrzymywało planer w przekonaniu, że pracuje.
        logger.info(f"[OK] Plik {file_id} calkowicie nauczony ({len(chunks)} chunkow)")
        target['status'] = STATUS_LEARNED
        target['chunks_learned'] = len(chunks)
        save_index(index, index_path)
        return LearnResult(learned=False, skipped=True, reason="nothing_to_learn", file_id=file_id)

    # Backoff: skip chunk po zbyt wielu probach
    MAX_CHUNK_RETRIES = 5
    fail_key = f"{file_id}#chunk_{chunk_idx}"
    chunk_failures = target.get("chunk_failures", {})
    fail_count = chunk_failures.get(fail_key, 0)
    if fail_count >= MAX_CHUNK_RETRIES:
        logger.warning(f"[SKIP] Chunk {chunk_idx} z {file_id} failowal {fail_count}x, pomijam")
        # Zapisz jako nauczony z adnotacja skip (zeby nie blokowac)
        memory_record = {
            "source_file": file_id,
            "folder": target['folder'],
            "chunk_id": fail_key,
            "chunk_index": chunk_idx,
            "timestamp": get_timestamp(),
            "learned_simple": True,
            "summary": f"[SKIPPED] Chunk pominity po {fail_count} nieudanych probach",
            "key_points": [],
            "tags": ["skipped", "hard_chunk"],
            "questions": [],
        }
        append_memory(memory_record, memory_path)
        target['chunks_learned'] = len(all_learned_ids | {fail_key})
        target['status'] = STATUS_LEARNING
        target['updated_at'] = get_timestamp()
        # Wyczysc failure counter dla tego chunka
        chunk_failures.pop(fail_key, None)
        target['chunk_failures'] = chunk_failures
        save_index(index, index_path)
        logger.info(f"[OK] Pominieto chunk {chunk_idx + 1}/{len(chunks)} z {file_id}")
        return LearnResult(learned=False, skipped=True, reason="chunk_backoff", file_id=file_id)

    # Ucz sie chunka
    learned_data = learn_chunk(chunk_to_learn, use_simple=use_simple, llm_fn=llm_fn)

    gc.collect()
    time.sleep(0.1)

    if not learned_data:
        # Trackuj failure count
        chunk_failures[fail_key] = fail_count + 1
        target['chunk_failures'] = chunk_failures
        save_index(index, index_path)
        logger.error(f"Nie udalo sie nauczyc chunka {chunk_idx} ({fail_count + 1}/{MAX_CHUNK_RETRIES})")
        return LearnResult(learned=False, reason="llm_returned_nothing", file_id=file_id)

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

    # Aktualizuj indeks. Liczone z UNII wszystkich chunkow, nie z licznika
    # przebiegu: w przebiegu ratunkowym pending_against to tylko rekordy
    # learned_simple, wiec licznik oparty na nim cofnalby postep pliku do zera.
    target['chunks_learned'] = len(all_learned_ids | {f"{file_id}#chunk_{chunk_idx}"})
    target['status'] = STATUS_LEARNING
    target['updated_at'] = get_timestamp()

    save_index(index, index_path)

    logger.info(
        f"[OK] Nauczono chunk {chunk_idx + 1}/{len(chunks)} z {file_id}"
        f"{' (przebieg ratunkowy, prosty prompt)' if use_simple else ''}"
    )

    return LearnResult(learned=True, reason="simple" if use_simple else "normal", file_id=file_id)
