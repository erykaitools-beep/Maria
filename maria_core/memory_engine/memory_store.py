"""
DEAMONMARIA V2 - Memory Store Module
Zarządzanie pamięcią długoterminową w formacie JSONL.
Wszystkie operacje są thread-safe i atomiczne.
CROSS-PLATFORM: działa na Windows, Linux, Mac.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
from contextlib import contextmanager
import logging
import time
import os
from maria_core.sys.config import MEMORY_DIR


logger = logging.getLogger(__name__)

# Cross-platform file locking
if sys.platform == 'win32':
    # Windows
    import msvcrt

    @contextmanager
    def _lock_file(file_obj):
        """Windows file locking."""
        try:
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, 1)
            yield file_obj
        finally:
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
else:
    # Linux/Mac
    import fcntl

    @contextmanager
    def _lock_file(file_obj):
        """Unix file locking."""
        try:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
            yield file_obj
        finally:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)


class MemoryStore:
    """Interfejs do operacji na plikach JSONL."""

    def __init__(self, filepath):
        # ZAWSZE zamien na Path - czy przyjdzie str, czy Path
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Dict[str, Any]) -> bool:
        """
        Dopisuje rekord do pliku JSONL.

        Args:
            record: Słownik z danymi do zapisania

        Returns:
            True jeśli sukces, False jeśli błąd
        """
        try:
            with open(self.filepath, 'a', encoding='utf-8') as f:
                with _lock_file(f):
                    json_line = json.dumps(record, ensure_ascii=False)
                    f.write(json_line + '\n')
            logger.debug(f"Zapisano rekord do {self.filepath.name}")
            return True
        except Exception as e:
            logger.error(f"Błąd zapisu do {self.filepath}: {e}")
            return False

    def load_all(self) -> List[Dict[str, Any]]:
        """
        Wczytuje wszystkie rekordy z pliku JSONL.

        Returns:
            Lista słowników (rekordów)
        """
        if not self.filepath.exists():
            logger.debug(f"Plik {self.filepath.name} nie istnieje, zwracam pustą listę")
            return []

        records = []
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            records.append(record)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Błąd parsowania linii {line_num} w {self.filepath.name}: {e}")
                            continue
                logger.debug(f"Wczytano {len(records)} rekordów z {self.filepath.name}")
                return records
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(0.1)  # krótka pauza i retry
                    continue
                logger.error(f"Błąd uprawnień przy odczycie {self.filepath}")
                return []
            except Exception as e:
                logger.error(f"Błąd odczytu {self.filepath}: {e}")
                return []

        return records

    def save_all(self, records: List[Dict[str, Any]]) -> bool:
        """
        Zapisuje wszystkie rekordy do pliku JSONL (nadpisuje).

        Args:
            records: Lista słowników do zapisania

        Returns:
            True jeśli sukces, False jeśli błąd
        """
        try:
            # Zapisz do pliku tymczasowego
            temp_file = self.filepath.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                with _lock_file(f):
                    for record in records:
                        json_line = json.dumps(record, ensure_ascii=False)
                        f.write(json_line + '\n')

            # Atomowo zastąp stary plik
            # Windows wymaga usunięcia starego pliku przed replace
            if sys.platform == 'win32' and self.filepath.exists():
                self.filepath.unlink()
            temp_file.replace(self.filepath)

            logger.debug(f"Zapisano {len(records)} rekordów do {self.filepath.name}")
            return True
        except Exception as e:
            logger.error(f"Błąd zapisu wszystkich rekordów do {self.filepath}: {e}")
            return False

    def find(self, filter_func) -> List[Dict[str, Any]]:
        """
        Znajduje rekordy spełniające warunek.

        Args:
            filter_func: Funkcja przyjmująca rekord i zwracająca bool

        Returns:
            Lista pasujących rekordów
        """
        records = self.load_all()
        return [r for r in records if filter_func(r)]

    def count(self) -> int:
        """Zwraca liczbę rekordów w pliku."""
        return len(self.load_all())


# ========== POMOCNICZE FUNKCJE ==========

def append_memory(record: Dict[str, Any], path: Path) -> bool:
    """
    Dopisuje rekord do pamięci długoterminowej.

    Args:
        record: Rekord zawierający: source_file, folder, chunk_id, summary, key_points, tags
        path: Ścieżka do maria_longterm_memory.jsonl
    """
    store = MemoryStore(path)
    return store.append(record)


def append_exam_result(record: Dict[str, Any], path: Path) -> bool:
    """
    Dopisuje wynik egzaminu.

    Args:
        record: Rekord zawierający: file, timestamp, attempt, score, questions, feedback
        path: Ścieżka do exam_results.jsonl
    """
    store = MemoryStore(path)
    return store.append(record)


def load_index(index_path: Path) -> List[Dict[str, Any]]:
    """
    Wczytuje indeks wiedzy.

    Returns:
        Lista rekordów indeksu
    """
    store = MemoryStore(index_path)
    return store.load_all()


def save_index(records: List[Dict[str, Any]], index_path: Path) -> bool:
    """
    Zapisuje cały indeks wiedzy.

    Args:
        records: Lista rekordów indeksu
        index_path: Ścieżka do knowledge_index.jsonl
    """
    store = MemoryStore(index_path)
    return store.save_all(records)


def get_memories_for_file(source_file: str, memory_path: Path) -> List[Dict[str, Any]]:
    """
    Pobiera wszystkie pamięci dotyczące konkretnego pliku.

    Args:
        source_file: ID pliku (np. "pakiet_01/A1.txt")
        memory_path: Ścieżka do maria_longterm_memory.jsonl

    Returns:
        Lista pamięci dotyczących tego pliku
    """
    store = MemoryStore(memory_path)
    return store.find(lambda r: r.get('source_file') == source_file)


def get_exam_results_for_file(file_id: str, exam_path: Path) -> List[Dict[str, Any]]:
    """
    Pobiera wszystkie wyniki egzaminów dla danego pliku.

    Args:
        file_id: ID pliku
        exam_path: Ścieżka do exam_results.jsonl

    Returns:
        Lista wyników egzaminów
    """
    store = MemoryStore(exam_path)
    return store.find(lambda r: r.get('file') == file_id)
# Globalna ścieżka do pliku indeksu pamięci
MEMORY_INDEX_PATH = MEMORY_DIR / "memory_index.json"

# Upewniamy się, że folder pamięci istnieje (powinien być tworzony w config.ensure_directories(),
# ale dodanie tego nie zaszkodzi)
os.makedirs(MEMORY_DIR, exist_ok=True)

# Globalna instancja pamięci – jeden wspólny magazyn dla całego systemu
memory_store = MemoryStore(filepath=(MEMORY_INDEX_PATH))


