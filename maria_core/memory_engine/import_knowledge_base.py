# import_knowledge_base.py
import json
from pathlib import Path
from maria_core.memory_engine.semantic_graph import SemanticGraph

BASE_DIR = Path(__file__).parent
KB_FILE = BASE_DIR / "maria_knowledge_base.jsonl"

def import_kb_to_graph(graph: SemanticGraph):
    if not KB_FILE.exists():
        print("[KB] Brak pliku maria_knowledge_base.jsonl")
        return

    with open(KB_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            concept = entry.get("concept")
            definition = entry.get("definition", "")
            example = entry.get("example", "")

            node_id = graph.add_node(
                label=concept,
                node_type="concept",
                attributes={
                    "definition": definition,
                    "example": example,
                    "source": "logic_teacher_kb",
                },
                confidence=0.8,
                source="logic_teacher_kb",
            )

            kb_node = graph.add_node("Knowledge Base (logic)", node_type="container")
            graph.add_edge(kb_node, "contains", node_id, source="logic_teacher_kb", confidence=0.8)

    print("[KB] [OK] Zaimportowano baze wiedzy do grafu")

