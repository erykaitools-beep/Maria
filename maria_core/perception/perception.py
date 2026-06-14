"""
DEAMONMARIA V2 - Perception Module
Skanowanie folderów input/ i budowa indeksu wiedzy.
Wykrywanie nowych plików, zmian i inteligentna analiza struktury.
"""

import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from maria_core.sys.config import (
    STATUS_NEW,
    STATUS_LEARNING,
    STATUS_DUPLICATE,
    get_timestamp,
    PRIORITY_BONUS_KEYWORDS,
    INPUT_DIR,
    KNOWLEDGE_INDEX,  # BUG-004 FIX: uzyj stałej z config zamiast hardcoded path
)
from maria_core.memory_engine.memory_store import load_index, save_index

logger = logging.getLogger(__name__)


def calculate_file_hash(filepath: Path) -> str:
    """
    Oblicza SHA256 hash pliku dla wykrywania zmian.

    Args:
        filepath: Ścieżka do pliku

    Returns:
        Hash jako hex string
    """
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"Błąd obliczania hash dla {filepath}: {e}")
        return ""


# P5 (#4): the web_source fetcher (content_writer.py) prepends a metadata header
# terminated by a "# ---" separator; its URL and "Pobrano" date differ on every
# fetch, so a whole-file hash (calculate_file_hash) never matches the SAME
# article re-fetched under a new slug/title. Hash only the body after the
# separator so identical content dedups across different filenames. Files with
# no such header (e.g. expert_*, manual notes) hash whole. Kept independent of
# content_writer.HEADER_SEPARATOR on purpose: maria_core must not import from
# agent_core, and the no-marker fallback is safe.
_BODY_HEADER_MARKER = "# ---"


