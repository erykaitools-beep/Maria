"""
LLM utilities for Maria's learning pipeline.

Shared by: learning_agent, exam_agent, priority_scheduler.
Extracted from learning_agent.py to eliminate spaghetti imports.
"""

import re
import requests
import json
import logging
from typing import Dict, Any, Optional

from maria_core.sys.config import (
    OLLAMA_MODEL,
    OLLAMA_HOST,
    OLLAMA_TIMEOUT,
    OLLAMA_TEMPERATURE,
    MAX_RETRIES_OLLAMA,
)

logger = logging.getLogger(__name__)


def call_ollama(prompt: str, model: str = OLLAMA_MODEL, temperature: float = OLLAMA_TEMPERATURE) -> Optional[str]:
    """
    Wywoluje Ollama API z obsluga bledow i retry.

    Args:
        prompt: Prompt dla modelu
        model: Nazwa modelu
        temperature: Temperatura generowania

    Returns:
        Odpowiedz modelu (string) lub None w razie bledu
    """
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",  # Force JSON output mode (Ollama native)
        "options": {
            "temperature": temperature,
            "num_ctx": 4096,
        }
    }

    for attempt in range(MAX_RETRIES_OLLAMA):
        try:
            response = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            return result.get('response', '').strip()
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama timeout (proba {attempt + 1}/{MAX_RETRIES_OLLAMA})")
            if attempt == MAX_RETRIES_OLLAMA - 1:
                logger.error("Ollama nie odpowiada po wszystkich probach")
                return None
        except Exception as e:
            logger.error(f"Blad wywolania Ollama: {e}")
            return None

    return None


def _parse_markdown_to_learning_dict(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse markdown/text response into learning dict when LLM ignores JSON format.

    Extracts summary (first paragraph or bold section), key_points (bullet points),
    tags (from Keywords/Tags section or inferred), and questions if present.

    Returns dict with 'summary', 'key_points', 'tags' or None if extraction fails.
    """
    if not text or len(text) < 50:
        return None

    lines = text.strip().split('\n')
    summary_parts = []
    key_points = []
    tags = []
    questions = []
    current_section = 'summary'

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        # Detect section headers (bold or plain)
        if any(kw in lower for kw in ['kluczowe punkty', 'key_points', 'bullet', 'kluczowe informacje']):
            current_section = 'points'
            continue
        if any(kw in lower for kw in ['tag', 'keyword', 'pojec', 'slowa kluczowe']):
            current_section = 'tags'
            continue
        if any(kw in lower for kw in ['pytani', 'question', 'sprawdzaj']):
            current_section = 'questions'
            continue
        if any(kw in lower for kw in ['streszczenie', 'summary', 'podsumowanie']):
            current_section = 'summary'
            continue

        # Clean markdown formatting
        clean = re.sub(r'\*\*(.+?)\*\*', r'\1', stripped)  # **bold**
        clean = re.sub(r'^\*\s+', '', clean)  # * bullet
        clean = re.sub(r'^-\s+', '', clean)   # - bullet
        clean = re.sub(r'^\d+\.\s+', '', clean)  # 1. numbered
        clean = clean.strip()
        if not clean:
            continue

        if current_section == 'summary':
            # First section header switches to points
            if stripped.startswith('*') or stripped.startswith('-') or re.match(r'^\d+\.', stripped):
                current_section = 'points'
                key_points.append(clean)
            else:
                summary_parts.append(clean)
        elif current_section == 'points':
            key_points.append(clean)
        elif current_section == 'tags':
            # Tags can be comma-separated or one per line
            for tag in re.split(r'[,;]', clean):
                tag = tag.strip().strip('"').strip("'")
                if tag and len(tag) < 50:
                    tags.append(tag)
        elif current_section == 'questions':
            questions.append(clean)

    summary = ' '.join(summary_parts).strip()
    if not summary and key_points:
        summary = key_points[0]

    # Need at least summary or key_points
    if not summary and not key_points:
        return None

    # If no tags extracted, take first words from key_points
    if not tags and key_points:
        for kp in key_points[:5]:
            words = kp.split()[:2]
            if words:
                tags.append(' '.join(words))

    result = {
        "summary": summary[:2000],
        "key_points": key_points[:15],
        "tags": tags[:15],
    }
    if questions:
        result["questions"] = questions[:5]

    return result


def extract_json_from_response(response: str) -> Optional[Dict[str, Any]]:
    """
    Wyciaga JSON z odpowiedzi modelu (obsluguje markdown ```json```).
    Zwraca dict albo None.
    """
    # 0. Bezpiecznik na None / pusty tekst
    if response is None:
        logger.error("[JSON] Otrzymano None zamiast tekstu odpowiedzi.")
        return None

    response = response.strip()
    if not response:
        logger.error("[JSON] Pusta odpowiedz z modelu - brak tresci do parsowania.")
        return None

    original_response = response  # kopia do logow

    # 1. Obsluga blokow ```json ... ``` (gdziekolwiek w tekscie)
    md_match = re.search(r'```(?:json)?\s*(.+?)\s*```', response, re.DOTALL | re.IGNORECASE)
    if md_match:
        response = md_match.group(1).strip()

    # 2. Pierwsza proba: caly tekst jako JSON
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        logger.warning(f"[JSON] Nie udalo sie sparsowac pelnej odpowiedzi jako JSON: {e}")

    # 3. Druga proba: fragment miedzy pierwszym '{{' a ostatnim '}}'
    start = response.find("{")
    end = response.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = response[start:end+1].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            logger.warning(f"[JSON] Nie udalo sie sparsowac wycinka {{...}}: {e}")

    # 3b. Fallback: sprobuj na ORYGINALNEJ odpowiedzi (przed ekstrakcja markdown)
    if response != original_response:
        start = original_response.find("{")
        end = original_response.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = original_response[start:end+1].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    # 4. Fallback: parsuj markdown/tekst do struktury JSON
    result = _parse_markdown_to_learning_dict(original_response)
    if result:
        logger.info(f"[JSON] Fallback: sparsowano markdown do JSON (keys: {list(result.keys())})")
        return result

    # 5. Ostatecznie: oddaj None
    logger.error(f"[JSON] Nie udalo sie wyciagnac JSON ani markdown. Odpowiedz ({len(original_response)} chars): {original_response[:200]}...")
    return None
