"""
DEAMONMARIA V2 - Exam Agent Module
Generowanie egzaminów, odpowiadanie, ocena i logika hard_topic.
Adaptacyjna liczba pytań, zapobieganie zapętleniu.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from maria_core.sys.config import (
    OLLAMA_MODEL,
    OLLAMA_TEMPERATURE,
    EXAM_MIN_QUESTIONS,
    EXAM_MAX_QUESTIONS,
    EXAM_CONTEXT_MAX_CHARS,
    EXAM_QUESTIONS_PER_CHUNK,
    EXAM_PASS_THRESHOLD,
    EXAM_MAX_ATTEMPTS,
    HELDOUT_BANK,
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
from maria_core.learning.llm_utils import call_ollama, extract_json_from_response

logger = logging.getLogger(__name__)

HELDOUT_GRADER_MODEL = "heldout:static@v1"
# A held-out exam below this many bank rows is statistically meaningless (a
# 1-row exam is a coin flip) -- fewer rows -> honest fallback to the LLM
# examiner, loudly logged + stamped heldout_fallback in the record (C3).
HELDOUT_MIN_BANK_ROWS = 3


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
Musisz odpowiedzieć DOKŁADNIE na {num_questions} pytań — ani mniej, ani więcej.
Każde pytanie wymaga osobnej odpowiedzi w tej samej kolejności co pytania.

Odpowiadaj naturalnie, 2–6 zdań na pytanie.

Kontekst:
--------------------
{context}
--------------------

Pytania ({num_questions}):
{questions_list}

Odpowiedz w JSON (bez markdown). Lista "answers" MUSI mieć dokładnie {num_questions} elementów:
{{
  "answers": [
    {{"a": "odpowiedź na pytanie 1..."}},
    {{"a": "odpowiedź na pytanie 2..."}}
  ]
}}"""

# Concise variant for HELD-OUT exams. The held-out grader is deterministic
# (it just checks whether the canonical fact/number is present), so a 2-6
# sentence essay is pure waste: ~98 tokens/answer measured 2026-06-04, which
# (with the retrieval context) pushed a single exam past the 240s Ollama
# timeout on CPU. A one-fact answer is ~5x shorter -> fits under the timeout,
# and tends to MATCH BETTER (less paraphrase that buries the canonical form).
PROMPT_ANSWER_EXAM_CONCISE = """Jesteś M.A.R.I.A. w trybie ucznia.
Musisz odpowiedzieć DOKŁADNIE na {num_questions} pytań — ani mniej, ani więcej.
Każde pytanie wymaga osobnej odpowiedzi w tej samej kolejności co pytania.

Odpowiadaj BARDZO KRÓTKO: sam fakt, liczba, nazwa lub jedno krótkie zdanie.
Bez wstępów, bez tłumaczenia, bez "tzw."/"około" gdy znasz dokładną wartość.

Kontekst:
--------------------
{context}
--------------------

Pytania ({num_questions}):
{questions_list}

Odpowiedz w JSON (bez markdown). Lista "answers" MUSI mieć dokładnie {num_questions} elementów:
{{
  "answers": [
    {{"a": "krótka odpowiedź 1"}},
    {{"a": "krótka odpowiedź 2"}}
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

Odpowiedz w JSON (bez markdown). Lista "graded" MUSI mieć dokładnie
{num_questions} elementów -- po jednym na każde pytanie, w tej samej kolejności.
Nie podawaj wyniku koncowego: liczy go egzamin, nie ty.
{{
  "graded": [
    {{
      "score": 0.8,
      "explanation": "..."
    }}
  ]
}}"""


