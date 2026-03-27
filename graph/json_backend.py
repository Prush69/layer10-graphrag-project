import json
from pathlib import Path
from typing import Optional

class JSONBackend:
    """Fallback backend that saves everything to a local JSON file."""
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.nodes = {} # id -> attrs
        self.edges = [] # list of attrs
        self.load()

    def load(self):
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    nodes_data = data.get("nodes", {})
                    if isinstance(nodes_data, list):
                        self.nodes = {n["id"]: n for n in nodes_data if "id" in n}
                    else:
                        self.nodes = nodes_data
                    edges_data = data.get("edges", data.get("links", []))
                    self.edges = []
                    for e in edges_data:
                        e["_source"] = e.get("_source") or e.get("source")
                        e["_target"] = e.get("_target") or e.get("target")
                        e["_key"] = e.get("_key") or e.get("key")
                        self.edges.append(e)
            except:
                self.nodes = {}
                self.edges = []

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": self.nodes, "edges": self.edges}, f, indent=2)

    def add_node(self, node_id: str, **attrs) -> bool:
        self.nodes[node_id] = attrs
        self.nodes[node_id]["id"] = node_id
        self.save()
        return True

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def get_node(self, node_id: str) -> Optional[dict]:
        return self.nodes.get(node_id)

    def update_node(self, node_id: str, **attrs):
        if node_id in self.nodes:
            self.nodes[node_id].update(attrs)
            self.save()

    def add_edge(self, source: str, target: str, key: str = None, **attrs) -> bool:
        edge = attrs.copy()
        edge["_source"] = source
        edge["_target"] = target
        edge["_key"] = key
        self.edges.append(edge)
        self.save()
        return True

    def get_out_edges(self, node_id: str) -> list[dict]:
        return [e for e in self.edges if e["_source"] == node_id]

    def get_in_edges(self, node_id: str) -> list[dict]:
        return [e for e in self.edges if e["_target"] == node_id]

    def get_all_nodes(self) -> list[tuple[str, dict]]:
        return list(self.nodes.items())

    def get_all_edges(self) -> list[dict]:
        return self.edges

    def node_count(self) -> int:
        return len(self.nodes)

    def edge_count(self) -> int:
        return len(self.edges)

    def clear(self):
        self.nodes = {}
        self.edges = []
        self.save()
    
    def close(self):
        pass
