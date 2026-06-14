"""Tests for the 'summaries' semantic namespace indexer (held-out closed-book β).

Pure tests: build_summary_entries does no embedding; index_summaries is tested
against a fake SemanticMemory so it needs no Ollama.
"""

import json
from pathlib import Path

from agent_core.semantic.indexer import (
    build_summary_entries,
    index_summaries,
    SUMMARY_NAMESPACE,
)


def _write_jsonl(path: Path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_build_summary_entries_basic(tmp_path):
    mem = tmp_path / "ltm.jsonl"
    _write_jsonl(mem, [
        {
            "source_file": "web_wiki_chemia.txt",
            "chunk_id": "web_wiki_chemia.txt#chunk_0",
            "chunk_index": "0",
            "summary": "Chemia bada substancje i ich przemiany.",
            "key_points": ["reakcje chemiczne", "wiazania"],
        },
        {
            "source_file": "web_wiki_biologia.txt",
            "chunk_id": "web_wiki_biologia.txt#chunk_0",
            "summary": "Biologia bada organizmy zywe.",
            "key_points": [],
        },
    ])

    entries = build_summary_entries(mem)
    assert len(entries) == 2
    ids = {e[0] for e in entries}
    assert ids == {"summary:web_wiki_chemia.txt#chunk_0", "summary:web_wiki_biologia.txt#chunk_0"}

    chemia = next(e for e in entries if "chemia" in e[0])
    entry_id, text, source_file = chemia
    assert source_file == "web_wiki_chemia.txt"
    # embeds the actual content (summary + key_points), not just a title
    assert "substancje" in text
    assert "reakcje chemiczne" in text


def test_build_summary_entries_synthesizes_chunk_id_when_missing(tmp_path):
    mem = tmp_path / "ltm.jsonl"
    _write_jsonl(mem, [
        {"source_file": "f.txt", "chunk_index": "3", "summary": "tresc"},
    ])
    entries = build_summary_entries(mem)
    assert entries[0][0] == "summary:f.txt#chunk_3"


def test_build_summary_entries_skips_empty_and_unsourced(tmp_path):
    mem = tmp_path / "ltm.jsonl"
    _write_jsonl(mem, [
        {"source_file": "", "chunk_id": "x#0", "summary": "ma tresc ale brak source"},
        {"source_file": "g.txt", "chunk_id": "g.txt#0", "summary": "", "key_points": []},
        {"source_file": "ok.txt", "chunk_id": "ok.txt#0", "summary": "realna tresc"},
    ])
    entries = build_summary_entries(mem)
    assert len(entries) == 1
    assert entries[0][2] == "ok.txt"


def test_build_summary_entries_falls_back_to_summary_simple_and_core_ideas(tmp_path):
    mem = tmp_path / "ltm.jsonl"
    _write_jsonl(mem, [
        {
            "source_file": "f.txt",
            "chunk_id": "f.txt#0",
            "summary_simple": "prosta tresc",
            "core_ideas": ["idea A"],
        },
    ])
    entries = build_summary_entries(mem)
    assert "prosta tresc" in entries[0][1]
    assert "idea A" in entries[0][1]


class _FakeStore:
    def __init__(self, existing=None):
        self._existing = set(existing or [])

    def get(self, entry_id):
        return object() if entry_id in self._existing else None


class _FakeSemanticMemory:
    """Records index_batch calls; no embedding."""

    def __init__(self, existing=None):
        self.store = _FakeStore(existing)
        self.batches = []
        self.saved = 0

    def index_batch(self, namespace, entries, extra_metadata=None):
        self.batches.append((namespace, list(entries), extra_metadata))
        return len(entries)

    def save(self):
        self.saved += 1
        return 1


def test_index_summaries_groups_by_file_with_source_file_metadata(tmp_path):
    mem = tmp_path / "ltm.jsonl"
    _write_jsonl(mem, [
        {"source_file": "a.txt", "chunk_id": "a.txt#0", "summary": "a0"},
        {"source_file": "a.txt", "chunk_id": "a.txt#1", "summary": "a1"},
        {"source_file": "b.txt", "chunk_id": "b.txt#0", "summary": "b0"},
    ])
    sm = _FakeSemanticMemory()
    total = index_summaries(sm, mem)

    assert total == 3
    # one batch per file, each tagged with its source_file
    ns = {b[0] for b in sm.batches}
    assert ns == {SUMMARY_NAMESPACE}
    meta_files = {b[2]["source_file"] for b in sm.batches}
    assert meta_files == {"a.txt", "b.txt"}
    assert sm.saved == 1


def test_index_summaries_incremental_skips_existing(tmp_path):
    mem = tmp_path / "ltm.jsonl"
    _write_jsonl(mem, [
        {"source_file": "a.txt", "chunk_id": "a.txt#0", "summary": "a0"},
        {"source_file": "a.txt", "chunk_id": "a.txt#1", "summary": "a1"},
    ])
    # a.txt#0 already indexed -> only a.txt#1 is new
    sm = _FakeSemanticMemory(existing={"summary:a.txt#0"})
    total = index_summaries(sm, mem, only_new=True)
    assert total == 1
    indexed_ids = [e[0] for b in sm.batches for e in b[1]]
    assert indexed_ids == ["summary:a.txt#1"]
