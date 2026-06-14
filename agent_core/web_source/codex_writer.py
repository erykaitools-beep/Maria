"""
Codex writer — request a Polish educational article from ChatGPT (Codex CLI)
and drop it into input/ so Maria's learning pipeline can pick it up.

Operator-gated: the only entry points are explicit operator triggers
(Telegram /codexwrite <topic>, REPL command). No autonomous loop here —
that path will land later behind a K12 PROPOSED goal so we don't burn
the 10/h Codex quota.

Pipeline:
    operator types `/codexwrite mechanika kwantowa`
        ↓
    Codex CLI is asked for ~600-1200 word PL article
        ↓
    response saved as input/codex_<slug>.txt via ContentWriter
        ↓
    FetchRegistry registers the synthetic URL "codex://<slug>"
        ↓
    KnowledgeAnalyzer picks the file up next learning cycle
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default Codex prompt — keeps the output stable enough for the learning
# pipeline (chunked, factual, Polish, no marketing fluff).
DEFAULT_PROMPT_TEMPLATE = (
    "Napisz dla mnie rzeczowy, edukacyjny artykul po polsku na temat: \"{topic}\".\n"
    "Wymagania:\n"
    "- 600-1200 slow w czystym tekscie (bez markdown, bez naglowkow #, "
    "bez list punktowanych — pisz akapitami).\n"
    "- Wprowadzenie, glowne pojecia, najwazniejsze fakty, kontekst, "
    "ograniczenia/otwarte pytania.\n"
    "- Polski, neutralna polszczyzna, BEZ polskich znakow diakrytycznych "
    "(uzywaj 'a' zamiast 'a', 's' zamiast 's', itd.).\n"
    "- Bez wstepu typu \"Oto artykul...\" — od razu konkret.\n"
    "- Bez przypisow, bez linkow, bez emoji.\n"
)

# Minimum length to accept Codex output as a usable article.
MIN_RESPONSE_CHARS = 400


def request_codex_article(
    topic: str,
    codex_client,
    writer,
    *,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    semantic_search=None,
    operator: str = "operator",
) -> Dict[str, Any]:
    """
    Ask Codex for an article and persist it under input/codex_<slug>.txt.

    Args:
        topic: Topic Maria should learn about. Free-form Polish phrase.
        codex_client: CodexClient instance (or None — we degrade cleanly).
        writer: ContentWriter instance (already wired with FetchRegistry).
        prompt_template: Override the default prompt if needed.
        semantic_search: Optional SemanticMemory; if provided we trigger
            incremental_index after a successful save so the new article
            is searchable immediately.
        operator: Identifier of who requested the write (audit trail only).

    Returns:
        Dict describing the outcome: {ok, filename, reason, chars, duration_ms,
        topic, error}.
    """
    started = time.time()
    result: Dict[str, Any] = {
        "ok": False,
        "topic": topic,
        "filename": None,
        "chars": 0,
        "duration_ms": 0,
        "reason": "",
        "operator": operator,
    }

    if not topic or not topic.strip():
        result["reason"] = "empty_topic"
        return result

    if codex_client is None:
        result["reason"] = "codex_client_unavailable"
        return result

    if not codex_client.is_available():
        result["reason"] = "codex_cli_not_installed"
        return result

    prompt = prompt_template.format(topic=topic.strip())
    response = codex_client.ask(
        prompt,
        source="codex_writer",
        context={"topic": topic, "operator": operator},
    )
    if response is None:
        # codex_client logs the exact reason (rate_limited, invoke_failed)
        # to codex_interactions.jsonl already; we just surface a hint.
        result["reason"] = "codex_call_failed_or_rate_limited"
        result["duration_ms"] = (time.time() - started) * 1000
        return result

    body = response.strip()
    if len(body) < MIN_RESPONSE_CHARS:
        result["reason"] = "response_too_short"
        result["chars"] = len(body)
        result["duration_ms"] = (time.time() - started) * 1000
        return result

    # Synthetic URL keeps FetchRegistry dedup working — re-asking the same
    # topic short-circuits before we burn another Codex call.
    synthetic_url = f"codex://{topic.strip().lower().replace(' ', '_')}"

    title = topic.strip().capitalize()
    filename = writer.write_article(
        title=title,
        content=body,
        url=synthetic_url,
        source_type="codex",
        topic=topic,
    )

    if not filename:
        result["reason"] = "writer_rejected"  # too short, dedup, or IO
        result["chars"] = len(body)
        result["duration_ms"] = (time.time() - started) * 1000
        return result

    if semantic_search is not None:
        try:
            from agent_core.routing.handlers import incremental_index
            incremental_index(semantic_search)
        except Exception as exc:
            logger.debug("[codex_writer] incremental_index skipped: %s", exc)

    result.update({
        "ok": True,
        "filename": filename,
        "chars": len(body),
        "duration_ms": (time.time() - started) * 1000,
        "reason": "saved",
    })
    logger.info(
        "[codex_writer] saved %s for topic=%r (%d chars, op=%s, %.0fms)",
        filename, topic, len(body), operator, result["duration_ms"],
    )
    return result
