"""
Text chunking for Maria's learning pipeline.

Splits long text into overlapping chunks at natural boundaries
(paragraphs, sentences) for incremental learning.

Extracted from learning_agent.py.
"""

import logging
from typing import List, Tuple

from maria_core.sys.config import (
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    TARGET_CHUNK_SIZE,
    CHUNK_OVERLAP,
    CHUNK_SEPARATORS,
)

logger = logging.getLogger(__name__)


def intelligent_chunk_text(text: str) -> List[Tuple[str, int, int]]:
    """
    Inteligentny podzial tekstu na chunki z overlapem.

    Priorytetyzuje naturalne granice (paragrafy, zdania) zamiast sztywnego podzialu.

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
        # Okresl koniec chunka
        end = min(start + TARGET_CHUNK_SIZE, len(text))

        # Jesli to nie koniec tekstu, znajdz najlepszy punkt podzialu
        if end < len(text):
            best_split = end

            # Szukaj separatorow w kolejnosci priorytetu
            for separator in CHUNK_SEPARATORS:
                # Szukaj w oknie [end-200, end+200]
                search_start = max(end - 200, start)
                search_end = min(end + 200, len(text))
                search_text = text[search_start:search_end]

                # Znajdz ostatnie wystapienie separatora
                sep_pos = search_text.rfind(separator)
                if sep_pos != -1:
                    actual_pos = search_start + sep_pos + len(separator)
                    # Sprawdz czy nie za maly/duzy chunk
                    chunk_size = actual_pos - start
                    if MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE * 1.5:
                        best_split = actual_pos
                        break

            end = best_split

        # Wytnij chunk
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append((chunk_text, start, end))

        # Nastepny chunk z overlapem
        # KLUCZOWE: start musi ZAWSZE przesunac sie do przodu
        prev_start = start
        start = end - CHUNK_OVERLAP

        # Zabezpieczenie przed nieskonczona petla:
        if start <= prev_start:
            start = prev_start + max(MIN_CHUNK_SIZE, 1)

        # Hard limit: max 100 chunkow (bezpiecznik)
        if len(chunks) >= 100:
            logger.warning(
                f"Chunk limit (100) reached for text of {len(text)} chars, stopping"
            )
            break

    logger.debug(f"Podzielono tekst na {len(chunks)} chunkow")
    return chunks
