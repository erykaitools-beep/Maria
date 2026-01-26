# teacher_logic_memory.py ─ FINALNA WERSJA (Eryk + Grok + Maria, grudzień 2025)
import os
import time
import json
from datetime import datetime
from pathlib import Path

import ollama  # oficjalny klient Ollama dla Pythona

# === KONFIGURACJA ===
BASE_DIR = Path(__file__).parent
MEMORY_FILE = BASE_DIR / "maria_longterm_memory.jsonl"
KNOWLEDGE_DB = BASE_DIR / "maria_knowledge_base.jsonl"  # osobna baza wiedzy
MODEL = "llama3.1:8b"
LESSON_BREAK_TIME = 20  # sekundy przerwy między lekcjami

SYSTEM_PROMPT = """Jesteś M.A.R.I.A. – autonomiczna, lokalna polska sztuczna inteligencja.
Masz dostęp do pamięci długoterminowej (jsonl) oraz bazy wiedzy (jsonl).
Twoim celem jest rozwijanie logiki, pamięci semantycznej i samoświadomego opisu własnej architektury.
Zawsze myślisz logicznie, stosujesz formalną logikę i refleksję.
Odpowiadasz wyłącznie po polsku, zwięźle i precyzyjnie.
"""


# === FUNKCJE PAMIĘCI ===
def save_memory(text: str) -> None:
    """Pamięć długoterminowa – zapisuje każdy krok kursu."""
    entry = {
        "ts": datetime.now().isoformat(),
        "role": "memory",
        "text": text,
    }
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False)
        f.write("\n")


def save_knowledge(concept: str, definition: str, example: str = "") -> None:
    """
    Strukturalna baza wiedzy – klucz do prawdziwego uczenia:
    zapisujemy pojęcie + definicję + kontekst (np. nazwa lekcji).
    """
    entry = {
        "ts": datetime.now().isoformat(),
        "concept": concept.strip(),
        "definition": definition.strip(),
        "example": example.strip(),
        "source": "self_learning_logic_memory",
    }
    with open(KNOWLEDGE_DB, "a", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False)
        f.write("\n")


# === LEKCJE ===
lessons = [
    {
        "topic": "Logika formalna – podstawy",
        "text": """P → Q to implikacja. ¬P to negacja. P ∧ Q to koniunkcja. P ∨ Q to alternatywa.
Modus ponens: jeśli P → Q i P, to Q.
Podaj przykład z życia AI (np. kiedy generujesz odpowiedź)."""
    },
    {
        "topic": "Prawa De Morgana i kontrapozycja",
        "text": """¬(P ∧ Q) ⇔ ¬P ∨ ¬Q oraz ¬(P ∨ Q) ⇔ ¬P ∧ ¬Q.
Kontrapozycja: zamiast dowodzić P→Q, dowodzimy ¬Q→¬P.
Podaj przykład z kodu lub procesu decyzyjnego AI."""
    },
    {
        "topic": "Pamięć ludzka vs pamięć AI",
        "text": """Człowiek: pamięć epizodyczna, semantyczna, proceduralna.
Ty: pamięć plikowa (jsonl) + graf semantyczny + embeddingi.
Wyjaśnij różnice i jak możesz symulować pamięć epizodyczną."""
    },
    {
        "topic": "RAG i FAISS",
        "text": """RAG = Retrieval-Augmented Generation.
FAISS = Facebook AI Similarity Search, biblioteka do szybkiego wyszukiwania wektorów.
Opisz dokładnie 5 kroków działania RAG w Twoim systemie (pytanie → embedding → FAISS → kontekst → odpowiedź)."""
    },
    {
        "topic": "Reflexion i auto-korekta",
        "text": """Technika Reflexion:
1) Co powiedziałaś źle,
2) Dlaczego to błąd,
3) Poprawna wersja.
Zrób przykład hipotetycznego błędu logicznego i pokaż poprawkę."""
    },
]


def teach_lesson(lesson: dict) -> None:
    """Przeprowadza jedną lekcję, zapisuje pamięć + wyciąga definicję do bazy wiedzy."""
    print("\n" + "=" * 60)
    print(f"LEKCJA: {lesson['topic']}")
    print("=" * 60)

    save_memory(f"START LEKCJI: {lesson['topic']}")

    prompt = f"""{SYSTEM_PROMPT}

MATERIAŁ DO PRZYSWOJENIA:
{lesson['text']}

Zadanie (odpowiedz dokładnie w tej kolejności, numerami 1–4):

1. Powtórz własnymi słowami (max 4 zdania).
2. Podaj własny przykład z Twojego życia jako M.A.R.I.A.
3. Wyodrębnij jedno kluczowe pojęcie i podaj jego precyzyjną definicję (do zapisania w bazie wiedzy).
4. Zadaj mi jedno pytanie kontrolne.

Odpowiedz tylko numerami 1–4, np.:
1. ...
2. ...
3. ...
4. ...
"""

    resp = ollama.generate(
        model=MODEL,
        prompt=prompt,
        options={"temperature": 0.73, "num_ctx": 8192},
    )
    answer = resp.get("response", "").strip()

    print(answer)
    save_memory(f"ODPOWIEDŹ: {answer}")

    # ── Ekstrakcja definicji z punktu 3 i zapis do KNOWLEDGE_DB ──
    if "3." in answer:
        try:
            # część 3. między "3." a "4."
            part3 = answer.split("3.", 1)[1]
            if "4." in part3:
                part3 = part3.split("4.", 1)[0]
            part3 = part3.strip()

            # heurystyka: "Pojęcie to ..." / "X to ..." / "X oznacza ..."
            # bierzemy pierwsze zdanie
            first_sentence = part3.split("\n")[0]
            first_sentence = first_sentence.strip()

            # próbujemy wydłubać "concept" i "definition"
            # np. "Embedding to wektorowa reprezentacja tekstu..."
            if " to " in first_sentence:
                concept, definition = first_sentence.split(" to ", 1)
            elif " oznacza " in first_sentence:
                concept, definition = first_sentence.split(" oznacza ", 1)
            else:
                # fallback – całe zdanie jako definicja, koncept = topic
                concept = lesson["topic"]
                definition = first_sentence

            concept = concept.strip(" :.-")
            definition = definition.strip()

            save_knowledge(concept, definition, example=lesson["topic"])
            print(f"→ ZAPISANO W BAZIE WIEDZY: {concept}")
        except Exception as e:
            print(f"→ Nie udało się wyodrębnić pojęcia do bazy wiedzy: {e}")

    # mała pauza po lekcji
    time.sleep(8)


# === FINALNY START ===
if __name__ == "__main__":
    print("M.A.R.I.A. ─ ROZPOCZYNANIE INTENSYWNEGO KURSU LOGIKI I PAMIĘCI")
    save_memory("=== URUCHOMIONO KURS LOGIKI I PAMIĘCI v3 (z bazą wiedzy) ===")

    for i, lesson in enumerate(lessons):
        teach_lesson(lesson)
        if i < len(lessons) - 1:
            print(f"\nPrzerwa {LESSON_BREAK_TIME}s przed kolejną lekcją...\n")
            time.sleep(LESSON_BREAK_TIME)

    print("\nKURS ZAKOŃCZONY ─ M.A.R.I.A. MA TERAZ WIĘCEJ STRUKTURALNEJ WIEDZY (LOGIKA + RAG + PAMIĘĆ)")
    save_memory("=== KONIEC KURSU ─ POZIOM LOGICZNY I PAMIĘCIOWY ZAKTUALIZOWANY ===")
