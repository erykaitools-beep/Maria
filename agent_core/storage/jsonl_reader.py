"""Bounded reverse reads and incremental cursors for append-only JSONL logs."""

import json
import os
import threading
from pathlib import Path
from typing import Dict, Iterator, List, Optional


def _reverse_lines(path: Path, block_size: int = 8192) -> Iterator[tuple]:
    """Yield (raw complete line, byte offset after line), newest first."""
    with Path(path).open("rb") as stream:
        yield from _reverse_stream(stream, block_size)


def _reverse_stream(stream, block_size: int = 8192) -> Iterator[tuple]:
    """Use the same open file throughout a reverse read, including rotation."""
    position = stream.seek(0, os.SEEK_END)
    remainder = b""
    end = position
    first = True
    while position:
        size = min(position, block_size)
        position -= size
        stream.seek(position)
        pieces = (stream.read(size) + remainder).split(b"\n")
        remainder = pieces[0]
        for raw in reversed(pieces[1:]):
            if first:
                first = False
                end -= len(raw)
                continue
            yield raw, end
            end -= len(raw) + 1
    if not first:
        yield remainder, end


def iter_jsonl_reverse(path: Path) -> Iterator[Dict]:
    """Read complete valid JSON objects from the end, without a full-file list."""
    for raw, _ in _reverse_lines(Path(path)):
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            yield record


def read_jsonl_tail(path: Path, limit: int) -> List[Dict]:
    """Return the latest valid objects in file order; ignore a partial last row."""
    if limit <= 0:
        return []
    recent = []
    for record in iter_jsonl_reverse(path):
        recent.append(record)
        if len(recent) >= limit:
            break
    recent.reverse()
    return recent


class JSONLCursor:
    """Read new complete objects, including bursts and split UTF-8 writes.

    Replacement/truncation resumes after the last complete consumed line when
    that line is retained (the archive writer keeps a suffix). Otherwise the new
    file is read from the beginning. The cursor does not deduplicate identical
    records or timestamps: two appended physical rows remain two events.
    """

    def __init__(self, path: Path, *, max_bytes: int = 1024 * 1024):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.path = Path(path)
        self._max_bytes = max_bytes
        self._identity = None
        self._offset = 0
        self._pending = b""
        self._last_line: Optional[bytes] = None
        self._anchor = b""
        self._lock = threading.Lock()
        self.payload_bytes_read = 0

    def skip_existing(self) -> None:
        """Start a new monitor session after the current complete rows."""
        with self._lock:
            try:
                with self.path.open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    self._identity = (stat.st_dev, stat.st_ino)
                    last = next((row for row in _reverse_stream(stream)
                                 if row[0].strip()), None)
                    self._offset = last[1] if last else 0
                    self._last_line = last[0] if last else None
                    self._pending = b""
                    self._set_anchor(stream)
            except FileNotFoundError:
                self._identity = None
                self._offset = 0
                self._pending = b""

    def _set_anchor(self, stream) -> None:
        stream.seek(max(0, self._offset - 128))
        self._anchor = stream.read(min(128, self._offset))
        stream.seek(self._offset)

    def _recover(self, stream) -> None:
        offset = 0
        if self._last_line is not None:
            stream.seek(0)
            for raw in stream:
                if raw.endswith(b"\n") and raw[:-1] == self._last_line:
                    offset = stream.tell()
                    break
        self._offset = offset
        self._pending = b""

    def poll(self) -> List[Dict]:
        """Consume up to max_bytes new bytes; partial rows wait for another poll."""
        with self._lock:
            try:
                with self.path.open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    changed = self._identity is not None and identity != self._identity
                    if not changed and self._offset:
                        stream.seek(max(0, self._offset - len(self._anchor)))
                        changed = (stat.st_size < self._offset
                                   or stream.read(len(self._anchor)) != self._anchor)
                    if changed:
                        self._recover(stream)
                    self._identity = identity
                    stream.seek(self._offset)
                    new = stream.read(self._max_bytes)
                    self.payload_bytes_read += len(new)
                    self._offset += len(new)
                    self._set_anchor(stream)
            except FileNotFoundError:
                return []

            complete = (self._pending + new).split(b"\n")
            self._pending = complete.pop()
            records = []
            for raw in complete:
                if raw.strip():
                    self._last_line = raw
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(record, dict):
                    records.append(record)
            return records
