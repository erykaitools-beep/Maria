"""
Tests for agent_core.web_source.codex_writer (R1.3 MVP).

CodexClient and incremental_index are mocked; we only verify the wiring.
"""

from pathlib import Path

import pytest

from agent_core.web_source.codex_writer import (
    request_codex_article,
    DEFAULT_PROMPT_TEMPLATE,
)
from agent_core.web_source.content_writer import ContentWriter
from agent_core.web_source.fetch_registry import FetchRegistry
from agent_core.llm.codex_client import CodexClient
from agent_core.tests.spec_helpers import specced


def _live_writer(tmp_path):
    registry = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
    writer = ContentWriter(input_dir=tmp_path, fetch_registry=registry)
    return writer, registry


class TestRequestCodexArticle:

    def test_empty_topic_short_circuits(self, tmp_path):
        writer, _ = _live_writer(tmp_path)
        codex = specced(CodexClient)
        out = request_codex_article(
            topic=" ", codex_client=codex, writer=writer,
        )
        assert out["ok"] is False
        assert out["reason"] == "empty_topic"
        codex.ask.assert_not_called()

    def test_no_codex_client(self, tmp_path):
        writer, _ = _live_writer(tmp_path)
        out = request_codex_article(
            topic="fizyka", codex_client=None, writer=writer,
        )
        assert out["ok"] is False
        assert out["reason"] == "codex_client_unavailable"

    def test_cli_not_installed(self, tmp_path):
        writer, _ = _live_writer(tmp_path)
        codex = specced(CodexClient)
        codex.is_available.return_value = False
        out = request_codex_article(
            topic="fizyka", codex_client=codex, writer=writer,
        )
        assert out["ok"] is False
        assert out["reason"] == "codex_cli_not_installed"
        codex.ask.assert_not_called()

    def test_ask_returns_none_means_failed(self, tmp_path):
        writer, _ = _live_writer(tmp_path)
        codex = specced(CodexClient)
        codex.is_available.return_value = True
        codex.ask.return_value = None  # rate-limited or invoke_failed
        out = request_codex_article(
            topic="fizyka", codex_client=codex, writer=writer,
        )
        assert out["ok"] is False
        assert out["reason"] == "codex_call_failed_or_rate_limited"

    def test_response_too_short_rejected(self, tmp_path):
        writer, _ = _live_writer(tmp_path)
        codex = specced(CodexClient)
        codex.is_available.return_value = True
        codex.ask.return_value = "krotka odpowiedz"  # < 400 chars
        out = request_codex_article(
            topic="fizyka", codex_client=codex, writer=writer,
        )
        assert out["ok"] is False
        assert out["reason"] == "response_too_short"

    def test_happy_path_writes_file_and_registers(self, tmp_path):
        writer, registry = _live_writer(tmp_path)
        codex = specced(CodexClient)
        codex.is_available.return_value = True
        body = (
            "Mechanika kwantowa to dzial fizyki opisujacy zachowanie "
            "obiektow w skali atomowej. " * 20
        )
        codex.ask.return_value = body
        out = request_codex_article(
            topic="mechanika kwantowa",
            codex_client=codex,
            writer=writer,
            operator="telegram",
        )
        assert out["ok"] is True
        assert out["filename"].startswith("codex_")
        assert (tmp_path / out["filename"]).exists()
        # Synthetic URL is registered for dedup
        assert registry.is_fetched("codex://mechanika_kwantowa")

    def test_dedup_prevents_second_call(self, tmp_path):
        writer, _ = _live_writer(tmp_path)
        codex = specced(CodexClient)
        codex.is_available.return_value = True
        body = "Tresc edukacyjna. " * 60
        codex.ask.return_value = body

        first = request_codex_article(
            topic="logika", codex_client=codex, writer=writer,
        )
        assert first["ok"] is True

        second = request_codex_article(
            topic="logika", codex_client=codex, writer=writer,
        )
        # Codex was called both times (still hits the API), but the writer
        # rejects the duplicate URL — operator notices via reason field.
        assert second["ok"] is False
        assert second["reason"] == "writer_rejected"

    def test_prompt_template_includes_topic(self, tmp_path):
        writer, _ = _live_writer(tmp_path)
        codex = specced(CodexClient)
        codex.is_available.return_value = True
        codex.ask.return_value = "x" * 500
        request_codex_article(
            topic="biologia molekularna",
            codex_client=codex, writer=writer,
        )
        prompt_arg = codex.ask.call_args.args[0]
        assert "biologia molekularna" in prompt_arg

    def test_default_prompt_asks_for_article(self):
        # Sanity check that the template still expects a Polish article
        formatted = DEFAULT_PROMPT_TEMPLATE.format(topic="logika")
        assert "logika" in formatted
        assert "po polsku" in formatted.lower()


class TestContentWriterCodexPrefix:
    """ContentWriter must produce codex_<slug>.txt for source_type=codex (R1.3)."""

    def test_codex_prefix(self, tmp_path):
        registry = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        writer = ContentWriter(input_dir=tmp_path, fetch_registry=registry)
        body = "Tresc edukacyjna o fizyce. " * 30
        filename = writer.write_article(
            title="Fizyka kwantowa",
            content=body,
            url="codex://fizyka_kwantowa",
            source_type="codex",
        )
        assert filename is not None
        assert filename.startswith("codex_")
        assert "fizyka_kwantowa" in filename
        # Wiki/RSS prefixes still work
        assert filename != "web_wiki_fizyka_kwantowa.txt"

    def test_wiki_prefix_unchanged(self, tmp_path):
        registry = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        writer = ContentWriter(input_dir=tmp_path, fetch_registry=registry)
        body = "Tresc Wikipedii. " * 30
        filename = writer.write_article(
            title="Logika",
            content=body,
            url="https://pl.wikipedia.org/wiki/Logika",
            source_type="wikipedia",
        )
        assert filename == "web_wiki_logika.txt"
