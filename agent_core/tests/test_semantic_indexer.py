"""Tests for SemanticMemory auto-indexer."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.semantic.indexer import (
    _extract_title_from_file,
    build_knowledge_entries,
    build_belief_entries,
    build_hint_entries,
    run_initial_indexing,
    start_background_indexing,
)
from agent_core.semantic import SemanticMemory
from agent_core.semantic.embedding_model import EmbeddingModel


def _mock_semantic_memory():
    sm = MagicMock(spec=SemanticMemory)
    sm.index_batch = MagicMock(side_effect=lambda ns, entries: len(entries))
    sm.save = MagicMock(return_value=0)
    return sm


class TestExtractTitle:
    def test_wiki_title(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("# Zrodlo: Wikipedia (pl)\n# Tytul: Fizyka\nContent here\n")
        assert _extract_title_from_file(f) == "Fizyka"

    def test_expert_temat(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("# Zrodlo: ChatGPT\n# Temat: logika formalna\nContent\n")
        assert _extract_title_from_file(f) == "logika formalna"

    def test_fallback_to_filename(self, tmp_path):
        f = tmp_path / "web_wiki_astronomia.txt"
        f.write_text("No title header here\n")
        assert _extract_title_from_file(f) == "astronomia"

    def test_fallback_cleans_prefix(self, tmp_path):
        f = tmp_path / "input_003_system_i_przyczyna.txt"
        f.write_text("No header\n")
        assert _extract_title_from_file(f) == "system i przyczyna"

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "missing.txt"
        title = _extract_title_from_file(f)
        assert title == "missing"


class TestBuildKnowledgeEntries:
    def test_basic(self, tmp_path):
        # Create knowledge_index
        ki = tmp_path / "knowledge_index.jsonl"
        ki.write_text(json.dumps({
            "id": "web_wiki_fizyka.txt",
            "file": "web_wiki_fizyka.txt",
            "status": "completed",
        }) + "\n")

        # Create input file
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "web_wiki_fizyka.txt").write_text("# Tytul: Fizyka\nContent\n")

        entries = build_knowledge_entries(ki, input_dir)
        assert len(entries) == 1
        assert entries[0][0] == "knowledge:web_wiki_fizyka.txt"
        assert "Fizyka" in entries[0][1]

    def test_missing_input_file(self, tmp_path):
        ki = tmp_path / "knowledge_index.jsonl"
        ki.write_text(json.dumps({
            "id": "missing.txt",
            "file": "missing.txt",
            "status": "new",
        }) + "\n")

        input_dir = tmp_path / "input"
        input_dir.mkdir()

        entries = build_knowledge_entries(ki, input_dir)
        assert len(entries) == 1
        assert "missing" in entries[0][1]

    def test_empty_index(self, tmp_path):
        ki = tmp_path / "knowledge_index.jsonl"
        ki.write_text("")
        entries = build_knowledge_entries(ki, tmp_path)
        assert entries == []

    def test_no_file(self, tmp_path):
        entries = build_knowledge_entries(tmp_path / "nonexistent.jsonl", tmp_path)
        assert entries == []


class TestBuildBeliefEntries:
    def test_basic(self, tmp_path):
        bf = tmp_path / "beliefs.jsonl"
        bf.write_text(
            json.dumps({"entity": "fizyka", "content": "Fizyka jest nauka o naturze", "tags": ["nauka"], "confidence": 0.7}, ensure_ascii=False) + "\n"
            + json.dumps({"entity": "chemia", "content": "Chemia bada materie", "tags": ["materia"], "confidence": 0.5}, ensure_ascii=False) + "\n"
        )
        entries = build_belief_entries(bf)
        assert len(entries) == 2
        assert any("fizyka" in e[0] for e in entries)
        assert any("Fizyka jest nauka" in e[1] for e in entries)

    def test_merge_semantics(self, tmp_path):
        bf = tmp_path / "beliefs.jsonl"
        bf.write_text(
            json.dumps({"entity": "fizyka", "content": "old", "tags": [], "confidence": 0.3}, ensure_ascii=False) + "\n"
            + json.dumps({"entity": "fizyka", "content": "updated", "tags": [], "confidence": 0.7}, ensure_ascii=False) + "\n"
        )
        entries = build_belief_entries(bf)
        assert len(entries) == 1  # Merged
        assert "updated" in entries[0][1]

    def test_tags_included(self, tmp_path):
        bf = tmp_path / "beliefs.jsonl"
        bf.write_text(json.dumps({
            "entity": "test", "content": "test content",
            "tags": ["tag1", "tag2"], "confidence": 0.5,
        }, ensure_ascii=False) + "\n")
        entries = build_belief_entries(bf)
        assert "tag1" in entries[0][1]


class TestBuildHintEntries:
    def test_basic(self, tmp_path):
        hf = tmp_path / "topic_hints.jsonl"
        hf.write_text(
            json.dumps({"topic": "logika formalna", "source": "self_analysis", "consumed": False}) + "\n"
        )
        entries = build_hint_entries(hf)
        assert len(entries) == 1
        assert "logika formalna" in entries[0][1]

    def test_empty_topic_skipped(self, tmp_path):
        hf = tmp_path / "topic_hints.jsonl"
        hf.write_text(json.dumps({"topic": "", "source": "test"}) + "\n")
        entries = build_hint_entries(hf)
        assert entries == []


class TestRunInitialIndexing:
    def test_indexes_all_sources(self, tmp_path):
        data_dir = tmp_path / "meta_data"
        data_dir.mkdir()
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create knowledge
        (memory_dir / "knowledge_index.jsonl").write_text(
            json.dumps({"id": "f1.txt", "file": "f1.txt", "status": "completed"}) + "\n"
        )
        (input_dir / "f1.txt").write_text("# Tytul: Fizyka\nContent\n")

        # Create beliefs
        (data_dir / "beliefs.jsonl").write_text(
            json.dumps({"entity": "e1", "content": "belief1", "tags": [], "confidence": 0.5}, ensure_ascii=False) + "\n"
        )

        # Create hints
        (data_dir / "topic_hints.jsonl").write_text(
            json.dumps({"topic": "logika", "source": "test"}) + "\n"
        )

        sm = _mock_semantic_memory()
        counts = run_initial_indexing(sm, str(data_dir), str(memory_dir), str(input_dir))

        assert counts["knowledge"] == 1
        assert counts["beliefs"] == 1
        assert counts["hints"] == 1
        assert sm.index_batch.call_count == 3
        sm.save.assert_called_once()

    def test_handles_missing_files(self, tmp_path):
        data_dir = tmp_path / "meta_data"
        data_dir.mkdir()
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        sm = _mock_semantic_memory()
        counts = run_initial_indexing(sm, str(data_dir), str(memory_dir), str(tmp_path / "input"))
        assert counts == {}


class TestBackgroundIndexing:
    def test_starts_and_completes(self, tmp_path):
        data_dir = tmp_path / "meta_data"
        data_dir.mkdir()
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        sm = _mock_semantic_memory()
        t = start_background_indexing(sm, str(data_dir), str(memory_dir), str(tmp_path), delay_sec=0)
        t.join(timeout=5)
        assert not t.is_alive()

    def test_survives_error(self, tmp_path):
        sm = MagicMock()
        sm.index_batch = MagicMock(side_effect=RuntimeError("boom"))
        sm.save = MagicMock()

        t = start_background_indexing(sm, "/nonexistent", "/nonexistent", "/nonexistent", delay_sec=0)
        t.join(timeout=5)
        assert not t.is_alive()  # Should not crash