def calculate_body_hash(filepath: Path) -> str:
    """SHA256 of the content body, excluding any web_source metadata header."""
    try:
        text = filepath.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        logger.error(f"Błąd obliczania body-hash dla {filepath}: {e}")
        return ""
    idx = text.find(_BODY_HEADER_MARKER)
    if idx != -1:
        newline = text.find("\n", idx)
        if newline != -1:
            text = text[newline + 1:]
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def analyze_file_structure(filepath: Path) -> Dict[str, Any]:
    """
    Analizuje strukturę pliku tekstowego.

    Wykrywa:
    - Liczbę linii/akapitów
    - Nagłówki (linie kończące się na ":" lub zaczynające od "#")
    - Listy (linie zaczynające od "-", "*", cyfry+".")
    - Gęstość semantyczną (unikalne słowa / całość)

    Args:
        filepath: Ścieżka do pliku

    Returns:
        Słownik z metrykami struktury
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n')
        paragraphs = [p for p in content.split('\n\n') if p.strip()]

        # Wykrywanie nagłówków
        headers = []
        for line in lines:
            stripped = line.strip()
            if stripped and (
                stripped.endswith(':') or 
                stripped.startswith('#') or
                stripped.startswith('==') or
                stripped.startswith('--')
            ):
                headers.append(stripped)

        # Wykrywanie list
        list_items = 0
        for line in lines:
            stripped = line.strip()
            if stripped and (
                stripped.startswith('- ') or
                stripped.startswith('* ') or
                (len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in '.)')
            ):
                list_items += 1

        # Gęstość semantyczna
        words = content.lower().split()
        unique_words = set(words)
        semantic_density = len(unique_words) / max(len(words), 1)

        # Unikalne terminy techniczne (słowa >6 znaków, nie powszechne)
        technical_terms = [w for w in unique_words if len(w) > 6 and w.isalpha()]

        return {
            "total_chars": len(content),
            "total_lines": len(lines),
            "total_paragraphs": len(paragraphs),
            "headers_count": len(headers),
            "list_items_count": list_items,
            "semantic_density": round(semantic_density, 3),
            "unique_terms_count": len(technical_terms),
            "structure_score": len(headers) * 2 + list_items  # wyższa wartość = lepsza struktura
        }
    except Exception as e:
        logger.error(f"Błąd analizy struktury {filepath}: {e}")
        return {
            "total_chars": 0,
            "total_lines": 0,
            "total_paragraphs": 0,
            "headers_count": 0,
            "list_items_count": 0,
            "semantic_density": 0.0,
            "unique_terms_count": 0,
            "structure_score": 0
        }


def calculate_initial_priority(filepath: Path, folder: str, filename: str) -> float:
    """
    Oblicza wstępny priorytet na podstawie rozmiaru, nazwy i struktury.

    Skala: 0-100 (wyższy = ważniejszy)

    Args:
        filepath: Pełna ścieżka do pliku
        folder: Nazwa folderu
        filename: Nazwa pliku

    Returns:
        Priorytet (0-100)
    """
    priority = 50.0  # bazowy priorytet

    # Analiza struktury
    structure = analyze_file_structure(filepath)

    # 1. Bonus za rozmiar (mniejszy plik = wyższy priorytet)
    chars = structure['total_chars']
    if chars < 5000:
        priority += 15
    elif chars < 10000:
        priority += 10
    elif chars < 20000:
        priority += 5
    else:
        priority += 0  # duże pliki na później

    # 2. Bonus za strukturę (więcej nagłówków/list = lepiej)
    if structure['structure_score'] > 10:
        priority += 10
    elif structure['structure_score'] > 5:
        priority += 5

    # 3. Bonus za gęstość semantyczną (więcej unikalnych słów = ważniejszy)
    if structure['semantic_density'] > 0.4:
        priority += 8
    elif structure['semantic_density'] > 0.3:
        priority += 4

    # 4. Bonus za słowa kluczowe w nazwie
    full_name = f"{folder}/{filename}".lower()
    for keyword, bonus in PRIORITY_BONUS_KEYWORDS.items():
        if keyword.lower() in full_name:
            priority += bonus
            logger.debug(f"Keyword '{keyword}' w {filename}: +{bonus} priority")

    # Ogranicz do 0-100
    return max(0, min(100, priority))


def scan_input_directory(base_dir: Path, index_path: Path) -> Dict[str, int]:
    """
    Skanuje katalog input/ i aktualizuje indeks wiedzy.

    Dla każdego pliku .txt:
    - Sprawdza czy istnieje w indeksie
    - Jeśli nie: dodaje nowy rekord
    - Jeśli tak: sprawdza hash (czy się zmienił)

    Args:
        base_dir: Ścieżka do katalogu bazowego (INPUT_DIR)
        index_path: Ścieżka do knowledge_index.jsonl

    Returns:
        Słownik ze statystykami: {new: X, changed: Y, unchanged: Z}
    """
    logger.info(f"[SCAN] Skanuje katalog: {base_dir}")

    # Wczytaj istniejący indeks
    index = load_index(index_path)
    index_dict = {rec['id']: rec for rec in index}

    stats = {"new": 0, "changed": 0, "unchanged": 0, "duplicate": 0}

    # P5 (#4): body-content hash -> canonical id, for cross-file dedup. Only
    # non-duplicate records are canonical (no dup-of-dup chains). Grown as files
    # are (re)scanned below, so it back-fills over a few scans on an old index.
    body_hash_to_id = {
        rec["body_hash"]: rec["id"]
        for rec in index_dict.values()
        if rec.get("body_hash") and rec.get("status") != STATUS_DUPLICATE
    }

    # Znajdź wszystkie pliki .txt
    txt_files = list(base_dir.rglob("*.txt"))
    logger.info(f"Znaleziono {len(txt_files)} plików .txt")

    for filepath in txt_files:
        try:
            # Względna ścieżka od base_dir
            relative_path = filepath.relative_to(base_dir)
            folder = relative_path.parent.name if relative_path.parent != Path('.') else "root"
            filename = filepath.name
            file_id = str(relative_path).replace('\\', '/')

            # Oblicz hash (cały plik = edit-detekcja; body = dedup P5)
            file_hash = calculate_file_hash(filepath)
            body_hash = calculate_body_hash(filepath)

            if file_id in index_dict:
                # Plik już istnieje - sprawdź czy się zmienił
                existing = index_dict[file_id]
                if existing.get('hash') != file_hash:
                    logger.info(f"[CHANGED] Zmieniony plik: {file_id}")
                    # Resetuj status na new (ponowna nauka)
                    existing['hash'] = file_hash
                    existing['status'] = STATUS_NEW
                    existing['updated_at'] = get_timestamp()
                    # Przelicz priorytet
                    existing['priority'] = calculate_initial_priority(filepath, folder, filename)
                    stats['changed'] += 1
                else:
                    stats['unchanged'] += 1
                # P5: ensure the record carries a body_hash (back-fill for
                # records indexed before P5) and register it as canonical.
                if body_hash:
                    existing['body_hash'] = body_hash
                    if existing.get('status') != STATUS_DUPLICATE:
                        body_hash_to_id.setdefault(body_hash, file_id)
            else:
                # P5: identical body already indexed under a DIFFERENT id ->
                # mark this copy inert so it is never re-learned. Its progress
                # is credited via the canonical (completed_file_ids resolves it).
                canonical_id = (
                    body_hash_to_id.get(body_hash) if body_hash else None
                )
                if canonical_id and canonical_id != file_id:
                    logger.info(
                        f"[DUPLICATE] {file_id} has the same body as "
                        f"{canonical_id} - indexed inert, not re-learned"
                    )
                    index_dict[file_id] = {
                        "id": file_id,
                        "folder": folder,
                        "file": filename,
                        "status": STATUS_DUPLICATE,
                        "duplicate_of": canonical_id,
                        "priority": 0.0,
                        "hash": file_hash,
                        "body_hash": body_hash,
                        "created_at": get_timestamp(),
                        "updated_at": get_timestamp(),
                        "exam_attempts": 0,
                        "last_scores": [],
                        "chunks_learned": 0,
                        "total_chunks": 0,
                    }
                    stats['duplicate'] += 1
                else:
                    # Nowy plik
                    logger.info(f"[NEW] Nowy plik: {file_id}")
                    priority = calculate_initial_priority(filepath, folder, filename)

                    new_record = {
                        "id": file_id,
                        "folder": folder,
                        "file": filename,
                        "status": STATUS_NEW,
                        "priority": priority,
                        "hash": file_hash,
                        "body_hash": body_hash,
                        "created_at": get_timestamp(),
                        "updated_at": get_timestamp(),
                        "exam_attempts": 0,
                        "last_scores": [],
                        "chunks_learned": 0,
                        "total_chunks": 0,
                    }

                    index_dict[file_id] = new_record
                    if body_hash:
                        body_hash_to_id[body_hash] = file_id
                    stats['new'] += 1

        except Exception as e:
            logger.error(f"Błąd przetwarzania {filepath}: {e}")
            continue

    # Zapisz zaktualizowany indeks
    updated_index = list(index_dict.values())
    save_index(updated_index, index_path)

    logger.info(f"[STATS] Statystyki: nowe={stats['new']}, zmienione={stats['changed']}, niezmienione={stats['unchanged']}, duplikaty={stats['duplicate']}")

    return stats


def get_next_file_to_learn(index_path: Path, exclude_hard_topics: bool = True) -> Optional[Dict[str, Any]]:
    """
    Zwraca kolejny plik do nauki na podstawie priorytetu.

    Args:
        index_path: Ścieżka do indeksu
        exclude_hard_topics: Czy pominąć pliki oznaczone jako hard_topic

    Returns:
        Rekord pliku lub None jeśli brak plików do nauki
    """
    from maria_core.sys.config import STATUS_NEW, STATUS_LEARNING, STATUS_HARD_TOPIC

    index = load_index(index_path)

    # Filtruj pliki do nauki
    candidates = []
    for rec in index:
        if rec['status'] in [STATUS_NEW, STATUS_LEARNING]:
            if exclude_hard_topics and rec['status'] == STATUS_HARD_TOPIC:
                continue
            candidates.append(rec)

    if not candidates:
        return None

    # Sortuj po priorytecie (malejąco)
    candidates.sort(key=lambda x: x.get('priority', 0), reverse=True)

    return candidates[0]


# ================== PUBLICZNE API DLA HEARTBEAT ==================

class Perception:
    """
    Fasada dla systemu percepcji - uproszczone API dla innych modułów.
    """

    @staticmethod
    def scan_for_new_files() -> Dict[str, int]:
        """
        Skanuje folder input/ i aktualizuje indeks.
        Zwraca statystyki: {new: X, changed: Y, unchanged: Z}
        """
        return scan_input_directory(INPUT_DIR, KNOWLEDGE_INDEX)

    @staticmethod
    def has_new_material() -> bool:
        """Czy są nowe pliki do przetworzenia?"""
        next_file = get_next_file_to_learn(KNOWLEDGE_INDEX)
        return next_file is not None

    @staticmethod
    def get_next_file() -> Optional[Dict[str, Any]]:
        """Pobierz następny plik do nauki (rekord z indeksu)."""
        return get_next_file_to_learn(KNOWLEDGE_INDEX)

    @staticmethod
    def get_file_path(file_record: Dict[str, Any]) -> Path:
        """Konwertuje rekord z indeksu na pełną ścieżkę pliku."""
        return INPUT_DIR / file_record['id']

    @staticmethod
    def pending_count() -> int:
        """Ile plików czeka do nauki?"""
        index = load_index(KNOWLEDGE_INDEX)
        return len([r for r in index if r['status'] in [STATUS_NEW, STATUS_LEARNING]])


# Singleton dla wygody
perception = Perception()


# ================== PRZYKŁAD UŻYCIA ==================
if __name__ == "__main__":
    print("[PERCEPTION TEST]")
    
    # Skanuj folder
    stats = perception.scan_for_new_files()
    print(f"Statystyki: {stats}")
    
    # Sprawdź kolejkę
    print(f"Plików w kolejce: {perception.pending_count()}")
    
    # Pobierz następny plik
    next_file = perception.get_next_file()
    if next_file:
        print(f"Następny do nauki: {next_file['file']} (priorytet: {next_file['priority']})")
        filepath = perception.get_file_path(next_file)
        print(f"Pełna ścieżka: {filepath}")
    else:
        print("Brak plików do nauki.")