def build_context_from_memories(
    memories: List[Dict[str, Any]], max_chars: Optional[int] = None
) -> str:
    """
    Buduje kontekst nauki z pamięci długoterminowej.

    Args:
        memories: Lista rekordów pamięci dla danego pliku
        max_chars: Opcjonalny cap na rozmiar kontekstu. Gdy pełny kontekst go
                   przekracza, chunki są próbkowane RÓWNOMIERNIE (co k-ty) do
                   limitu -- reprezentatywne pokrycie całego pliku zamiast samego
                   początku. Dla egzaminu open-book trzyma prompt-eval pod
                   OLLAMA_TIMEOUT na CPU (duże pliki do 117k znaków, 2026-06-06).

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

    full = "\n".join(context_parts)

    if max_chars and len(full) > max_chars and len(context_parts) > 1:
        # Pełny kontekst za duży -> próbkuj chunki RÓWNOMIERNIE do limitu, by
        # egzamin pokrywał cały plik (nie tylko początek). Spójne dla generate
        # i answer (oba czytają ten sam zwrócony kontekst). Oryginalne numery
        # "Chunk N" zostają, więc próbka jest czytelnie rozłożona.
        avg = len(full) / len(context_parts)
        keep = max(1, int(max_chars / avg))
        if keep < len(context_parts):
            step = len(context_parts) / keep
            idxs = sorted({int(i * step) for i in range(keep)})
            full = "\n".join(context_parts[i] for i in idxs)

    return full


def build_context_from_retrieval(
    semantic_memory,
    questions: List[Dict[str, str]],
    top_k: int = 4,
    exclude_file: Optional[str] = None,
    namespace: str = "summaries",
    threshold: float = 0.3,
    max_chunks: int = 12,
) -> str:
    """Build exam context by REAL retrieval over learned summaries (closed-book).

    Instead of spoon-feeding the file's own learned summary (open-book), retrieve
    the most relevant chunks from ALL learned content per question -- the same
    path production recall would use. This makes a passing score reflect the
    memory+retrieval system finding the answer, not copying a handed paragraph.

    ``exclude_file`` optionally drops a file's own chunks (stricter consolidation
    test); default keeps them (the answer chunk still competes among everything).
    Returns "" if nothing relevant is found (degrades to closed-book parametric).
    """
    if semantic_memory is None:
        return ""
    seen = set()
    parts: List[str] = []
    for q in questions:
        qtext = q.get("q") if isinstance(q, dict) else str(q)
        if not qtext:
            continue
        try:
            results = semantic_memory.search(
                qtext, namespace=namespace, top_k=top_k * 2, threshold=threshold
            )
        except Exception as e:  # retrieval must never crash an exam
            logger.warning(f"[HELDOUT] retrieval failed for a question: {e}")
            results = []
        kept = 0
        for r in results:
            meta = getattr(r.entry, "metadata", None) or {}
            if exclude_file and meta.get("source_file") == exclude_file:
                continue
            eid = getattr(r.entry, "entry_id", None) or id(r.entry)
            if eid in seen:
                continue
            seen.add(eid)
            parts.append(r.entry.text)
            kept += 1
            if kept >= top_k:
                break
        if len(parts) >= max_chunks:
            break
    return "\n\n".join(parts[:max_chunks])


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

    parsed = extract_json_from_response(response, expected_keys={'exam'})
    exam = None
    if parsed and 'exam' in parsed:
        exam = parsed['exam']
        if not isinstance(exam, list) or len(exam) == 0:
            logger.warning("Pole 'exam' nie jest niepustą listą, próbuję fallback parsera")
            exam = None

    if exam is None:
        fallback = _parse_exam_generate_fallback(response, num_questions)
        if fallback:
            logger.info(f"[EXAM] Fallback: parsed {len(fallback)} questions from text")
            exam = fallback
        else:
            logger.error("Brak pola 'exam' w odpowiedzi (fallback nie zadzialal)")
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


_NUMBERED_LIST_RE = re.compile(
    r'^\s*(\d+)[.):\]]\s*(.+?)(?=\n\s*\d+[.):\]]\s|\Z)',
    re.MULTILINE | re.DOTALL,
)


def _parse_numbered_list(
    text: str, expected_count: int, allow_partial: bool = False
) -> Optional[List[str]]:
    # Fallback for LLM responses that ignore the JSON instruction and
    # return a numbered list ("1. ...\n2. ...") instead.
    matches = _NUMBERED_LIST_RE.findall(text)
    if not matches:
        return None
    by_num: Dict[int, str] = {}
    for num_str, content in matches:
        try:
            n = int(num_str)
        except ValueError:
            continue
        if 1 <= n <= expected_count and n not in by_num:
            by_num[n] = content.strip()
    if not by_num:
        return None
    if allow_partial:
        # Grading averages over whatever it parsed; a missing item must not
        # nuke the whole batch (was the source of failed-exam action storms).
        return [by_num[i] for i in sorted(by_num)]
    if len(by_num) != expected_count:
        return None
    return [by_num[i] for i in range(1, expected_count + 1)]


_QA_ANSWER_MARKER_RE = re.compile(
    r'\n\s*(?:odpowied[zź](?:\s+wzorcowa)?|wzorzec|expected|answer)\s*[:\-]\s*',
    re.IGNORECASE,
)


def _parse_exam_generate_fallback(response: str, num_questions: int) -> Optional[List[Dict[str, str]]]:
    # Fallback when LLM ignores JSON instruction and emits markdown/numbered list
    # of question/answer pairs. Pairs split on common answer markers
    # ("Odpowiedz:", "Expected:", etc.) or first newline within each item.
    items = _parse_numbered_list(response, num_questions)
    if items is None:
        return None

    pairs: List[Dict[str, str]] = []
    for item in items:
        m = _QA_ANSWER_MARKER_RE.search(item)
        if m:
            q = item[:m.start()].strip()
            expected = item[m.end():].strip()
        else:
            lines = item.strip().split('\n', 1)
            if len(lines) != 2:
                continue
            q, expected = lines[0].strip(), lines[1].strip()
        if q and expected and len(expected) > 10:
            pairs.append({"q": q, "expected": expected})

    if not pairs:
        return None
    return pairs


def _parse_exam_answers_fallback(response: str, num_questions: int) -> Optional[List[Dict[str, str]]]:
    items = _parse_numbered_list(response, num_questions)
    if items is None:
        return None
    return [{"a": text} for text in items]


# Score extraction is ordered by reliability: an explicit "score:"/"ocena:"
# label wins, then an unambiguous decimal, then a leading bare 0/1. The old
# single regex matched any bare 0/1 anywhere in the line, so a stray digit in
# the explanation prose (e.g. "w 1 zdaniu") was mis-read as the score.
_LABELED_SCORE_RE = re.compile(
    r'(?:score|ocena)\s*[:=]?\s*(1\.0+|\d?\.\d+|[01])\b', re.IGNORECASE
)
_DECIMAL_SCORE_RE = re.compile(r'(?<![\d.])(1\.0+|\d?\.\d+)\b')
_LEADING_INT_SCORE_RE = re.compile(r'^[\s\-:.)\]]*([01])\b')


def _extract_score(item: str) -> Optional[Tuple[float, int]]:
    """Return (score in 0..1, end offset of matched token) or None."""
    for rx in (_LABELED_SCORE_RE, _DECIMAL_SCORE_RE, _LEADING_INT_SCORE_RE):
        m = rx.search(item)
        if m:
            try:
                val = float(m.group(1))
            except ValueError:
                return None
            return max(0.0, min(1.0, val)), m.end()
    return None


def _parse_exam_grading_fallback(response: str, num_questions: int) -> Optional[Dict[str, Any]]:
    items = _parse_numbered_list(response, num_questions, allow_partial=True)
    if items is None:
        return None
    graded: List[Dict[str, Any]] = []
    for item in items:
        res = _extract_score(item)
        if res is None:
            continue  # skip an unscoreable line instead of failing the batch
        score, end = res
        rest = item[end:].lstrip(" -:,.\n").strip()
        graded.append({"score": score, "explanation": rest or item.strip()})
    if not graded:
        return None
    final_score = sum(g["score"] for g in graded) / len(graded)
    return {"graded": graded, "final_score": round(final_score, 3)}


def answer_exam(context: str, questions: List[Dict[str, str]], llm_fn=None,
                concise: bool = False) -> Optional[List[Dict[str, str]]]:
    """
    Odpowiada na pytania egzaminacyjne.

    Args:
        context: Kontekst nauki
        questions: Lista pytań [{"q": "...", "expected": "..."}]
        llm_fn: Opcjonalna funkcja LLM (signature: fn(prompt) -> str).
                 Domyślnie call_ollama.
        concise: Gdy True, użyj zwięzłego promptu (jedno-faktowe odpowiedzi).
                 Dla held-out (deterministyczny grader) — szybciej i lepszy match.
                 Regularny egzamin (LLM grader) zostawia False (2-6 zdań).

    Returns:
        Lista odpowiedzi [{"a": "..."}] lub None
    """
    questions_list = "\n".join([f"{i+1}. {q.get('q', '?')}" for i, q in enumerate(questions)])

    _template = PROMPT_ANSWER_EXAM_CONCISE if concise else PROMPT_ANSWER_EXAM
    prompt = _template.format(
        context=context,
        questions_list=questions_list,
        num_questions=len(questions),
    )

    logger.debug(f"Odpowiadam na {len(questions)} pytań")

    _call = llm_fn if llm_fn is not None else call_ollama
    response = _call(prompt)
    if not response:
        return None

    parsed = extract_json_from_response(response, expected_keys={'answers'})
    if not parsed or 'answers' not in parsed:
        fallback = _parse_exam_answers_fallback(response, len(questions))
        if fallback:
            logger.info(f"[EXAM] Fallback: parsed {len(fallback)} answers from numbered text")
            return fallback
        logger.error("Brak pola 'answers' w odpowiedzi (fallback nie zadzialal)")
        return None

    answers = parsed['answers']
    if not isinstance(answers, list):
        logger.error(f"Pole 'answers' nie jest lista (type={type(answers).__name__})")
        return None

    expected = len(questions)
    actual = len(answers)
    if actual < expected:
        # Pad missing answers with empty placeholder — graceful degradation.
        # Empty answer will score 0 in grade_exam, which is the truthful outcome
        # when LLM silently dropped a question rather than fabricating one.
        padding = expected - actual
        answers = answers + [{"a": ""} for _ in range(padding)]
        logger.warning(
            f"[EXAM] LLM zwrocil {actual}/{expected} odpowiedzi — pad {padding} pustymi"
        )
    elif actual > expected:
        # Truncate over-count (rare; LLM hallucinated extra answers).
        extra = actual - expected
        answers = answers[:expected]
        logger.warning(
            f"[EXAM] LLM zwrocil {actual}/{expected} odpowiedzi — truncate {extra}"
        )

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

    final_score is ALWAYS recomputed from graded[] here -- the grader LLM's own
    final_score is discarded. Reason (production audit 2026-07-15): the prompt
    used to carry a worked example ending in "final_score": 0.83, and the model
    echoed that literal instead of averaging -- 447/1344 historical exams (33.3%)
    scored EXACTLY 0.83, and 52.5% disagreed with their own graded[] mean, which
    flipped 15 verdicts across the pass threshold. Both other graders
    (_parse_exam_grading_fallback, grade_heldout) already averaged; only this
    path trusted the model. Do not reintroduce a model-supplied final_score.
    """
    # Zbuduj pary pytanie-odpowiedź wzorcowa-odpowiedź ucznia
    qa_pairs = []
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        pair = f"Pytanie {i}: {q.get('q', '?')}\n"
        pair += f"Odpowiedź wzorcowa: {q.get('expected', '?')}\n"
        pair += f"Odpowiedź ucznia: {a.get('a', '?')}\n"
        qa_pairs.append(pair)

    qa_text = "\n".join(qa_pairs)

    prompt = PROMPT_GRADE_EXAM.format(qa_pairs=qa_text,
                                      num_questions=len(questions))

    logger.debug(f"Oceniam {len(questions)} odpowiedzi")

    _call = llm_fn if llm_fn is not None else call_ollama
    response = _call(prompt)  # bardzo niska temperatura dla konsystencji
    if not response:
        return None

    # 'graded' is the only required key -- final_score is computed, not parsed.
    parsed = extract_json_from_response(response, expected_keys={'graded'})
    if not parsed or 'graded' not in parsed:
        fallback = _parse_exam_grading_fallback(response, len(questions))
        if fallback:
            logger.info(f"[EXAM] Fallback: parsed grading for {len(fallback['graded'])} answers from text")
            return fallback
        logger.error("Brak wymaganych pól w ocenie (fallback nie zadzialal)")
        return None

    scored = _mean_of_graded(parsed.get('graded'), len(questions))
    if scored is None:
        fallback = _parse_exam_grading_fallback(response, len(questions))
        if fallback:
            logger.info(f"[EXAM] Fallback: graded[] unusable, parsed grading from text")
            return fallback
        logger.error("Oceny nie zawieraja zadnego uzytecznego score (fallback nie zadzialal)")
        return None

    graded, final_score = scored
    llm_claim = parsed.get('final_score')
    if isinstance(llm_claim, (int, float)) and not isinstance(llm_claim, bool):
        if abs(float(llm_claim) - final_score) > 0.005:
            logger.info(
                f"[EXAM] Grader final_score={llm_claim} rozjechany ze srednia "
                f"{final_score:.3f} - liczy sie srednia"
            )

    parsed['graded'] = graded
    parsed['final_score'] = final_score
    return parsed


