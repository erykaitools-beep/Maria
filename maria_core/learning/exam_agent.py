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


def generate_exam(context: str, num_questions: int) -> Optional[List[Dict[str, str]]]:
    """
    Generuje egzamin (pytania + odpowiedzi wzorcowe).

    Args:
        context: Kontekst nauki
        num_questions: Liczba pytań do wygenerowania

    Returns:
        Lista słowników [{"q": "...", "expected": "..."}] lub None
    """
    prompt = PROMPT_GENERATE_EXAM.format(
        num_questions=num_questions,
        context=context
    )

    logger.debug(f"Generuję egzamin z {num_questions} pytaniami")

    response = call_ollama(prompt, temperature=0.4)  # niższa temperatura dla stabilności
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

    return exam


def answer_exam(context: str, questions: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    """
    Odpowiada na pytania egzaminacyjne.

    Args:
        context: Kontekst nauki
        questions: Lista pytań [{"q": "...", "expected": "..."}]

    Returns:
        Lista odpowiedzi [{"a": "..."}] lub None
    """
    questions_list = "\n".join([f"{i+1}. {q['q']}" for i, q in enumerate(questions)])

    prompt = PROMPT_ANSWER_EXAM.format(
        context=context,
        questions_list=questions_list
    )

    logger.debug(f"Odpowiadam na {len(questions)} pytań")

    response = call_ollama(prompt, temperature=0.5)
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


def grade_exam(questions: List[Dict[str, str]], answers: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """
    Ocenia odpowiedzi na egzaminie.

    Args:
        questions: Lista pytań z odpowiedziami wzorcowymi
        answers: Lista odpowiedzi ucznia

    Returns:
        Słownik z 'graded' (lista ocen) i 'final_score' (średnia) lub None
    """
    # Zbuduj pary pytanie-odpowiedź wzorcowa-odpowiedź ucznia
    qa_pairs = []
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        pair = f"Pytanie {i}: {q['q']}\n"
        pair += f"Odpowiedź wzorcowa: {q['expected']}\n"
        pair += f"Odpowiedź ucznia: {a['a']}\n"
        qa_pairs.append(pair)

    qa_text = "\n".join(qa_pairs)

    prompt = PROMPT_GRADE_EXAM.format(qa_pairs=qa_text)

    logger.debug(f"Oceniam {len(questions)} odpowiedzi")

    response = call_ollama(prompt, temperature=0.2)  # bardzo niska dla konsystencji
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


def run_exam_if_ready(
    index_path: Path,
    memory_path: Path,
    exam_path: Path,
    ollama_model: str = OLLAMA_MODEL
) -> bool:
    """
    Uruchamia egzamin dla pliku, który jest gotowy (status=learned).

    Logika:
    1. Znajdź plik ze statusem LEARNED
    2. Wygeneruj egzamin na podstawie pamięci
    3. Odpowiedz na pytania
    4. Oceń odpowiedzi
    5. Zapisz wynik
    6. Zaktualizuj status:
       - score >= 0.6 → COMPLETED
       - score < 0.6 i attempt=1 → EXAM_FAILED (ponowna nauka)
       - score < 0.6 i attempt=2 → HARD_TOPIC
       - wykryto looping → HARD_TOPIC

    Args:
        index_path: Ścieżka do indeksu
        memory_path: Ścieżka do pamięci
        exam_path: Ścieżka do wyników egzaminów
        ollama_model: Model Ollama

    Returns:
        True jeśli przeprowadzono egzamin, False jeśli brak pracy
    """
    logger.info("📝 Sprawdzam czy jest plik gotowy na egzamin...")

    # Wczytaj indeks
    index = load_index(index_path)

    # Znajdź kandydatów
    candidates = []
    for rec in index:
        if rec['status'] == STATUS_LEARNED and rec['exam_attempts'] < EXAM_MAX_ATTEMPTS:
            candidates.append(rec)

    if not candidates:
        logger.info("✅ Brak plików gotowych na egzamin")
        return False

    # Wybierz pierwszy (lub najwyższy priorytet)
    candidates.sort(key=lambda x: x.get('priority', 0), reverse=True)
    target = candidates[0]

    file_id = target['id']
    logger.info(f"📝 Egzamin z: {file_id}")

    # Pobierz pamięci
    memories = get_memories_for_file(file_id, memory_path)
    if not memories:
        logger.error(f"Brak pamięci dla {file_id}!")
        return False

    # Zbuduj kontekst
    context = build_context_from_memories(memories)

    # Oblicz liczbę pytań
    num_questions = calculate_num_questions(len(memories))

    # Generuj egzamin
    exam = generate_exam(context, num_questions)
    if not exam:
        logger.error("Nie udało się wygenerować egzaminu")
        return False

    # Odpowiedz
    answers = answer_exam(context, exam)
    if not answers:
        logger.error("Nie udało się odpowiedzieć na egzamin")
        return False

    # Oceń
    grading = grade_exam(exam, answers)
    if not grading:
        logger.error("Nie udało się ocenić egzaminu")
        return False

    final_score = grading['final_score']
    logger.info(f"🎯 Wynik egzaminu: {final_score:.2%}")

    # Zapisz wynik
    exam_record = {
        "file": file_id,
        "timestamp": get_timestamp(),
        "attempt": target['exam_attempts'] + 1,
        "score": final_score,
        "num_questions": len(exam),
        "questions": exam,
        "answers": answers,
        "grading": grading['graded'],
    }
    append_exam_result(exam_record, exam_path)

    # Aktualizuj indeks
    target['exam_attempts'] += 1
    target['last_scores'].append(final_score)

    # Logika statusu
    if final_score >= EXAM_PASS_THRESHOLD:
        # Zaliczony!
        target['status'] = STATUS_COMPLETED
        logger.info(f"✅ Egzamin ZALICZONY ({final_score:.2%})")
    else:
        # Niezaliczony
        if target['exam_attempts'] == 1:
            # Pierwsza próba - daj drugą szansę
            target['status'] = STATUS_EXAM_FAILED
            logger.warning(f"❌ Egzamin NIEZALICZONY ({final_score:.2%}) - druga szansa")
        else:
            # Druga próba lub więcej - hard topic
            target['status'] = STATUS_HARD_TOPIC
            target['priority'] -= 30  # obniż priorytet
            logger.warning(f"⚠️  Egzamin NIEZALICZONY ({final_score:.2%}) - HARD TOPIC")

    # Sprawdź zapętlenie
    if check_for_looping(target):
        target['status'] = STATUS_HARD_TOPIC
        target['priority'] -= 20
        logger.warning(f"🔁 Wykryto zapętlenie - oznaczam jako HARD TOPIC")

    target['updated_at'] = get_timestamp()
    save_index(index, index_path)

    return True
