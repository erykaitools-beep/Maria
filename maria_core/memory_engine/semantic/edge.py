class Edge:
    def __init__(self, edge_id, from_id, relation, to_id, weight=1.0, confidence=1.0):
        self.id = edge_id
        self.from_id = from_id
        self.relation = relation
        self.to_id = to_id
        self.weight = weight
        self.confidence = confidence
        self.access_count = 0
