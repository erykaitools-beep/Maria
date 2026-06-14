"""P5 (#4): content-hash dedup at scan time + duplicate resolution in
completed_file_ids.

Identical content fetched under a different filename (same article, new
URL/slug) must not be re-learned, but a goal holding both the original and its
dedup'd twin must still be able to reach progress 1.0.
"""

from maria_core.perception.perception import (
    calculate_body_hash,
    scan_input_directory,
)
from maria_core.memory_engine.memory_store import load_index
from maria_core.sys.config import STATUS_NEW, STATUS_DUPLICATE
from agent_core.routing.handlers import completed_file_ids


def _write(path, header_url, body):
    """Mirror content_writer's header: only URL/date vary between fetches."""
    path.write_text(
        f"# Zrodlo: Wikipedia\n# Tytul: T\n# URL: {header_url}\n"
        f"# Pobrano: 2026-05-31\n# ---\n\n{body}\n",
        encoding="utf-8",
    )


class TestBodyHash:
    def test_same_body_different_header_same_hash(self, tmp_path):
        a, b = tmp_path / "a.txt", tmp_path / "b.txt"
        body = "Identyczna tresc artykulu o fotosyntezie roslin."
        _write(a, "http://pl/X/1", body)
        _write(b, "http://pl/Y/2", body)
        # Whole-file hashes differ (headers differ), body hashes match.
        assert calculate_body_hash(a) == calculate_body_hash(b)

    def test_different_body_different_hash(self, tmp_path):
        a, b = tmp_path / "a.txt", tmp_path / "b.txt"
        _write(a, "http://x", "Tresc pierwsza.")
        _write(b, "http://x", "Tresc druga, zupelnie inna.")
        assert calculate_body_hash(a) != calculate_body_hash(b)

    def test_no_header_hashes_whole_and_is_stable(self, tmp_path):
        a = tmp_path / "plain.txt"
        a.write_text("Goly tekst bez naglowka web_source", encoding="utf-8")
        h = calculate_body_hash(a)
        assert h == calculate_body_hash(a)
        assert len(h) == 64  # sha256 hex


class TestScanDedup:
    def test_identical_body_marked_duplicate(self, tmp_path):
        inp = tmp_path / "input"
        inp.mkdir()
        index = tmp_path / "knowledge_index.jsonl"
        body = "Logika to nauka o poprawnym rozumowaniu i wnioskowaniu."
        _write(inp / "web_wiki_logika.txt", "http://pl/Logika", body)
        _write(inp / "web_wiki_logika_formalna.txt", "http://pl/Logika_formalna", body)

        stats = scan_input_directory(inp, index)

        assert stats["new"] == 1
        assert stats["duplicate"] == 1
        recs = {r["id"]: r for r in load_index(index)}
        # Order of rglob is not guaranteed, so assert structurally: exactly one
        # canonical 'new' and one 'duplicate' that points at it.
        assert sorted(r["status"] for r in recs.values()) == [
            STATUS_DUPLICATE, STATUS_NEW,
        ]
        dup = next(r for r in recs.values() if r["status"] == STATUS_DUPLICATE)
        canon = next(r for r in recs.values() if r["status"] == STATUS_NEW)
        assert dup["duplicate_of"] == canon["id"]
        assert dup["body_hash"] == canon["body_hash"]

    def test_distinct_content_both_new(self, tmp_path):
        inp = tmp_path / "input"
        inp.mkdir()
        index = tmp_path / "knowledge_index.jsonl"
        _write(inp / "web_wiki_a.txt", "http://a", "Pierwszy temat zupelnie inny.")
        _write(inp / "web_wiki_b.txt", "http://b", "Drugi temat calkiem rozny.")

        stats = scan_input_directory(inp, index)

        assert stats["new"] == 2
        assert stats["duplicate"] == 0

    def test_rescan_is_idempotent(self, tmp_path):
        inp = tmp_path / "input"
        inp.mkdir()
        index = tmp_path / "knowledge_index.jsonl"
        body = "Ta sama tresc dwa razy."
        _write(inp / "web_wiki_x.txt", "http://x", body)
        _write(inp / "web_rss_x_kopia.txt", "http://y", body)

        scan_input_directory(inp, index)
        stats2 = scan_input_directory(inp, index)

        # Second scan: nothing new, nothing newly duplicated -- both known.
        assert stats2["new"] == 0
        assert stats2["duplicate"] == 0
        statuses = sorted(r["status"] for r in load_index(index))
        assert statuses == [STATUS_DUPLICATE, STATUS_NEW]


class TestCompletedFileIdsDedup:
    def test_duplicate_completed_iff_canonical_completed(self):
        snapshot = {"files_by_status": {
            "completed": [{"id": "canon.txt"}],
            "duplicate": [
                {"id": "dup_done.txt", "duplicate_of": "canon.txt"},
                {"id": "dup_pending.txt", "duplicate_of": "not_done.txt"},
            ],
        }}
        result = completed_file_ids(snapshot)
        # The dup of a completed canonical counts; the dup of an unlearned one
        # does NOT (no optimistic credit -- preserves the exam-verified gate).
        assert result == {"canon.txt", "dup_done.txt"}

    def test_no_duplicates_bucket_is_safe(self):
        snapshot = {"files_by_status": {"completed": [{"id": "a.txt"}]}}
        assert completed_file_ids(snapshot) == {"a.txt"}
