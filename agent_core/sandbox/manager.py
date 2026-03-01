"""
SandboxManager - zarządza izolowanymi sesjami nauki.

Kazda nauka idzie przez sandbox. Promote() to jedyny most do produkcji.
Max 1 aktywna sesja. Transaction log w promote_log.jsonl.

Kontrakt: docs/CONTRACTS.md - Kontrakt 2: Sandbox / Production Boundary
ADR-010: Sandbox-first learning
"""

import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from agent_core.sandbox.protocol import (
    PromoteResult,
    SandboxSession,
    SandboxStatus,
    PROMOTE_SCORE_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Timeout po ktorym sandbox jest auto-discard (24h)
SANDBOX_TIMEOUT_SEC = 86400


class SandboxManager:
    """
    Zarzadza sandbox sesjami nauki.

    Jedna aktywna sesja na raz. Promote atomowy per sesja.
    Transaction log w promote_log.jsonl (START/COMMIT/ROLLBACK).
    """

    def __init__(
        self,
        sandbox_base_dir: Path,
        production_index: Path,
        production_memory: Path,
        production_exams: Path,
        promote_log_path: Optional[Path] = None,
    ):
        """
        Args:
            sandbox_base_dir: Katalog bazowy sandbox (meta_data/sandbox/)
            production_index: Sciezka do produkcyjnego knowledge_index.jsonl
            production_memory: Sciezka do produkcyjnego maria_longterm_memory.jsonl
            production_exams: Sciezka do produkcyjnego exam_results.jsonl
            promote_log_path: Sciezka do promote_log.jsonl (domyslnie w sandbox_base_dir)
        """
        self._sandbox_base = sandbox_base_dir
        self._prod_index = production_index
        self._prod_memory = production_memory
        self._prod_exams = production_exams
        self._promote_log = promote_log_path or (sandbox_base_dir / "promote_log.jsonl")

        self._active_session: Optional[SandboxSession] = None

        # Upewnij sie ze katalog istnieje
        self._sandbox_base.mkdir(parents=True, exist_ok=True)

    @property
    def active_session(self) -> Optional[SandboxSession]:
        """Aktualnie aktywna sesja sandbox (lub None)."""
        return self._active_session

    def has_active_session(self) -> bool:
        """Czy jest aktywna sesja sandbox."""
        return self._active_session is not None

    def create_session(self) -> SandboxSession:
        """
        Utworz nowa sesje sandbox.

        Raises:
            RuntimeError: Jesli juz jest aktywna sesja
        """
        if self._active_session is not None:
            raise RuntimeError(
                f"Active sandbox session already exists: {self._active_session.session_id}. "
                "Discard or promote it first."
            )

        session_id = str(uuid.uuid4())[:12]
        sandbox_dir = self._sandbox_base / f"sess_{session_id}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        session = SandboxSession(
            session_id=session_id,
            created_at=time.time(),
            status=SandboxStatus.ACTIVE,
            sandbox_dir=sandbox_dir,
            sandbox_index=sandbox_dir / "knowledge_index.jsonl",
            sandbox_memory=sandbox_dir / "maria_longterm_memory.jsonl",
            sandbox_exams=sandbox_dir / "exam_results.jsonl",
        )

        # Utworz puste pliki JSONL
        session.sandbox_index.touch()
        session.sandbox_memory.touch()
        session.sandbox_exams.touch()

        self._active_session = session
        logger.info(f"Sandbox session created: {session_id} at {sandbox_dir}")
        return session

    def seed_from_production(self, file_ids: Optional[List[str]] = None) -> int:
        """
        Skopiuj rekordy indeksu z produkcji do sandbox.

        Pozwala sandbox kontynuowac nauke plikow ktore juz sa w produkcji.

        Args:
            file_ids: Lista file_id do skopiowania (None = wszystkie)

        Returns:
            Liczba skopiowanych rekordow

        Raises:
            RuntimeError: Jesli brak aktywnej sesji
        """
        session = self._require_active_session()

        if not self._prod_index.exists():
            return 0

        seeded = 0
        with open(self._prod_index, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if file_ids is None or record.get("file_id") in file_ids:
                        with open(session.sandbox_index, "a", encoding="utf-8") as sf:
                            sf.write(json.dumps(record, ensure_ascii=False) + "\n")
                        seeded += 1
                except (json.JSONDecodeError, KeyError):
                    continue

        logger.info(f"Seeded {seeded} records from production to sandbox {session.session_id}")
        return seeded

    def record_chunk_learned(self, file_id: str) -> None:
        """
        Rejestruj nauczony chunk (wywolywane po learn_next_chunk).

        Args:
            file_id: Identyfikator pliku
        """
        session = self._require_active_session()
        session.chunks_learned += 1
        # Zlicz unikalne pliki
        if file_id:
            session.files_learned = self._count_unique_files(session.sandbox_index)

    def record_exam_result(self, file_id: str, score: float, passed: bool) -> None:
        """
        Rejestruj wynik egzaminu (wywolywane po run_exam_if_ready).

        Args:
            file_id: Identyfikator pliku
            score: Wynik egzaminu (0.0-1.0)
            passed: Czy zdany
        """
        session = self._require_active_session()
        session.exams_total += 1
        if passed:
            session.exams_passed += 1

        # Przelicz srednia
        # Wazona: (stara_srednia * (n-1) + nowy_score) / n
        n = session.exams_total
        if n == 1:
            session.avg_score = score
        else:
            session.avg_score = (session.avg_score * (n - 1) + score) / n

        # Sprawdz czy kryteria spelnione
        if session.meets_promote_criteria():
            session.status = SandboxStatus.READY_TO_PROMOTE

    def promote(self) -> PromoteResult:
        """
        Przenies zawartosc sandbox do produkcji.

        Atomowe per sesja: wszystko albo nic.
        Transaction log: START -> COMMIT/ROLLBACK.

        Returns:
            PromoteResult z wynikiem operacji

        Raises:
            RuntimeError: Jesli brak aktywnej sesji
        """
        session = self._require_active_session()

        if not session.meets_promote_criteria():
            return PromoteResult(
                success=False,
                errors=[
                    f"Promote criteria not met: "
                    f"chunks={session.chunks_learned}, "
                    f"exams={session.exams_total}, "
                    f"avg_score={session.avg_score:.2f}, "
                    f"errors={session.validation_errors}"
                ],
            )

        # Waliduj JSONL w sandboxie
        validation_errors = self._validate_sandbox_jsonl(session)
        if validation_errors:
            session.validation_errors.extend(validation_errors)
            return PromoteResult(success=False, errors=validation_errors)

        # Transaction: START
        self._write_promote_log({
            "ts": time.time(),
            "marker": "START",
            "session_id": session.session_id,
            "files": session.files_learned,
            "chunks": session.chunks_learned,
        })

        try:
            # Append sandbox JSONL do produkcji
            files_promoted = 0
            chunks_promoted = 0

            # Merge index (nowszy updated_at wygrywa)
            index_merged = self._merge_index(session.sandbox_index, self._prod_index)
            if index_merged > 0:
                files_promoted = index_merged

            # Append memory
            chunks_promoted = self._append_jsonl(session.sandbox_memory, self._prod_memory)

            # Append exams
            self._append_jsonl(session.sandbox_exams, self._prod_exams)

            # Usun sandbox dir
            shutil.rmtree(session.sandbox_dir, ignore_errors=True)

            # Transaction: COMMIT
            self._write_promote_log({
                "ts": time.time(),
                "marker": "COMMIT",
                "session_id": session.session_id,
                "result": "ok",
            })

            session.status = SandboxStatus.PROMOTED
            self._active_session = None

            logger.info(
                f"Sandbox {session.session_id} promoted: "
                f"{files_promoted} files, {chunks_promoted} chunks"
            )

            return PromoteResult(
                success=True,
                files_promoted=files_promoted,
                chunks_promoted=chunks_promoted,
            )

        except Exception as e:
            # Transaction: ROLLBACK
            self._write_promote_log({
                "ts": time.time(),
                "marker": "ROLLBACK",
                "session_id": session.session_id,
                "reason": type(e).__name__,
                "exception": str(e),
            })

            logger.error(f"Sandbox promote failed: {e}")
            return PromoteResult(
                success=False,
                errors=[f"Promote failed: {e}"],
            )

    def discard(self, reason: str = "user_request") -> bool:
        """
        Odrzuc aktywna sesje sandbox.

        Args:
            reason: Powod odrzucenia

        Returns:
            True jesli sesja zostala odrzucona
        """
        if self._active_session is None:
            return False

        session = self._active_session
        session.status = SandboxStatus.DISCARDED

        # Usun katalog sandbox
        if session.sandbox_dir.exists():
            shutil.rmtree(session.sandbox_dir, ignore_errors=True)

        logger.info(f"Sandbox {session.session_id} discarded: {reason}")
        self._active_session = None
        return True

    def check_timeout(self) -> bool:
        """
        Sprawdz czy aktywna sesja przekroczyla timeout (24h).

        Returns:
            True jesli sesja zostala auto-discarded
        """
        if self._active_session is None:
            return False

        age = time.time() - self._active_session.created_at
        if age > SANDBOX_TIMEOUT_SEC:
            self.discard(reason="timeout_24h")
            return True
        return False

    def startup_recovery(self) -> None:
        """
        Sprawdz promote_log na starcie systemu.

        Jesli ostatni wpis to START bez COMMIT:
        - Sandbox dir istnieje → auto-DISCARD
        - Sandbox dir nie istnieje → WARNING (partial append)
        W obu przypadkach: dopisz ROLLBACK marker.
        """
        if not self._promote_log.exists():
            return

        # Znajdz ostatni wpis
        last_entry = None
        try:
            with open(self._promote_log, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            last_entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
        except Exception:
            return

        if last_entry is None:
            return

        if last_entry.get("marker") != "START":
            return  # Last was COMMIT or ROLLBACK - all good

        session_id = last_entry.get("session_id", "unknown")
        sandbox_dir = self._sandbox_base / f"sess_{session_id}"

        if sandbox_dir.exists():
            # Sandbox intact - auto-discard (nie zombie)
            shutil.rmtree(sandbox_dir, ignore_errors=True)
            logger.warning(
                f"Startup recovery: sandbox {session_id} auto-discarded "
                "(START without COMMIT, sandbox dir existed)"
            )
        else:
            # Sandbox dir gone - partial append may have occurred
            logger.warning(
                f"Startup recovery: sandbox {session_id} - "
                "START without COMMIT, sandbox dir missing (possible partial append)"
            )

        # Dopisz ROLLBACK marker
        self._write_promote_log({
            "ts": time.time(),
            "marker": "ROLLBACK",
            "session_id": session_id,
            "reason": "startup_recovery",
            "exception": None,
        })

    def cleanup_stale(self) -> int:
        """
        Usun osierocone katalogi sandbox (bez aktywnej sesji).

        Returns:
            Liczba usunietych katalogow
        """
        removed = 0
        if not self._sandbox_base.exists():
            return 0

        active_dir = None
        if self._active_session:
            active_dir = self._active_session.sandbox_dir

        for item in self._sandbox_base.iterdir():
            if item.is_dir() and item.name.startswith("sess_"):
                if item != active_dir:
                    shutil.rmtree(item, ignore_errors=True)
                    removed += 1

        if removed:
            logger.info(f"Cleaned up {removed} stale sandbox directories")
        return removed

    def get_status(self) -> Dict:
        """Status sandbox managera (do /sandbox status command)."""
        if self._active_session:
            s = self._active_session
            return {
                "active": True,
                "session_id": s.session_id,
                "status": s.status.value,
                "age_sec": time.time() - s.created_at,
                "chunks_learned": s.chunks_learned,
                "files_learned": s.files_learned,
                "exams_total": s.exams_total,
                "exams_passed": s.exams_passed,
                "avg_score": s.avg_score,
                "meets_criteria": s.meets_promote_criteria(),
                "validation_errors": s.validation_errors,
            }
        return {"active": False}

    # --- Private methods ---

    def _require_active_session(self) -> SandboxSession:
        """Zwroc aktywna sesje lub rzuc wyjatek."""
        if self._active_session is None:
            raise RuntimeError("No active sandbox session. Call create_session() first.")
        return self._active_session

    def _validate_sandbox_jsonl(self, session: SandboxSession) -> List[str]:
        """
        Sprawdz czy pliki JSONL w sandboxie sa poprawne.

        Returns:
            Lista bledow (pusta = OK)
        """
        errors = []
        for path, name in [
            (session.sandbox_index, "index"),
            (session.sandbox_memory, "memory"),
            (session.sandbox_exams, "exams"),
        ]:
            if not path.exists():
                errors.append(f"{name}: file missing")
                continue
            line_num = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line_num += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as e:
                        errors.append(f"{name} line {line_num}: {e}")
        return errors

    def _merge_index(self, source: Path, target: Path) -> int:
        """
        Merge index records: nowszy updated_at wygrywa.

        Returns:
            Liczba zmergowanych rekordow
        """
        if not source.exists():
            return 0

        # Wczytaj istniejace rekordy z produkcji (po file_id)
        prod_records: Dict[str, dict] = {}
        if target.exists():
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        fid = record.get("file_id")
                        if fid:
                            prod_records[fid] = record
                    except json.JSONDecodeError:
                        continue

        # Merge z sandbox
        merged = 0
        with open(source, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    fid = record.get("file_id")
                    if not fid:
                        continue
                    existing = prod_records.get(fid)
                    if existing is None or record.get("updated_at", 0) > existing.get("updated_at", 0):
                        prod_records[fid] = record
                        merged += 1
                except json.JSONDecodeError:
                    continue

        # Zapisz zmergowany index
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            for record in prod_records.values():
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return merged

    def _append_jsonl(self, source: Path, target: Path) -> int:
        """
        Append rekordy z source do target (JSONL).

        Returns:
            Liczba appended rekordow
        """
        if not source.exists():
            return 0

        count = 0
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(source, "r", encoding="utf-8") as src:
            with open(target, "a", encoding="utf-8") as dst:
                for line in src:
                    line = line.strip()
                    if line:
                        dst.write(line + "\n")
                        count += 1
        return count

    def _write_promote_log(self, entry: dict) -> None:
        """Append entry do promote_log.jsonl."""
        self._promote_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self._promote_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _count_unique_files(self, index_path: Path) -> int:
        """Zlicz unikalne file_id w pliku JSONL."""
        if not index_path.exists():
            return 0
        file_ids = set()
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    fid = record.get("file_id")
                    if fid:
                        file_ids.add(fid)
                except json.JSONDecodeError:
                    continue
        return len(file_ids)