def _mean_of_graded(graded: Any, num_questions: int) -> Optional[Tuple[List[Dict[str, Any]], float]]:
    """Average graded[] scores, padding missing per-question grades with 0.0.

    A grader that returns fewer grades than questions has silently dropped the
    questions it could not handle; averaging only what it returned would reward
    that omission (14 historical exams graded fewer answers than they asked).
    Missing grades therefore count as 0.0, mirroring answer_exam's under-count
    padding. Returns None when graded[] carries no usable score at all, so the
    caller can fall back to text parsing.
    """
    if not isinstance(graded, list):
        return None

    clean: List[Dict[str, Any]] = []
    for item in graded:
        if not isinstance(item, dict):
            continue
        score = item.get('score')
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        item = dict(item)
        item['score'] = max(0.0, min(1.0, float(score)))
        clean.append(item)

    if not clean:
        return None

    if 0 < len(clean) < num_questions:
        logger.warning(
            f"[EXAM] Grader ocenil {len(clean)}/{num_questions} pytan - "
            f"brakujace licze jako 0.0"
        )
        for _ in range(num_questions - len(clean)):
            clean.append({"score": 0.0,
                          "explanation": "brak oceny od egzaminatora"})
    elif len(clean) > num_questions > 0:
        logger.warning(
            f"[EXAM] Grader ocenil {len(clean)}/{num_questions} pytan - "
            f"nadmiarowe obcinam"
        )
        clean = clean[:num_questions]

    final_score = round(sum(g['score'] for g in clean) / len(clean), 3)
    return clean, final_score


