"""Durable receipts for one operator's chat transport, never a job scheduler.

Client nonces correlate replies; only the server creates interaction identities.
Unfinished receipts from a previous process become unknown and are never replayed.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
from uuid import uuid4


def valid_request_id(value):
    return isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9-]{32,36}", value) is not None


class TurnConflict(ValueError):
    pass


class ChatTurnStore:
    """Single application-process store. IDs are retained even after reply expiry."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError("unsafe_turn_directory")
        info = self.directory.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError("unowned_turn_directory")
        self.directory.chmod(0o700)
        self.path = self.directory / "receipts.sqlite3"
        self.lock = threading.RLock()
        if self.path.is_symlink():
            raise ValueError("unsafe_turn_file")
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (hasattr(os, "getuid") and info.st_uid != os.getuid()):
                raise ValueError("unsafe_turn_file")
        finally:
            os.close(fd)
        self.path.chmod(0o600)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS turns (request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, interaction_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, response TEXT, created REAL NOT NULL, updated REAL NOT NULL)")
            db.execute("UPDATE turns SET state='unknown', updated=? WHERE state='pending'", (time.time(),))

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def _digest(message):
        return hashlib.sha256(message.encode("utf-8")).hexdigest()

    @staticmethod
    def _public(row):
        if row is None:
            return None
        result = {"request_id": row[0], "state": row[3], "updatedAt": row[5]}
        if row[4]:
            result["response"] = json.loads(row[4])
        return result

    def lookup(self, request_id, message=None):
        if not valid_request_id(request_id):
            raise ValueError("invalid_request_id")
        with self.lock, closing(self._connect()) as db:
            row = db.execute("SELECT request_id, digest, interaction_id, state, response, updated FROM turns WHERE request_id=?", (request_id,)).fetchone()
        if row and message is not None and row[1] != self._digest(message):
            raise TurnConflict("request_content_conflict")
        return self._public(row)

    def claim(self, request_id, message):
        if not valid_request_id(request_id):
            raise ValueError("invalid_request_id")
        with self.lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT request_id, digest, interaction_id, state, response, updated FROM turns WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[1] != self._digest(message):
                    raise TurnConflict("request_content_conflict")
                return {**self._public(row), "new": False}
            now, interaction = time.time(), uuid4().hex
            db.execute("INSERT INTO turns VALUES (?,?,?,'pending',NULL,?,?)", (request_id, self._digest(message), interaction, now, now))
            return {"request_id": request_id, "state": "pending", "new": True, "interaction_id": interaction}

    def complete(self, request_id, payload):
        # Keep just transport response fields, not arbitrary model/tool metadata.
        allowed = {"success", "message", "error", "code", "fallback", "timeout", "rate_limited", "wait_seconds"}
        response = {key: value for key, value in payload.items() if key in allowed and isinstance(value, (str, bool, int, float, type(None)))}
        for key, value in list(response.items()):
            if isinstance(value, str) and len(value) > 40000:
                response[key] = value[:39920] + "\n[Odpowiedź skrócona w zapisie transportu.]"
        response["request_id"] = request_id
        with self.lock, closing(self._connect()) as db, db:
            db.execute("UPDATE turns SET state='completed', response=?, updated=? WHERE request_id=? AND state='pending'", (json.dumps(response, ensure_ascii=False), time.time(), request_id))
            # Keep the last 500 complete replies. Retain older nonce tombstones,
            # so a delayed client can never rerun an old command after eviction.
            db.execute("UPDATE turns SET state='unknown', response=NULL WHERE state='completed' AND request_id NOT IN (SELECT request_id FROM turns WHERE state='completed' ORDER BY updated DESC LIMIT 500)")

    def mark_unknown(self, request_id):
        with self.lock, closing(self._connect()) as db, db:
            db.execute("UPDATE turns SET state='unknown', updated=? WHERE request_id=? AND state='pending'", (time.time(), request_id))

    def forget_responses(self):
        """Clear chat content while keeping IDs that prevent accidental replay."""
        with self.lock, closing(self._connect()) as db, db:
            db.execute("UPDATE turns SET state='unknown', response=NULL, updated=?", (time.time(),))
