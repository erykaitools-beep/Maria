# semantic_bridge.py
from maria_core.memory_engine.semantic.semantic_graph import SemanticGraph

semantic_memory = SemanticGraph()

def remember_fact(subject: str, relation: str, obj: str):
    # proste ID – możesz później zastąpić swoim systemem ID
    subj_id = f"node:{subject}"
    obj_id = f"node:{obj}"

    if subj_id not in semantic_memory.nodes:
        semantic_memory.add_node(subj_id, label=subject, type="entity")
    if obj_id not in semantic_memory.nodes:
        semantic_memory.add_node(obj_id, label=obj, type="entity")

    semantic_memory.add_edge(subj_id, relation, obj_id)

def query_related(subject: str, relation: str, depth: int = 1):
    subj_id = f"node:{subject}"
    return semantic_memory.query(
        start_id=subj_id,
        allowed_relations=[relation],
        max_depth=depth
    )
