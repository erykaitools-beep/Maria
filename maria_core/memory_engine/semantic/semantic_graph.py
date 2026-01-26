from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict, deque
import json
from datetime import datetime
import math


class SemanticGraph:
    """
    Główna klasa grafu semantycznego.
    """

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}          # {node_id: node_dict}
        self.edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}  # {(from_id, relation, to_id): edge_dict}
        self.subgraphs = {}      # {name: SubGraph}

        # Indeksy do szybkiego wyszukiwania
        self.node_index_by_label = defaultdict(list)   # {label: [node_ids]}
        self.node_index_by_type = defaultdict(list)    # {type: [node_ids]}
        self.relation_index = defaultdict(list)        # {relation: [edge_keys]}

        # Meta-informacje
        self.creation_time = datetime.now()
        self.last_consolidation: Optional[datetime] = None
        self.stats = {
            "total_nodes": 0,
            "total_edges": 0,
            "conflicts_detected": 0,
            "nodes_consolidated": 0
        }

    # ================== DODAWANIE WĘZŁÓW ==================

    def add_node(
        self,
        label: str,
        node_type: str = "entity",
        attributes: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        confidence: float = 1.0,
        source: str = "unknown"
    ) -> str:
        """Dodaj nowy węzeł lub aktualizuj istniejący"""
        # Sprawdź, czy węzeł już istnieje
        existing = self.find_node_by_label(label, node_type)

        if existing:
            # Aktualizuj zamiast tworzyć duplikat
            existing["confidence"] = max(existing.get("confidence", 1.0), confidence)
            existing["updated_at"] = datetime.now().isoformat()
            return existing["id"]

        # Stwórz nowy węzeł (dict zamiast obiektu)
        node_id = f"node:{len(self.nodes):05d}"
        now = datetime.now().isoformat()
        node = {
            "id": node_id,
            "label": label,
            "type": node_type,
            "attributes": attributes or {},
            "embedding": embedding,
            "confidence": confidence,
            "source": source,
            "created_at": now,
            "updated_at": now,
            "access_count": 0,
            "importance": 0.5,
            "is_outdated": False,
            "superseded_by": None
        }

        self.nodes[node_id] = node
        self.node_index_by_label[label].append(node_id)
        self.node_index_by_type[node_type].append(node_id)

        self.stats["total_nodes"] = len(self.nodes)

        return node_id

    # ================== DODAWANIE KRAWĘDZI ==================

    def add_edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        weight: float = 1.0,
        confidence: float = 1.0,
        source: str = "unknown"
    ):
        """Dodaj krawędź między węzłami"""
        if from_id not in self.nodes or to_id not in self.nodes:
            raise ValueError(f"Jeden z węzłów nie istnieje: {from_id} -> {to_id}")

        edge_key = (from_id, relation, to_id)

        # Sprawdź duplikat
        if edge_key in self.edges:
            # Wzmocnij istniejącą krawędź
            self.edges[edge_key]["weight"] = min(
                2.0,
                weight + self.edges[edge_key].get("weight", 1.0)
            )
            self.edges[edge_key]["confidence"] = max(
                confidence,
                self.edges[edge_key].get("confidence", 1.0)
            )
            return

        edge = {
            "id": f"edge:{len(self.edges):05d}",
            "from": from_id,
            "relation": relation,
            "to": to_id,
            "weight": weight,
            "confidence": confidence,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "access_count": 0
        }

        self.edges[edge_key] = edge
        self.relation_index[relation].append(edge_key)

        self.stats["total_edges"] = len(self.edges)

    # ================== WYSZUKIWANIE WĘZŁÓW ==================

    def find_node_by_label(self, label: str, node_type: Optional[str] = None):
        """Znajdź węzeł po etykiecie"""
        candidates = self.node_index_by_label.get(label, [])

        if not candidates:
            return None

        if node_type is None:
            return self.nodes[candidates[0]]

        for node_id in candidates:
            if self.nodes[node_id]["type"] == node_type:
                return self.nodes[node_id]

        return None

    def find_nodes_by_type(self, node_type: str):
        """Znajdź wszystkie węzły danego typu"""
        node_ids = self.node_index_by_type[node_type]
        return [self.nodes[nid] for nid in node_ids]

    # ================== SEMANTIC SIMILARITY ==================

    def semantic_similarity_search(
        self,
        embedding: List[float],
        top_k: int = 10,
        node_type: Optional[str] = None
    ):
        """Wyszukiwanie po podobieństwie wektorów (cosine similarity)."""
        if not embedding:
            return []

        candidates: List[Tuple[str, float]] = []

        for node_id, node in self.nodes.items():
            if node.get("embedding") is None:
                continue

            if node_type and node["type"] != node_type:
                continue

            similarity = self._cosine_similarity(embedding, node["embedding"])
            candidates.append((node_id, similarity))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return [(self.nodes[nid], sim) for nid, sim in candidates[:top_k]]

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Cosine similarity między dwoma wektorami"""
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a ** 2 for a in vec1))
        norm2 = math.sqrt(sum(b ** 2 for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    # ================== TRAVERSALE GRAFU (BFS/DFS) ==================

    def query(
        self,
        start_node_id: str,
        allowed_relations: Optional[List[str]] = None,
        max_depth: int = 2,
        strategy: str = "bfs"
    ):
        """
        Traversuj graf od startowego węzła.
        Zwraca listę węzłów (dict) posortowanych po ważności.
        """
        if start_node_id not in self.nodes:
            return []

        visited: Set[str] = set()
        results: List[Dict[str, Any]] = []

        if strategy == "bfs":
            queue = deque([(start_node_id, 0)])
        else:  # dfs
            queue = [(start_node_id, 0)]

        while queue:
            if strategy == "bfs":
                current_id, depth = queue.popleft()
            else:
                current_id, depth = queue.pop()

            if current_id in visited or depth > max_depth:
                continue

            visited.add(current_id)
            current_node = self.nodes[current_id]

            if current_id != start_node_id:
                results.append(current_node)

            current_node["access_count"] = current_node.get("access_count", 0) + 1

            for (from_id, relation, to_id), edge in self.edges.items():
                if allowed_relations and relation not in allowed_relations:
                    continue
                if from_id == current_id and to_id not in visited:
                    queue.append((to_id, depth + 1))

        results.sort(
            key=lambda n: n.get("confidence", 1.0) * (n.get("access_count", 0) + 0.1),
            reverse=True
        )
        return results

    # ================== DETEKCJA SPRZECZNOŚCI ==================

    def detect_contradictions(self) -> List[Dict[str, Any]]:
        """Wykryj sprzeczne informacje w grafie."""
        contradictions: List[Dict[str, Any]] = []

        opposite_relations = {
            "isTrue": "isFalse",
            "isCapitalOf": "isNotCapitalOf",
            "equals": "notEquals"
        }

        for (from_id, rel, to_id), edge1 in self.edges.items():
            opposite_rel = opposite_relations.get(rel)
            if not opposite_rel:
                continue

            for (from_id2, rel2, to_id2), edge2 in self.edges.items():
                if from_id == from_id2 and rel2 == opposite_rel and to_id == to_id2:
                    contradictions.append({
                        "edge1": (from_id, rel, to_id),
                        "edge2": (from_id2, rel2, to_id2),
                        "severity": "high",
                        "resolution": "needs_manual_review"
                    })

        self.stats["conflicts_detected"] = len(contradictions)
        return contradictions

    # ================== KONSOLIDACJA WIEDZY ==================

    def consolidate(self):
        """Tło proces: scal duplikaty, abstrakcje, pruning."""
        self._merge_similar_nodes()
        self._update_importance_scores()
        self._prune_low_importance_nodes()
        self.last_consolidation = datetime.now()

    def _merge_similar_nodes(self, threshold: float = 0.9):
        merged_count = 0
        labels = list(self.node_index_by_label.keys())

        for i, label1 in enumerate(labels):
            for label2 in labels[i+1:]:
                if self._string_similarity(label1, label2) > threshold:
                    nodes1 = [self.nodes[nid] for nid in self.node_index_by_label[label1]]
                    nodes2 = [self.nodes[nid] for nid in self.node_index_by_label[label2]]

                    winner = max(
                        nodes1 + nodes2,
                        key=lambda n: n.get("confidence", 1.0) * (n.get("access_count", 0) + 1)
                    )

                    for node in nodes1 + nodes2:
                        if node["id"] != winner["id"]:
                            node["is_outdated"] = True
                            node["superseded_by"] = winner["id"]
                            merged_count += 1

        self.stats["nodes_consolidated"] = merged_count

    def _update_importance_scores(self):
        for node in self.nodes.values():
            access_boost = math.log(node.get("access_count", 0) + 2)
            node["importance"] = node.get("confidence", 1.0) * min(1.0, access_boost / 10)

    def _prune_low_importance_nodes(self, threshold: float = 0.1):
        to_remove: List[str] = []

        for node_id, node in list(self.nodes.items()):
            if node.get("importance", 0) < threshold and node.get("access_count", 0) < 2:
                to_remove.append(node_id)

        for node_id in to_remove:
            del self.nodes[node_id]
            edges_to_remove = [
                key for key in list(self.edges.keys())
                if key[0] == node_id or key[2] == node_id
            ]
            for edge_key in edges_to_remove:
                del self.edges[edge_key]

    @staticmethod
    def _string_similarity(s1: str, s2: str) -> float:
        set1 = set(s1.lower())
        set2 = set(s2.lower())

        if not set1 and not set2:
            return 1.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    # ================== SERIALIZACJA ==================

    def to_dict(self):
        return {
            "nodes": self.nodes,
            "edges": {"|".join(k): v for k, v in self.edges.items()},
            "stats": self.stats,
            "last_consolidation": self.last_consolidation.isoformat() if self.last_consolidation else None
        }

    def save_to_json(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def load_from_json(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.nodes = data.get("nodes", {})
        self.edges = {}
        for k, v in data.get("edges", {}).items():
            from_id, relation, to_id = k.split("|")
            self.edges[(from_id, relation, to_id)] = v

        self.stats = data.get("stats", {})

        # wyczyść i odbuduj indeksy
        self.node_index_by_label = defaultdict(list)
        self.node_index_by_type = defaultdict(list)
        self.relation_index = defaultdict(list)

        for node_id, node in self.nodes.items():
            self.node_index_by_label[node["label"]].append(node_id)
            self.node_index_by_type[node["type"]].append(node_id)

        for (from_id, relation, to_id) in self.edges.keys():
            self.relation_index[relation].append((from_id, relation, to_id))

        # zaktualizuj statystyki
        self.stats["total_nodes"] = len(self.nodes)
        self.stats["total_edges"] = len(self.edges)
