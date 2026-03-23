"""
DEAMONMARIA V2 - Exam Agent Module
Generowanie egzaminów, odpowiadanie, ocena i logika hard_topic.
Adaptacyjna liczba pytań, zapobieganie zapętleniu.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from maria_core.sys.config import (
    OLLAMA_MODEL,
    OLLAMA_TEMPERATURE,
    EXAM_MIN_QUESTIONS,
    EXAM_MAX_QUESTIONS,
    EXAM_QUESTIONS_PER_CHUNK,
    EXAM_PASS_THRESHOLD,
    EXAM_MAX_ATTEMPTS,
    STATUS_LEARNED,
    STATUS_EXAM_FAILED,
    STATUS_HARD_TOPIC,
    STATUS_COMPLETED,
    get_timestamp,
)
from maria_core.memory_engine.memory_store import (
    load_index,
    save_index,
    append_exam_result,
    get_memories_for_file,
    get_exam_results_for_file,
)
from maria_core.learning.learning_agent import call_ollama, extract_json_from_response

logger = logging.getLogger(__name__)


# ========== PROMPTY EGZAMINACYJNE ==========

PROMPT_GENERATE_EXAM = """Jesteś M.A.R.I.A. w trybie nauczyciela.
Masz przed sobą CAŁY kontekst nauki z danego pliku (połączone streszczenia i punkty kluczowe).

Twoje zadanie:
- Przygotuj egzamin składający się z {num_questions} pytań otwartych.
- Do każdego pytania podaj idealną odpowiedź wzorcową (2-4 zdania).
- Pytania powinny sprawdzać zrozumienie, nie tylko pamięć.

Kontekst:
--------------------
{context}
--------------------

Odpowiedz w JSON (bez markdown):
{{
  "exam": [
    {{
      "q": "pytanie 1...",
      "expected": "idealna odpowiedź..."
    }},
    {{
      "q": "pytanie 2...",
      "expected": "..."
    }}
  ]
}}"""

PROMPT_ANSWER_EXAM = """Jesteś M.A.R.I.A. w trybie ucznia.
Odpowiedz na każde z pytań na podstawie swojej pamięci i kontekstu nauki.

Odpowiadaj naturalnie, 2–6 zdań na pytanie.

Kontekst:
--------------------
{context}
--------------------

Pytania:
{questions_list}

Odpowiedz w JSON (bez markdown):
{{
  "answers": [
    {{"a": "odpowiedź na pytanie 1..."}},
    {{"a": "odpowiedź na pytanie 2..."}}
  ]
}}"""

PROMPT_GRADE_EXAM = """Jesteś M.A.R.I.A. w trybie egzaminatora.
Twoim zadaniem jest porównanie odpowiedzi ucznia z odpowiedzią wzorcową.

Dla każdego pytania oceń:
- score w skali 0–1 (0 = błędne, 1 = idealnie zgodne)
- krótkie wyjaśnienie (1–2 zdania)

Bądź sprawiedliwy ale wymagający. Odpowiedź musi być merytorycznie poprawna.

Dane wejściowe:
--------------------
{qa_pairs}
--------------------