def load_heldout_bank(bank_path: Path = HELDOUT_BANK) -> List[Dict[str, Any]]:
    """Load static held-out questions from JSONL, skipping malformed lines."""
    if not bank_path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(bank_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("heldout_bank.jsonl line %s: %s", line_no, exc)
                    continue
                if isinstance(row, dict) and row.get("q"):
                    rows.append(row)
    except OSError as exc:
        logger.warning("Cannot read heldout bank %s: %s", bank_path, exc)
    return rows


def select_heldout_rows(file_id: str, bank_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Select rows matching a file id directly, or a topic contained in the id.

    v3 rows (authored at fetch, C1) carry a ``source_hash``: a re-fetched body
    re-authors under a new hash, so grading uses ONLY the newest key -- answers
    graded against a stale body's facts would false-FAIL. v3 selection is also
    capped at 6 rows (EXAM_MAX_QUESTIONS parity: the student's 300s CPU answer
    budget). Legacy v2 rows (no hash) keep the old behavior byte-for-byte.
    """
    file_norm = _normalize_match_text(Path(file_id).stem.replace("_", " "))
    selected = []
    for row in bank_rows:
        row_file = row.get("file") or row.get("file_id")
        if row_file and str(row_file) == file_id:
            selected.append(row)
            continue
        topic = row.get("topic")
        if topic and _normalize_match_text(str(topic)) in file_norm:
            selected.append(row)
    hashed = [r for r in selected if r.get("source_hash")]
    if hashed:
        def _created_key(r):
            # Type-safe: a hand-edited row with a string created_at must not
            # TypeError the exam (the author always writes floats).
            v = r.get("created_at")
            return float(v) if isinstance(v, (int, float)) \
                and not isinstance(v, bool) else 0.0
        newest = max(hashed, key=_created_key)
        current = newest.get("source_hash")
        return [r for r in hashed if r.get("source_hash") == current][:6]
    return selected


def grade_heldout(
    bank_rows: List[Dict[str, Any]],
    answers: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Grade answers with a static answer key. No LLM, no network."""
    if not bank_rows:
        return None
    graded = []
    for idx, row in enumerate(bank_rows):
        answer = ""
        if idx < len(answers) and isinstance(answers[idx], dict):
            answer = str(answers[idx].get("a", ""))
        score, explanation = _score_heldout_answer(row, answer)
        graded.append({
            "score": score,
            "explanation": explanation,
            "match": row.get("match", "contains"),
            "bank_version": row.get("bank_version", "v1"),
        })
    final_score = sum(g["score"] for g in graded) / len(graded)
    return {"graded": graded, "final_score": round(final_score, 3)}


def _score_heldout_answer(row: Dict[str, Any], answer: str) -> Tuple[float, str]:
    match_type = str(row.get("match", "contains")).lower()
    canonical = str(row.get("canonical", ""))
    pattern = str(row.get("pattern", ""))
    answer_norm = _normalize_match_text(answer)
    canonical_norm = _normalize_match_text(canonical)

    if match_type == "exact":
        passed = bool(canonical_norm) and answer_norm == canonical_norm
        return _score(passed), "exact match" if passed else "exact mismatch"

    if match_type == "regex":
        rx = pattern or canonical
        try:
            passed = bool(rx) and re.search(rx, answer, flags=re.IGNORECASE) is not None
        except re.error as exc:
            return 0.0, f"invalid regex: {exc}"
        return _score(passed), "regex matched" if passed else "regex not matched"

    if match_type == "numeric":
        expected = _first_number(canonical or pattern)
        candidates = _all_numbers(answer)
        tolerance = float(row.get("tolerance", 0.0) or 0.0)
        # ANY number in the answer may match, not the first one found: concise
        # Polish answers routinely open with a year/date ("W 2029 roku ... 500000
        # USD"), and first-number matching graded the year against the price --
        # a systematic false-FAIL on exactly the market content the bank holds.
        matched = None
        if expected is not None:
            for cand in candidates:
                if abs(cand - expected) <= tolerance:
                    matched = cand
                    break
        passed = matched is not None
        closest = min(candidates, key=lambda c: abs(c - expected)) \
            if (candidates and expected is not None) else None
        detail = (
            f"numeric within tolerance ({matched} vs {expected}, tol={tolerance})"
            if passed else
            f"numeric mismatch (closest {closest} vs {expected}, tol={tolerance})"
        )
        return _score(passed), detail

    # Default: contains.
    passed = bool(canonical_norm) and canonical_norm in answer_norm
    return _score(passed), "contains canonical" if passed else "missing canonical"


def _score(passed: bool) -> float:
    return 1.0 if passed else 0.0


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


# Number shapes, most specific first so grouped forms win over their fragments:
#   1 234 567,89  - space/nbsp thousands (Polish print style; '68 250' must parse
#                   as 68250, not 68 -- red-team 2026-07-11 blocker)
#   1.234.567     - multi-group dot thousands
#   68250.5/68,25 - plain int/decimal; ',' and '.' both read as the decimal
#                   separator (Polish comma), single '68.250' stays 68.25
_NUMBER_RE = re.compile(
    "[-+]?\\d{1,3}(?:[ \u00a0]\\d{3})+(?:[,.]\\d+)?"  # space-grouped thousands
    "|[-+]?\\d{1,3}(?:\\.\\d{3}){2,}(?:,\\d+)?"      # multi-group dot thousands
    "|[-+]?\\d+(?:[,.]\\d+)?"                        # plain int / decimal
)


def _parse_number(token: str) -> Optional[float]:
    token = token.strip()
    if " " in token or "\u00a0" in token:
        # space-grouped: drop group separators, comma/dot is the decimal part
        token = token.replace(" ", "").replace("\u00a0", "")
    elif token.count(".") >= 2:
        # multi-group dot thousands: drop dots, comma is the decimal part
        token = token.replace(".", "")
    try:
        return float(token.replace(",", "."))
    except ValueError:
        return None


def _first_number(text: str) -> Optional[float]:
    for number in _iter_numbers(text):
        return number
    return None


def _all_numbers(text: str) -> List[float]:
    return list(_iter_numbers(text))


def _iter_numbers(text: str):
    for match in _NUMBER_RE.finditer(text):
        token = match.group(0)
        # Date-component guard: '2026-07-12' must not yield 7.0 and 12.0 --
        # a sign glued to the PREVIOUS digit is a date/range separator, and the
        # fragment behind it is junk that false-matches small-int canonicals.
        if token[0] in "+-" and match.start() > 0 \
                and text[match.start() - 1].isdigit():
            continue
        number = _parse_number(token)
        if number is not None:
            yield number


def check_for_looping(record: Dict[str, Any]) -> bool:
    """
    Sprawdza czy system się zapętlił (podobne wyniki egzaminów PONIŻEJ progu).

    Looping means STUCK: retried, and still not passing. Stable scores that PASS
    are mastery, not a loop -- branding them HARD_TOPIC drops the file from the
    candidate pool and costs the priority penalty for the crime of being learned.

    Before 2026-07-15 this checked similarity alone, and the grader echoed a
    literal 0.83 from its prompt (see grade_exam), so identical passing scores
    were the NORMAL case: all 3 files ever branded hard_topic had PASSED every
    exam -- e.g. expert_interpretacja.txt [0.83, 0.83, 0.83] -> HARD TOPIC
    (2026-07-15 09:47). The grader echo is fixed at the source; this gate is the
    second line of defence, so a future echo cannot brand good work again.

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
        if max_diff < 0.05 and max(recent) < EXAM_PASS_THRESHOLD:
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


def _execute_exam(file_id, memory_path, llm_fn=None, grader_llm_fn=None,
                  generator_llm_fn=None):
    """
    Run the 3-step exam pipeline: generate -> answer -> grade.

    Independent verification (keystone, 2026-05-30): the EXAMINER (grader_llm_fn,
    e.g. NIM nemotron) writes the questions + rubric AND grades, while the STUDENT
    (llm_fn, the local model) answers blind (answer_exam never shows the student
    the expected answers). This makes the score measure real capability instead
    of one model agreeing with its own expected answers. When grader_llm_fn is
    None it falls back to llm_fn for all three steps (the old self-graded
    behaviour) -- the caller flags such a run as non-independent.

    Returns:
        (score, exam_questions, answers, grading) or (None, ...) on failure
    """
    memories = get_memories_for_file(file_id, memory_path)
    if not memories:
        logger.error(f"Brak pamięci dla {file_id}!")
        return None, None, None, None

    context = build_context_from_memories(memories, max_chars=EXAM_CONTEXT_MAX_CHARS)
    num_questions = calculate_num_questions(len(memories))

    # Examiner authors + grades; student answers. Fall back to one model (self-
    # graded) only when no independent grader was supplied.
    examiner_fn = grader_llm_fn or llm_fn

    # The question AUTHOR may differ from the GRADER. Authoring a ~12-question
    # exam is a heavy generation that chronically timed out on the contended
    # local CPU (incident 2026-06-04: 20/20 exams failed, examiner=qwen3, 240s
    # x3). Routing authoring to a fast off-CPU model (NIM) fixes that, while
    # GRADING stays on the local independent grader (qwen3) -- NIM grading
    # measured ~85s for 3 questions, so it would blow the timeout on a full
    # rubric. When no separate author is supplied this is the old behaviour.
    author_fn = generator_llm_fn or examiner_fn

    exam = generate_exam(context, num_questions, llm_fn=author_fn)
    if not exam:
        logger.error("Nie udalo sie wygenerowac egzaminu")
        return None, None, None, None

    # concise=True (2026-06-06): verbose answers (2-6 zdan x 6 = ~1000 tok) ran
    # ~180s of OUTPUT alone on CPU; with the ~180s INPUT prompt-eval that put a
    # single answer at ~381s -> over any sane timeout (the 2nd storm root). The
    # LLM grader scores fact correctness, so a concise fact/number answer (~3x
    # less output) measures retention just as well -- answer drops to ~207s.
    answers = answer_exam(context, exam, llm_fn=llm_fn, concise=True)
    if not answers:
        logger.error("Nie udalo sie odpowiedziec na egzamin")
        return None, exam, None, None

    grading = grade_exam(exam, answers, llm_fn=examiner_fn)
    if not grading:
        logger.error("Nie udalo sie ocenic egzaminu")
        return None, exam, answers, None

    return grading['final_score'], exam, answers, grading


def _execute_heldout_exam(
    file_id: str,
    memory_path: Path,
    bank_rows: List[Dict[str, Any]],
    llm_fn=None,
    semantic_memory=None,
):
    """
    Run held-out static exam: bank questions -> student answers -> Python grade.

    When ``semantic_memory`` is wired the student answers CLOSED-BOOK: its
    context is built by real retrieval over ALL learned summaries (the production
    recall path) instead of being spoon-fed this file's own summary (open-book).
    Production passes None -> open-book (C5); closed-book is a drill mode. An
    alpha control (empty context = bare parametric knowledge) is scored in BOTH
    modes, so context lift / parroting rate is always measurable.

    Returns the same tuple as _execute_exam:
        (score, exam_questions, answers, grading) or (None, ...) on failure.
    """
    if not bank_rows:
        logger.info("[HELDOUT] No held-out rows for %s", file_id)
        return None, None, None, None

    exam = [
        {
            "q": str(row.get("q", "")),
            "expected": str(row.get("canonical") or row.get("pattern") or ""),
            "heldout": True,
            "bank_version": row.get("bank_version", "v1"),
        }
        for row in bank_rows
        if row.get("q")
    ]
    if not exam:
        return None, None, None, None

    # Student context: CLOSED-BOOK retrieval (beta) when a semantic memory is
    # wired, else OPEN-BOOK (this file's own learned summary). Production
    # (2026-07-12, C5): the teacher passes semantic_memory=None for held-out
    # drills -> open-book; closed-book stays a drill mode (offline scripts).
    closed_book = semantic_memory is not None
    context = ""
    if closed_book:
        context = build_context_from_retrieval(semantic_memory, exam)
        if not context:
            # Guard: a fresh file's summary chunks are indexed only at boot
            # (index_summaries has one call site, run_initial_indexing), so
            # closed-book retrieval can come back EMPTY -- grading a blind
            # student against the bank would be a guaranteed FAIL and, via B4
            # retries, a burn loop. Fall back to open-book and say so.
            logger.warning(
                "[HELDOUT] closed-book retrieval empty for %s; "
                "falling back to open-book", file_id,
            )
            closed_book = False
    if not closed_book:
        memories = get_memories_for_file(file_id, memory_path)
        if not memories:
            logger.error(f"Brak pamięci dla {file_id}!")
            return None, None, None, None
        context = build_context_from_memories(memories, max_chars=EXAM_CONTEXT_MAX_CHARS)

    answers = answer_exam(context, exam, llm_fn=llm_fn, concise=True)
    if not answers:
        logger.error("Nie udalo sie odpowiedziec na held-out exam")
        return None, exam, None, None

    grading = grade_heldout(bank_rows, answers)
    if not grading:
        logger.error("Nie udalo sie ocenic held-out exam")
        return None, exam, answers, None

    # Provenance + alpha control (EMPTY context = bare parametric knowledge).
    # Diagnostic only; the reported score stays the contextful run. Runs in
    # BOTH modes (C5, 2026-07-12): open-book contains-grading over a handed
    # summary is the most parroting-prone configuration, so score-vs-alpha is
    # exactly the parroting-rate measurement calibration (C7) needs. The extra
    # student call is cheap: empty context = tiny prompt-eval, concise output.
    grading["closed_book"] = closed_book
    grading["context_chars"] = len(context)
    try:
        alpha_answers = answer_exam("", exam, llm_fn=llm_fn, concise=True)
        alpha_grading = grade_heldout(bank_rows, alpha_answers) if alpha_answers else None
        grading["alpha_score"] = (
            alpha_grading["final_score"] if alpha_grading else None
        )
    except Exception as e:
        logger.warning(f"[HELDOUT] alpha control failed: {e}")
        grading["alpha_score"] = None

    return grading["final_score"], exam, answers, grading


def _update_status_after_exam(target, final_score, passed, is_spaced_repetition,
                              heldout=False):
    """
    Update file status in index based on exam result.

    Rules:
    - held-out fail: status untouched (C5, red-team 2026-07-11: a B4 drill sets
      is_spaced, whose fail branch stamped COMPLETED on a LEARNED file -- an
      index lie -- and auto-select fails branded fresh files HARD_TOPIC; the
      held-out verdict lives in exam_results, the index must not lie for it)
    - spaced repetition: always keep COMPLETED
    - passed: COMPLETED
    - 1st fail: EXAM_FAILED (second chance)
    - 2nd+ fail or looping: HARD_TOPIC

    is_spaced_repetition means "this file was ALREADY completed and is being
    re-examined" -- keeping COMPLETED then is honest, because a shaky rerun does
    not unlearn the material. It must NOT mean "a caller named a file": every
    production caller names one, which turned this branch into an unconditional
    COMPLETED stamp applied before `passed` was ever consulted (fixed 2026-07-15).
    """
    target['exam_attempts'] += 1
    target['last_scores'].append(final_score)

    if heldout:
        # Held-out verdicts must not mutate index status beyond the honest
        # minimum: FAIL leaves status untouched; PASS promotes to COMPLETED and
        # SKIPS check_for_looping below -- repeated similar held-out scores are
        # a property of mechanical grading, and a HARD_TOPIC brand would drop
        # the file from the 'completed' bucket, silently wedging the heldout
        # goal's verified/N credit (diff-review 2026-07-12).
        if passed:
            target['status'] = STATUS_COMPLETED
            logger.info(f"[HELDOUT PASS] Egzamin held-out ZALICZONY ({final_score:.2%})")
        else:
            logger.warning(
                f"[HELDOUT FAIL] Egzamin held-out NIEZALICZONY ({final_score:.2%}) "
                f"- status bez zmian"
            )
        target['updated_at'] = get_timestamp()
        return

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
    grader_llm_fn=None,
    generator_llm_fn=None,
    grader_meta: Optional[Dict[str, Any]] = None,
    use_heldout: bool = False,
    heldout_bank_path: Optional[Path] = None,
    semantic_memory=None,
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

    # Spaced repetition = re-examining material ALREADY passed. Captured here,
    # before anything can mutate the record. Do NOT infer it from
    # target_file_id: production always names a file (teacher_module.py:487,
    # synthesis, /egzamin), so that test called every first exam a repeat and
    # stamped COMPLETED on files that had just failed their only exam
    # (audit 2026-07-15: web_rss_francuski_naukowiec, 0.55 vs 0.6 threshold,
    # indexed as completed).
    is_spaced = target.get('status') == STATUS_COMPLETED

    logger.info(f"[EXAM] Egzamin z: {file_id}")

    # 2. Execute exam pipeline
    used_heldout = False
    heldout_fallback = False
    if use_heldout:
        bank_rows = select_heldout_rows(
            file_id,
            load_heldout_bank(heldout_bank_path or HELDOUT_BANK),
        )
        if len(bank_rows) >= HELDOUT_MIN_BANK_ROWS:
            # C9 arming marker: greppable in journalctl, so the FIRST
            # mechanically graded exam after a flip is identifiable.
            logger.info(
                "[HELDOUT] armed: mechanical grading for %s (%d bank rows)",
                file_id, len(bank_rows),
            )
            final_score, exam, answers, grading = _execute_heldout_exam(
                file_id, memory_path, bank_rows, llm_fn=llm_fn,
                semantic_memory=semantic_memory,
            )
            used_heldout = True
        else:
            # C3: no silent identity-blur -- a caller asked for the mechanical
            # grader and did not get it. WARNING (greppable) + stamped in the
            # record below, so the fallback rate is visible in the trust data.
            heldout_fallback = True
            logger.warning(
                "[HELDOUT] %d bank rows for %s (min %d); falling back to LLM "
                "examiner", len(bank_rows), file_id, HELDOUT_MIN_BANK_ROWS,
            )
            final_score, exam, answers, grading = _execute_exam(
                file_id, memory_path, llm_fn, grader_llm_fn=grader_llm_fn,
                generator_llm_fn=generator_llm_fn,
            )
    else:
        final_score, exam, answers, grading = _execute_exam(
            file_id, memory_path, llm_fn, grader_llm_fn=grader_llm_fn,
            generator_llm_fn=generator_llm_fn,
        )
    if final_score is None:
        # Loop guard: spaced-repetition scheduler sorts by updated_at ASC and re-picks
        # the same file every cycle if updated_at stays stale. Bumping it pushes this
        # file to the back of the queue so the planner can make progress on other work.
        target['updated_at'] = get_timestamp()
        save_index(index, index_path)
        logger.warning(
            f"[EXAM] Pipeline failed for {file_id}; bumped updated_at to defer re-selection"
        )
        return no_exam

    passed = final_score >= EXAM_PASS_THRESHOLD
    logger.info(f"[SCORE] Wynik egzaminu: {final_score:.2%}")

    # 3. Save exam result
    _gm = grader_meta or {}
    # Actual-backend cells (see teacher_module._make_nim_first_examiner_fn):
    # read AFTER grading, so the record shows which model REALLY authored and
    # graded ("nim:<model>" / "local:<model>") instead of the constant planned
    # label -- the NIM-vs-fallback split used to be invisible in trust data.
    _grader_cell = _gm.get("grader_cell") or {}
    _author_cell = _gm.get("author_cell") or {}
    grader_model = _grader_cell.get("backend") or _gm.get("grader")
    author_model = _author_cell.get("backend")
    if used_heldout:
        _gm = {
            "independent": True,
            "grader": HELDOUT_GRADER_MODEL,
            "student": _gm.get("student") or ollama_model,
        }
        grader_model = HELDOUT_GRADER_MODEL
        author_model = None  # questions come from the frozen bank, not an LLM
    append_exam_result({
        "file": file_id,
        "timestamp": get_timestamp(),
        "attempt": target['exam_attempts'] + 1,
        "score": final_score,
        "num_questions": len(exam),
        "questions": exam,
        "answers": answers,
        "grading": grading['graded'],
        # Keystone provenance: was this graded by an INDEPENDENT model (not the
        # student grading its own homework)? Makes score trustworthiness visible.
        "grader_independent": bool(_gm.get("independent", False)),
        "grader_model": grader_model,
        "author_model": author_model,
        "student_model": _gm.get("student"),
        # Closed-book (retrieval) provenance + alpha control (empty-context score)
        "closed_book": bool(grading.get("closed_book", False)),
        "alpha_score": grading.get("alpha_score"),
        # C3: held-out was requested but the bank had too few rows -> the LLM
        # examiner graded instead. Without this stamp such a record is
        # bit-identical to a regular exam and the fallback rate is invisible.
        "heldout_fallback": heldout_fallback,
    }, exam_path)

    # 4. Update status (is_spaced captured pre-exam, see above)
    _update_status_after_exam(target, final_score, passed, is_spaced,
                              heldout=used_heldout)
    save_index(index, index_path)

    return {"executed": True, "passed": passed, "score": final_score,
            "file_id": file_id, "heldout_fallback": heldout_fallback}
