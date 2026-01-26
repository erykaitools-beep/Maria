class Node:
    def __init__(self, node_id, label, node_type="entity", attributes=None, embedding=None):
        self.id = node_id
        self.label = label
        self.type = node_type
        self.attributes = attributes or {}
        self.embedding = embedding
        self.access_count = 0
        self.confidence = 1.0

    def update_metadata(self, confidence=None):
        if confidence is not None:
            self.confidence = max(self.confidence, confidence)
