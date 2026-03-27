"""Auto-indexer for SemanticMemory.

Populates the vector store from Maria's JSONL data sources on startup.
Runs in a background thread to avoid blocking the tick loop.

Sources indexed:
    - knowledge_index.jsonl -> namespace "knowledge" (learning material topics)
    - beliefs.jsonl -> namespace "beliefs" (world model beliefs)
    - topic_hints.jsonl -> namespace "hints" (K12 suggestions)
    - input/ files -> extract title from header for richer knowledge embeddings
"""

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _extract_title_from_file(file_path: Path) -> str:
    """Extract human-readable title from input file header.

    Looks for lines like:
        # Tytul: Fizyka
        # Temat: logika formalna
    Falls back to cleaned filename.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for _ in range(5):  # Check first 5 lines
                line = f.readline()
                if not line:
                    break
                for prefix in ("# Tytul:", "# Temat:", "# Title:"):
                    if line.startswith(prefix):
                        return line[len(prefix):].strip()
    except (OSError, UnicodeDecodeError):
        pass

    # Fallback: clean filename
    name = file_path.stem
    # Remove prefixes like web_wiki_, web_rss_, input_NNN_, expert_
    name = re.sub(r'^(web_wiki_|web_rss_|input_\d+_|expert_)', '', name)
    return name.replace('_', ' ')


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load all records from a JSONL file."""
    records = []
    if not path.exists():
        return records
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning(f"[INDEXER] Cannot read {path}: {e}")
    return records


def build_knowledge_entries(
    knowledge_path: Path,
    input_dir: Path,
) -> List[Tuple[str, str]]:
    """Build (entry_id, text) pairs from knowledge_index + input files.

    Embeds: title + filename + status info.
    """
    entries = []
    records = _load_jsonl(knowledge_path)

    for rec in records:
        file_id = rec.get("id", "")
        filename = rec.get("file", "")
        status = rec.get("status", "new")

        if not file_id:
            continue

        # Try to extract title from actual input file
        file_path = input_dir / filename
        title = _extract_title_from_file(file_path) if file_path.exists() else ""

        # Build embedding text: title is most semantic, filename as context
        if title:
            text = f"{title} ({filename}, status: {status})"
        else:
            clean_name = filename.replace('_', ' ').replace('.txt', '')
            text = f"{clean_name} (status: {status})"

        entries.append((f"knowledge:{file_id}", text))

    return entries


def build_belief_entries(beliefs_path: Path) -> List[Tuple[str, str]]:
    """Build (entry_id, text) pairs from beliefs.jsonl.

    Embeds: entity + content + tags.
    """
    entries = []
    # MERGE semantics: last record per entity wins
    beliefs = {}
    for rec in _load_jsonl(beliefs_path):
        entity = rec.get("entity", "")
        if entity:
            beliefs[entity] = rec

    for entity, rec in beliefs.items():
        content = rec.get("content", "")
        tags = rec.get("tags", [])
        confidence = rec.get("confidence", 0.0)

        text = content if content else entity
        if tags:
            text += f" (tagi: {', '.join(tags[:5])})"

        entries.append((f"belief:{entity[:50]}", text))

    return entries


def build_hint_entries(hints_path: Path) -> List[Tuple[str, str]]:
    """Build (entry_id, text) pairs from topic_hints.jsonl."""
    entries = []
    for rec in _load_jsonl(hints_path):
        topic = rec.get("topic", "")
        if not topic:
            continue
        source = rec.get("source", "self_analysis")
        consumed = rec.get("consumed", False)
        text = f"Sugestia nauki: {topic} (zrodlo: {source})"
        entries.append((f"hint:{topic[:50]}", text))
    return entries


def run_initial_indexing(semantic_memory, data_dir: str, memory_dir: str,
                         input_dir: str) -> Dict[str, int]:
    """Run full initial indexing of all sources.

    Returns dict with counts per namespace.
    """
    data_path = Path(data_dir)
    memory_path = Path(memory_dir)
    input_path = Path(input_dir)

    counts = {}
    start = time.time()

    # 1. Knowledge (from knowledge_index + input file titles)
    knowledge = build_knowledge_entries(
        memory_path / "knowledge_index.jsonl",
        input_path,
    )
    if knowledge:
        count = semantic_memory.index_batch("knowledge", knowledge)
        counts["knowledge"] = count
        logger.info(f"[INDEXER] Indexed {count} knowledge entries")

    # 2. Beliefs
    beliefs = build_belief_entries(data_path / "beliefs.jsonl")
    if beliefs:
        count = semantic_memory.index_batch("beliefs", beliefs)
        counts["beliefs"] = count
        logger.info(f"[INDEXER] Indexed {count} belief entries")

    # 3. Hints
    hints = build_hint_entries(data_path / "topic_hints.jsonl")
    if hints:
        count = semantic_memory.index_batch("hints", hints)
        counts["hints"] = count
        logger.info(f"[INDEXER] Indexed {count} hint entries")

    # Save vectors to JSONL
    saved = semantic_memory.save()

    elapsed = time.time() - start
    total = sum(counts.values())
    logger.info(
        f"[INDEXER] Initial indexing complete: {total} vectors "
        f"({counts}) in {elapsed:.1f}s, {saved} saved to disk"
    )

    return counts


def start_background_indexing(semantic_memory, data_dir: str, memory_dir: str,
                               input_dir: str) -> threading.Thread:
    """Start initial indexing in a background thread.

    Returns the thread (for join/monitoring).
    """
    def _run():
        try:
            run_initial_indexing(semantic_memory, data_dir, memory_dir, input_dir)
        except Exception as e:
            logger.error(f"[INDEXER] Background indexing failed: {e}")

    t = threading.Thread(target=_run, name="semantic-indexer", daemon=True)
    t.start()
    logger.info("[INDEXER] Background indexing started")
    return t
