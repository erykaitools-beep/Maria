"""Real file cursor regressions; temp data, no services or model inference."""

import json
from pathlib import Path

import pytest

from agent_core.storage.jsonl_reader import (
    JSONLCursor, _reverse_lines, read_jsonl_tail,
)


def _rows(path, records, mode="ab"):
    with path.open(mode) as stream:
        for record in records:
            stream.write((json.dumps(record, ensure_ascii=False) + "\n").encode())


def _drain(cursor):
    rows = []
    before = -1
    while before != cursor.payload_bytes_read:
        before = cursor.payload_bytes_read
        rows.extend(cursor.poll())
    return rows


def test_cursor_payload_per_poll_is_bounded(tmp_path):
    path = tmp_path / "log.jsonl"
    _rows(path, [{"n": i} for i in range(100)])
    cursor = JSONLCursor(path, max_bytes=137)
    cursor.poll()
    assert cursor.payload_bytes_read == 137


@pytest.mark.parametrize("block_size", [1, 3, 7, 8192])
def test_reverse_reader_offsets_and_partial_tail(tmp_path, block_size):
    path = tmp_path / "log.jsonl"
    raw = [b'{"n":0}', b'{"n":1,"text":"' + "zażółć".encode() + b'"}', b'{"n":2}']
    data = b"\n".join(raw) + b'\n{"n":unfinished'
    path.write_bytes(data)
    got = list(_reverse_lines(path, block_size))
    ends = []
    offset = 0
    for row in raw:
        offset += len(row) + 1
        ends.append(offset)
    assert got == list(reversed(list(zip(raw, ends))))


def test_tail_ignores_invalid_nonobjects_and_partial_utf8(tmp_path):
    path = tmp_path / "log.jsonl"
    _rows(path, [{"n": i} for i in range(100)])
    with path.open("ab") as stream:
        stream.write(b'bad\n[]\n{"text":"\xc5')
    assert read_jsonl_tail(path, 2) == [{"n": 98}, {"n": 99}]
    assert read_jsonl_tail(path, 0) == []


def test_tail_reads_only_end_of_large_file(monkeypatch, tmp_path):
    path = tmp_path / "large.jsonl"
    _rows(path, [{"n": i, "text": "x" * 100} for i in range(10000)])
    original = Path.open
    bytes_read = []

    class CountRead:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def seek(self, *args):
            return self.stream.seek(*args)
        def read(self, count):
            data = self.stream.read(count)
            bytes_read.append(len(data))
            return data

    def open_count(self, mode="r", *args, **kwargs):
        stream = original(self, mode, *args, **kwargs)
        return CountRead(stream) if self == path and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", open_count)
    assert read_jsonl_tail(path, 2) == [
        {"n": 9998, "text": "x" * 100}, {"n": 9999, "text": "x" * 100},
    ]
    assert sum(bytes_read) <= 8192


def test_cursor_keeps_bursts_and_same_timestamp(tmp_path):
    path = tmp_path / "log.jsonl"
    rows = [{"n": i, "timestamp": 1.0} for i in range(1000)]
    _rows(path, rows)
    cursor = JSONLCursor(path, max_bytes=137)
    assert _drain(cursor) == rows
    assert cursor.poll() == []
    assert cursor.payload_bytes_read == path.stat().st_size


def test_cursor_waits_for_split_utf8_and_newline(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_bytes(b'{"text":"\xc5')
    cursor = JSONLCursor(path)
    assert cursor.poll() == []
    with path.open("ab") as stream:
        stream.write(b'\xbc"}')
    assert cursor.poll() == []
    with path.open("ab") as stream:
        stream.write(b'\n')
    assert cursor.poll() == [{"text": "ż"}]
    assert cursor.poll() == []


@pytest.mark.parametrize("replace", [True, False])
def test_rotation_retained_suffix_does_not_replay_and_new_rows_are_read(tmp_path, replace):
    path = tmp_path / "log.jsonl"
    rows = [{"n": i} for i in range(5)]
    _rows(path, rows)
    cursor = JSONLCursor(path)
    assert cursor.poll() == rows
    target = tmp_path / "new.jsonl" if replace else path
    _rows(target, rows[3:] + [{"n": 5}, {"n": 6}], mode="wb")
    if replace:
        target.replace(path)
    assert cursor.poll() == [{"n": 5}, {"n": 6}]
    assert cursor.poll() == []


def test_rotation_with_unread_burst_preserves_remaining_rows(tmp_path):
    path = tmp_path / "log.jsonl"
    rows = [{"n": i} for i in range(50)]
    _rows(path, rows)
    cursor = JSONLCursor(path, max_bytes=80)
    first = cursor.poll()
    replacement = tmp_path / "new.jsonl"
    _rows(replacement, rows[2:] + [{"n": 50}])
    replacement.replace(path)
    assert first + _drain(cursor) == rows + [{"n": 50}]


def test_restart_skips_old_complete_rows_but_keeps_new_partial_completion(tmp_path):
    path = tmp_path / "log.jsonl"
    _rows(path, [{"n": 1}])
    with path.open("ab") as stream:
        stream.write(b'{"n":2')
    cursor = JSONLCursor(path)
    cursor.skip_existing()
    assert cursor.poll() == []
    with path.open("ab") as stream:
        stream.write(b'}\n')
    assert cursor.poll() == [{"n": 2}]


def test_missing_file_and_complete_malformed_row_are_tolerated(tmp_path):
    path = tmp_path / "log.jsonl"
    cursor = JSONLCursor(path)
    cursor.skip_existing()
    assert cursor.poll() == []
    path.write_bytes(b'broken\n{}\n')
    assert cursor.poll() == [{}]
    assert cursor.poll() == []
