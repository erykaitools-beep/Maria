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
import threading
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

    @property
    def _lock_path(self) -> Path:
        """Osobny plik-kłódka obok pliku danych.

        Kłódka MUSI wisieć na czymś, co przeżyje replace() pliku danych.
        Blokowanie samego pliku danych nie wystarcza: save_all podmienia
        i-node, wiec rownolegly writer trzymalby blokade na osieroconym
        i-node i pisal w pustke.
        """
        return self.filepath.with_name(self.filepath.name + '.lock')

    @contextmanager
    def _exclusive(self):
        """Wylaczny dostep do TEGO pliku danych (append i save_all razem)."""
        with open(self._lock_path, 'a', encoding='utf-8') as lock_f:
            with _lock_file(lock_f):
                yield

    def append(self, record: Dict[str, Any]) -> bool:
        """
        Dopisuje rekord do pliku JSONL.

        Args:
            record: Słownik z danymi do zapisania

        Returns:
            True jeśli sukces, False jeśli błąd
        """
        try:
            # Ta sama kłódka co save_all - inaczej append moglby dopisac
            # do i-node'a wlasnie podmienianego przez save_all (dane znikaja).
            with self._exclusive():
                with open(self.filepath, 'a', encoding='utf-8') as f:
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
        # Kłódka obejmuje zapis I podmiane. Dawniej flock szedl na plik
        # tymczasowy i byl zwalniany PRZED replace() - czyli chronil nic.
        with self._exclusive():
            return self._write_records(records)

    def _write_records(self, records: List[Dict[str, Any]]) -> bool:
        """Zapis do tempa + atomowa podmiana.

        WOLAJACY MUSI JUZ TRZYMAC ``_exclusive()``. Metoda sama go nie bierze,
        bo flock na drugim deskryptorze w tym samym procesie zablokowalby
        sie na sobie (zakleszczenie).
        """
        # Nazwa tempa MUSI byc unikalna per pisarz. Wspolna nazwa (dawne
        # with_suffix('.tmp')) znaczyla, ze dwa rownolegle save_all otwieraly
        # ten SAM plik w trybie 'w' - drugi ucinal dane pierwszego w trakcie
        # pisania. Zmierzone: uszkodzony plik w 4 z 5 rund.
        temp_file = self.filepath.with_name(
            f"{self.filepath.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                for record in records:
                    json_line = json.dumps(record, ensure_ascii=False)
                    f.write(json_line + '\n')
                # Twardy reset (jak 30.07) potrafi zostawic plik z trescia
                # ze niczego. Dane na dysk PRZED podmiana nazwy.
                f.flush()
                os.fsync(f.fileno())

            # Atomowo zastąp stary plik
            # Windows wymaga usunięcia starego pliku przed replace
            if sys.platform == 'win32' and self.filepath.exists():
                self.filepath.unlink()
            temp_file.replace(self.filepath)

            logger.debug(f"Zapisano {len(records)} rekordów do {self.filepath.name}")
            return True
        except Exception as e:
            logger.error(f"Błąd zapisu wszystkich rekordów do {self.filepath}: {e}")
            # Nie zostawiaj sieroty - inaczej katalog obrasta w *.tmp
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def update_all(self, mutate) -> bool:
        """Odczyt-zmiana-zapis pod JEDNA kłódką (bez utraty aktualizacji).

        Wzorzec ``index = load_index(); index.append(x); save_index(index)``
        ma wyscig POMIEDZY odczytem a zapisem, ktorego blokada w save_all nie
        domyka: dwa watki czytaja ten sam stan i drugi nadpisuje zmiane
        pierwszego. Zmierzone na 6 watkach x 40 dopisan: **240 dopisanych,
        40 w pliku - 200 zgubionych**.

        Args:
            mutate: funkcja lista_rekordow -> nowa_lista_rekordow.
                NIE WOLNO jej wolac append()/save_all() na tym samym
                MemoryStore - kłódka nie jest reentrantna (zakleszczenie).

        Returns:
            True jeśli sukces, False jeśli błąd
        """
        try:
            with self._exclusive():
                records = self.load_all()
                updated = mutate(records)
                if updated is None:
                    logger.error(
                        f"update_all: mutate() zwrocilo None dla {self.filepath.name} "
                        f"- przerwano, plik nietkniety"
                    )
                    return False
                return self._write_records(list(updated))
        except Exception as e:
            logger.error(f"Błąd update_all na {self.filepath}: {e}")
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