Odpowiedz w JSON (bez markdown):
{{
  "graded": [
    {{
      "score": 0.8,
      "explanation": "..."
    }}
  ],
  "final_score": 0.83
}}"""


def build_context_from_memories(memories: List[Dict[str, Any]]) -> str:
    """
    Buduje kontekst nauki z pamięci długoterminowej.

    Args:
        memories: Lista rekordów pamięci dla danego pliku

    Returns:
        String z kontekstem (streszczenia + kluczowe punkty)
    """
    context_parts = []

    for idx, mem in enumerate(memories, 1):
        # Użyj summary lub summary_simple
        summary = mem.get('summary') or mem.get('summary_simple', '')
        key_points = mem.get('key_points') or mem.get('core_ideas', [])

        part = f"Chunk {idx}:\n{summary}\n"
        if key_points:
            part += "Kluczowe punkty:\n"
            for kp in key_points:
                part += f"- {kp}\n"

        context_parts.append(part)

    return "\n".join(context_parts)


def calculate_num_questions(num_chunks: int) -> int:
    """
    Oblicza adaptacyjną liczbę pytań na egzamin.

    Args:
        num_chunks: Liczba chunków w pliku

    Returns:
        Liczba pytań (między MIN i MAX)
    """
    num_questions = int(num_chunks * EXAM_QUESTIONS_PER_CHUNK)
    return max(EXAM_MIN_QUESTIONS, min(EXAM_MAX_QUESTIONS, num_questions))


def generate_exam(context: str, num_questions: int, llm_fn=None) -> Optional[List[Dict[str, str]]]:
    """
    Generuje egzamin (pytania + odpowiedzi wzorcowe).

    Args:
        context: Kontekst nauki
        num_questions: Liczba pytań do wygenerowania
        llm_fn: Opcjonalna funkcja LLM (signature: fn(prompt) -> str).
                 Domyślnie call_ollama.

    Returns:
        Lista słowników [{"q": "...", "expected": "..."}] lub None
    """
    prompt = PROMPT_GENERATE_EXAM.format(
        num_questions=num_questions,
        context=context
    )

    logger.debug(f"Generuję egzamin z {num_questions} pytaniami")

    _call = llm_fn if llm_fn is not None else call_ollama
    response = _call(prompt)  # niższa temperatura dla stabilności
    if not response:
        return None

    parsed = extract_json_from_response(response)
    if not parsed or 'exam' not in parsed:
        logger.error("Brak pola 'exam' w odpowiedzi")
        return None

    exam = parsed['exam']
    if not isinstance(exam, list) or len(exam) == 0:
        logger.error("Pole 'exam' nie jest niepustą listą")
        return None

    # Normalize keys: LLM may return "answer"/"correct" instead of "expected"
    normalized = []
    for item in exam:
        if not isinstance(item, dict):
            continue
        q = item.get("q", item.get("question", item.get("pytanie", "")))
        expected = item.get("expected",
                           item.get("answer", item.get("a",
                           item.get("correct", item.get("odpowiedz", "")))))
        if q and expected:
            normalized.append({"q": str(q), "expected": str(expected)})
    if not normalized:
        logger.error("Nie udalo sie znormalizowac pytan egzaminacyjnych")
        return None

    return normalized


def answer_exam(context: str, questions: List[Dict[str, str]], llm_fn=None) -> Optional[List[Dict[str, str]]]:
    """
    Odpowiada na pytania egzaminacyjne.

    Args:
        context: Kontekst nauki
        questions: Lista pytań [{"q": "...", "expected": "..."}]
        llm_fn: Opcjonalna funkcja LLM (signature: fn(prompt) -> str).
                 Domyślnie call_ollama.

    Returns:
        Lista odpowiedzi [{"a": "..."}] lub None
    """
    questions_list = "\n".join([f"{i+1}. {q.get('q', '?')}" for i, q in enumerate(questions)])

    prompt = PROMPT_ANSWER_EXAM.format(
        context=context,
        questions_list=questions_list
    )

    logger.debug(f"Odpowiadam na {len(questions)} pytań")

    _call = llm_fn if llm_fn is not None else call_ollama
    response = _call(prompt)
    if not response:
        return None

    parsed = extract_json_from_response(response)
    if not parsed or 'answers' not in parsed:
        logger.error("Brak pola 'answers' w odpowiedzi")
        return None

    answers = parsed['answers']
    if not isinstance(answers, list) or len(answers) != len(questions):
        logger.error(f"Liczba odpowiedzi ({len(answers)}) != liczba pytań ({len(questions)})")
        return None

    return answers


def grade_exam(questions: List[Dict[str, str]], answers: List[Dict[str, str]], llm_fn=None) -> Optional[Dict[str, Any]]:
    """
    Ocenia odpowiedzi na egzaminie.

    Args:
        questions: Lista pytań z odpowiedziami wzorcowymi
        answers: Lista odpowiedzi ucznia
        llm_fn: Opcjonalna funkcja LLM (signature: fn(prompt) -> str).
                 Domyślnie call_ollama.

    Returns:
        Słownik z 'graded' (lista ocen) i 'final_score' (średnia) lub None
    """
    # Zbuduj pary pytanie-odpowiedź wzorcowa-odpowiedź ucznia
    qa_pairs = []
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        pair = f"Pytanie {i}: {q.get('q', '?')}\n"
        pair += f"Odpowiedź wzorcowa: {q.get('expected', '?')}\n"
        pair += f"Odpowiedź ucznia: {a.get('a', '?')}\n"
        qa_pairs.append(pair)

    qa_text = "\n".join(qa_pairs)

    prompt = PROMPT_GRADE_EXAM.format(qa_pairs=qa_text)

    logger.debug(f"Oceniam {len(questions)} odpowiedzi")

    _call = llm_fn if llm_fn is not None else call_ollama
    response = _call(prompt)  # bardzo niska temperatura dla konsystencji
    if not response:
        return None

    parsed = extract_json_from_response(response)
    if not parsed or 'graded' not in parsed or 'final_score' not in parsed:
        logger.error("Brak wymaganych pól w ocenie")
        return None

    return parsed


def check_for_looping(record: Dict[str, Any]) -> bool:
    """
    Sprawdza czy system się zapętlił (podobne wyniki egzaminów).

    Args:
        record: Rekord z indeksu

    Returns:
        True jeśli wykryto zapętlenie
    """
    scores = record.get('last_scores', [])

    # Jeśli mamy 3+ wyniki i wszystkie są podobne (różnica < 0.05)
    if len(scores) >= 3:
        recent = scores[-3:]
        max_diff = max(recent) - min(recent)
        if max_diff < 0.05:
            logger.warning(f"Wykryto zapętlenie dla {record['id']}: wyniki {recent}")
            return True

    return False


def _find_exam_candidate(index, target_file_id=None):
    """
    Find a file to examine.

    Args:
        index: Knowledge index records
        target_file_id: Specific file (spaced repetition) or None (auto-select)

    Returns:
        (target_record, file_id) or (None, file_id) if not found
    """
    if target_file_id:
        for rec in index:
            if rec['id'] == target_file_id:
                return rec, rec['id']
        logger.info(f"[EXAM] Plik {target_file_id} nie znaleziony w indeksie")
        return None, target_file_id

    candidates = [
        r for r in index
        if r['status'] == STATUS_LEARNED and r['exam_attempts'] < EXAM_MAX_ATTEMPTS
    ]
    if not candidates:
        logger.info("[OK] Brak plikow gotowych na egzamin")
        return None, ""

    candidates.sort(key=lambda x: x.get('priority', 0), reverse=True)
    target = candidates[0]
    return target, target['id']


def _execute_exam(file_id, memory_path, llm_fn=None):
    """
    Run the 3-step exam pipeline: generate -> answer -> grade.

    Returns:
        (score, exam_questions, answers, grading) or (None, ...) on failure
    """
    memories = get_memories_for_file(file_id, memory_path)
    if not memories:
        logger.error(f"Brak pamięci dla {file_id}!")
        return None, None, None, None

    context = build_context_from_memories(memories)
    num_questions = calculate_num_questions(len(memories))

    exam = generate_exam(context, num_questions, llm_fn=llm_fn)
    if not exam:
        logger.error("Nie udalo sie wygenerowac egzaminu")
        return None, None, None, None

    answers = answer_exam(context, exam, llm_fn=llm_fn)
    if not answers:
        logger.error("Nie udalo sie odpowiedziec na egzamin")
        return None, exam, None, None

    grading = grade_exam(exam, answers, llm_fn=llm_fn)
    if not grading:
        logger.error("Nie udalo sie ocenic egzaminu")
        return None, exam, answers, None

    return grading['final_score'], exam, answers, grading


def _update_status_after_exam(target, final_score, passed, is_spaced_repetition):
    """
    Update file status in index based on exam result.

    Rules:
    - spaced repetition: always keep COMPLETED
    - passed: COMPLETED
    - 1st fail: EXAM_FAILED (second chance)
    - 2nd+ fail or looping: HARD_TOPIC
    """
    target['exam_attempts'] += 1
    target['last_scores'].append(final_score)

    if is_spaced_repetition:
        target['status'] = STATUS_COMPLETED
        if passed:
            logger.info(f"[REVIEW PASS] Powtorka ZALICZONA ({final_score:.2%})")
        else:
            logger.warning(f"[REVIEW FAIL] Powtorka NIEZALICZONA ({final_score:.2%}) - zostaje completed")
    elif passed:
        target['status'] = STATUS_COMPLETED
        logger.info(f"[PASS] Egzamin ZALICZONY ({final_score:.2%})")
    else:
        if target['exam_attempts'] == 1:
            target['status'] = STATUS_EXAM_FAILED
            logger.warning(f"[FAIL] Egzamin NIEZALICZONY ({final_score:.2%}) - druga szansa")
        else:
            target['status'] = STATUS_HARD_TOPIC
            target['priority'] -= 30
            logger.warning(f"[HARD] Egzamin NIEZALICZONY ({final_score:.2%}) - HARD TOPIC")

    if check_for_looping(target):
        target['status'] = STATUS_HARD_TOPIC
        target['priority'] -= 20
        logger.warning(f"Wykryto zapetlenie - oznaczam jako HARD TOPIC")

    target['updated_at'] = get_timestamp()


def run_exam_if_ready(
    index_path: Path,
    memory_path: Path,
    exam_path: Path,
    ollama_model: str = OLLAMA_MODEL,
    llm_fn=None,
    target_file_id: str = None,
) -> Dict[str, Any]:
    """
    Run exam for a file that is ready (status=learned) or specific file (spaced repetition).

    Pipeline: find candidate -> generate/answer/grade -> save result -> update status.

    Returns:
        Dict: executed, passed, score, file_id
    """
    logger.info("[EXAM] Sprawdzam czy jest plik gotowy na egzamin...")
    index = load_index(index_path)

    # 1. Find candidate
    target, file_id = _find_exam_candidate(index, target_file_id)
    no_exam = {"executed": False, "passed": False, "score": 0.0, "file_id": file_id}
    if target is None:
        return no_exam

    logger.info(f"[EXAM] Egzamin z: {file_id}")

    # 2. Execute exam pipeline
    final_score, exam, answers, grading = _execute_exam(file_id, memory_path, llm_fn)
    if final_score is None:
        return no_exam

    passed = final_score >= EXAM_PASS_THRESHOLD
    logger.info(f"[SCORE] Wynik egzaminu: {final_score:.2%}")

    # 3. Save exam result
    append_exam_result({
        "file": file_id,
        "timestamp": get_timestamp(),
        "attempt": target['exam_attempts'] + 1,
        "score": final_score,
        "num_questions": len(exam),
        "questions": exam,
        "answers": answers,
        "grading": grading['graded'],
    }, exam_path)

    # 4. Update status
    is_spaced = target_file_id is not None
    _update_status_after_exam(target, final_score, passed, is_spaced)
    save_index(index, index_path)

    return {"executed": True, "passed": passed, "score": final_score, "file_id": file_id}
